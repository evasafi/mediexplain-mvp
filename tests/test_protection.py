"""Public-demo protections: access code, request caps, safe logging."""
import io
import logging
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import protection
from backend.logsafe import MASK, SafeFormatter, redact, safe_exception_text
from backend.main import app
from backend.protection import DAY_LIMIT, RequestCaps
from backend.routers import reports
from tests.conftest import make_pdf

FAKE_RESULT = {"markers": [], "summary": "s", "recommendations": []}
PDF = make_pdf("Hemoglobin 10.2 g/dL 12.0 - 15.5")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(reports, "generate_explanation", lambda text: dict(FAKE_RESULT))
    return TestClient(app, raise_server_exceptions=False)


def upload(client, code=None, ip=None):
    headers = {}
    if code is not None:
        headers["X-Access-Code"] = code
    if ip is not None:
        headers["X-Forwarded-For"] = ip
    return client.post("/reports/upload", files={"file": ("r.pdf", PDF, "application/pdf")},
                       headers=headers)


# --- 1) access code -----------------------------------------------------------------

def test_no_access_code_configured_means_no_check(client):
    assert upload(client).status_code == 200
    assert client.get("/health").json()["access_code_required"] is False


@pytest.mark.parametrize("code", [None, "", "wrong", "s3cret-demo ", "S3CRET-DEMO"])
def test_missing_or_wrong_code_is_401_with_friendly_message(client, monkeypatch, code):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    r = upload(client, code=code)
    assert r.status_code == 401
    assert r.json()["detail"] == protection.ACCESS_DENIED
    assert "s3cret-demo" not in r.text


def test_correct_code_is_accepted(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    assert upload(client, code="s3cret-demo").status_code == 200


def test_health_stays_open_and_says_code_is_needed(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["access_code_required"] is True
    assert "s3cret-demo" not in r.text


def test_code_is_compared_in_constant_time(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    calls = []
    real = protection.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(protection.hmac, "compare_digest", spy)
    upload(client, code="guess")
    assert calls == [(b"guess", b"s3cret-demo")]


def test_wrong_codes_do_not_use_up_the_caps(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "1")
    for _ in range(5):
        assert upload(client, code="wrong").status_code == 401
    assert upload(client, code="s3cret-demo").status_code == 200


def test_bad_code_is_rejected_before_any_processing(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    monkeypatch.setattr(reports, "extract_text", lambda *a: pytest.fail("must not read the file"))
    assert upload(client, code="wrong").status_code == 401


# --- 2) request caps -------------------------------------------------------------------

def test_per_ip_hourly_cap(client, monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "2")
    assert [upload(client).status_code for _ in range(3)] == [200, 200, 429]
    r = upload(client)
    assert r.status_code == 429
    assert r.json()["detail"] == protection.IP_LIMIT.format(n=2)
    assert int(r.headers["Retry-After"]) > 0


def test_global_daily_cap_across_ips(client, monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    monkeypatch.setenv("MAX_REQUESTS_PER_DAY", "3")
    codes = [upload(client, ip=f"10.0.0.{i}").status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]
    assert upload(client, ip="10.0.0.99").json()["detail"] == DAY_LIMIT


def test_rejected_requests_are_not_counted(client, monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "1")
    monkeypatch.setenv("MAX_REQUESTS_PER_DAY", "2")
    assert upload(client, ip="1.1.1.1").status_code == 200
    for _ in range(5):  # blocked by the per-IP cap; must not eat the daily budget
        assert upload(client, ip="1.1.1.1").status_code == 429
    assert upload(client, ip="2.2.2.2").status_code == 200


def test_forwarded_for_is_ignored_unless_trusted(client, monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "1")
    assert upload(client, ip="1.1.1.1").status_code == 200
    # Without TRUST_FORWARDED_FOR a faked header doesn't give a fresh allowance.
    assert upload(client, ip="2.2.2.2").status_code == 429


def test_health_is_never_capped(client, monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "1")
    upload(client)
    assert all(client.get("/health").status_code == 200 for _ in range(5))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_per_ip_window_rolls_after_an_hour(monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "2")
    clock = Clock(datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc).timestamp())
    caps = RequestCaps(clock=clock)
    caps.check_and_count("ip")
    clock.t += 1800
    caps.check_and_count("ip")
    with pytest.raises(HTTPException) as e:
        caps.check_and_count("ip")
    assert e.value.status_code == 429
    clock.t += 1801  # the first request is now more than an hour old
    caps.check_and_count("ip")


def test_daily_cap_resets_at_utc_midnight(monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_DAY", "1")
    clock = Clock(datetime(2026, 11, 13, 23, 59, tzinfo=timezone.utc).timestamp())
    caps = RequestCaps(clock=clock)
    caps.check_and_count("a")
    with pytest.raises(HTTPException) as e:
        caps.check_and_count("b")
    assert e.value.headers["Retry-After"] == "61"
    clock.t += 120  # 00:01 the next day
    caps.check_and_count("b")


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-5"])
def test_defaults_when_unset_or_invalid(monkeypatch, value):
    for name in ("MAX_REQUESTS_PER_DAY", "MAX_REQUESTS_PER_IP_PER_HOUR"):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    caps = RequestCaps(clock=Clock(1_800_000_000.0))
    for _ in range(protection.DEFAULT_PER_IP_PER_HOUR):
        caps.check_and_count("ip")
    with pytest.raises(HTTPException):
        caps.check_and_count("ip")
    for i in range(protection.DEFAULT_PER_DAY - protection.DEFAULT_PER_IP_PER_HOUR):
        caps.check_and_count(f"other-{i}")
    with pytest.raises(HTTPException) as e:
        caps.check_and_count("fresh")
    assert e.value.detail == DAY_LIMIT


def test_restart_resets_counters(monkeypatch):
    monkeypatch.setenv("MAX_REQUESTS_PER_IP_PER_HOUR", "1")
    caps = RequestCaps(clock=Clock(1_800_000_000.0))
    caps.check_and_count("ip")
    caps = RequestCaps(clock=Clock(1_800_000_000.0))  # what a restart does
    caps.check_and_count("ip")


# --- 4) logs never hold report text, the access code or API keys ----------------------------

REPORT_TEXT = "Hemoglobin 10.2 g/dL patient Jane Example"


def test_safe_traceback_has_types_but_not_messages():
    try:
        try:
            raise KeyError(REPORT_TEXT)
        except KeyError as inner:
            raise ValueError(f"model said: {REPORT_TEXT}") from inner
    except ValueError as e:
        text = safe_exception_text(e)
    assert "KeyError" in text and "ValueError" in text
    assert "test_protection.py" in text  # stack frames are kept
    assert REPORT_TEXT not in text and "Jane" not in text


def test_redact_masks_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKEKEY123456")
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    assert redact("key AIzaFAKEKEY123456 code s3cret-demo") == f"key {MASK} code {MASK}"


def test_upload_failure_logs_nothing_sensitive(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret-demo")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKEKEY123456")

    def boom(text):
        raise ValueError(f"bad model output for {text} key AIzaFAKEKEY123456")

    monkeypatch.setattr(reports, "generate_explanation", boom)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        r = client.post("/reports/upload",
                        files={"file": ("r.pdf", make_pdf(REPORT_TEXT), "application/pdf")},
                        headers={"X-Access-Code": "s3cret-demo"})
    finally:
        root.removeHandler(handler)
    log = stream.getvalue()
    assert r.status_code == 500
    assert "ValueError" in log  # the real type is still logged (task 1)
    for secret in ("Jane", "Hemoglobin 10.2", "s3cret-demo", "AIzaFAKEKEY123456"):
        assert secret not in log, secret
