"""Upload validation and error mapping for POST /reports/upload.

The explainer is mocked; nothing here calls Gemini.
"""
import logging

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import reports
from tests.conftest import make_pdf, server_error

FAKE_RESULT = {
    "disclaimer": "d",
    "emergency_notice": None,
    "document_type": "Complete Blood Count",
    "summary": "s",
    "markers": [],
    "recommendations": ["q1", "q2", "q3"],
}


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(upload_dir):
    return TestClient(app, raise_server_exceptions=False)


def post(client, data: bytes, name="report.pdf"):
    return client.post(
        "/reports/upload", files={"file": (name, data, "application/pdf")}
    )


def test_health(client):
    assert client.get("/health").json()["status"] == "healthy"


def test_rejects_non_pdf(client, upload_dir):
    r = post(client, b"\x89PNG\r\n\x1a\nnot a pdf", name="report.pdf")
    assert r.status_code == 400
    assert list(upload_dir.iterdir()) == []


def test_rejects_file_over_10mb(client, upload_dir):
    r = post(client, b"%PDF" + b"0" * (reports.MAX_BYTES))
    assert r.status_code == 413
    assert list(upload_dir.iterdir()) == []


def test_accepts_file_at_exactly_10mb_limit(client, monkeypatch):
    # Size check must allow MAX_BYTES itself; it then fails parsing, not size.
    monkeypatch.setattr(reports, "parse_pdf_text", lambda p: "")
    r = post(client, b"%PDF" + b"0" * (reports.MAX_BYTES - 4))
    assert r.status_code == 422


def test_pdf_without_text_returns_422(client, upload_dir, monkeypatch):
    called = []
    monkeypatch.setattr(reports, "generate_explanation", lambda t: called.append(t))
    r = post(client, make_pdf(None))
    assert r.status_code == 422
    assert called == []
    assert list(upload_dir.iterdir()) == []


def test_success_returns_explainer_fields(client, upload_dir, monkeypatch):
    seen = {}

    def fake_explain(text):
        seen["text"] = text
        return FAKE_RESULT

    monkeypatch.setattr(reports, "generate_explanation", fake_explain)
    r = post(client, make_pdf("Hemoglobin 10.2 g/dL"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    for key in ("disclaimer", "emergency_notice", "document_type",
                "summary", "markers", "recommendations"):
        assert key in body
    assert "Hemoglobin 10.2" in seen["text"]
    assert list(upload_dir.iterdir()) == []


def test_model_server_error_returns_503(client, upload_dir, monkeypatch):
    def boom(text):
        raise server_error()

    monkeypatch.setattr(reports, "generate_explanation", boom)
    r = post(client, make_pdf("Hemoglobin 10.2 g/dL"))
    assert r.status_code == 503
    assert list(upload_dir.iterdir()) == []


def test_unexpected_error_returns_generic_500_and_logs_type(
    client, upload_dir, monkeypatch, caplog
):
    def boom(text):
        raise KeyError("secret-internal-detail")

    monkeypatch.setattr(reports, "generate_explanation", boom)
    with caplog.at_level(logging.ERROR):
        r = post(client, make_pdf("Hemoglobin 10.2 g/dL"))

    assert r.status_code == 500
    assert r.json() == {"detail": "Could not process this report."}
    assert "secret-internal-detail" not in r.text
    record = next(rec for rec in caplog.records if rec.name == reports.logger.name)
    assert "KeyError" in record.getMessage()
    assert record.exc_info is not None  # traceback is logged
    assert list(upload_dir.iterdir()) == []


def test_error_outside_route_try_is_logged_by_global_handler(
    client, monkeypatch, caplog
):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(reports.uuid, "uuid4", boom)
    with caplog.at_level(logging.ERROR):
        r = post(client, make_pdf("x"))
    assert r.status_code == 500
    assert "disk full" not in r.text
    assert any("OSError" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_rate_limit_returns_503_not_500(client, upload_dir, monkeypatch):
    from google.genai import errors as genai_errors

    def boom(text):
        raise genai_errors.ClientError(
            429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
        )

    monkeypatch.setattr(reports, "generate_explanation", boom)
    r = post(client, make_pdf("Hemoglobin 10.2 g/dL"))
    assert r.status_code == 503
    assert list(upload_dir.iterdir()) == []
