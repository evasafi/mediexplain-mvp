"""Streamlit front end. The backend is mocked; nothing calls Gemini."""
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from frontend import app

APP_FILE = str(Path(__file__).resolve().parents[1] / "frontend" / "app.py")

RESULT = {
    "status": "success",
    "disclaimer": "Backend disclaimer text.",
    "emergency_notice": None,
    "document_type": "Complete Blood Count",
    "summary": "Some values are outside the printed range.",
    "markers": [
        {"name": "Hemoglobin", "value": "10.2", "unit": "g/dL", "reference_range": "12.0 - 15.5",
         "status": "low", "explanation": "Hemoglobin carries oxygen.", "verified": True,
         "range_status": "low", "lab_flag": "low", "verification_notes": []},
        {"name": "WBC", "value": "7.1", "unit": "x10^3/uL", "reference_range": "4.0 - 11.0",
         "status": "normal", "explanation": "White cells fight infection.", "verified": True,
         "range_status": "normal", "lab_flag": None, "verification_notes": []},
        {"name": "Platelets", "value": "450", "unit": "x10^3/uL", "reference_range": "150 - 400",
         "status": "high", "explanation": "Platelets help clotting.", "verified": False,
         "range_status": "high", "lab_flag": "high",
         "verification_notes": ["The value was not found in the report text."]},
    ],
    "recommendations": ["What may explain these results?", "What is the next step?"],
    "warnings": ["Platelets: the value 450 could not be found in your report."],
}


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


# ---- logic -------------------------------------------------------------------

@pytest.mark.parametrize("code", [400, 413, 422, 503])
def test_friendly_messages_for_known_errors(code):
    msg = app.friendly_error(code)
    assert msg != app.GENERIC_ERROR
    assert "HTTP" not in msg and str(code) not in msg


def test_422_and_503_messages_are_plain_language():
    assert "readable text" in app.friendly_error(422)
    assert "busy" in app.friendly_error(503)


def test_unknown_error_gets_generic_message():
    assert app.friendly_error(500) == app.GENERIC_ERROR


def test_explain_report_posts_to_configured_url(monkeypatch):
    seen = {}

    def fake_post(url, files, timeout):
        seen.update(url=url, files=files, timeout=timeout)
        return FakeResponse(200, RESULT)

    monkeypatch.setattr(app, "API_URL", "http://backend.test:9000")
    monkeypatch.setattr(app.requests, "post", fake_post)
    result, error = app.explain_report("r.pdf", b"%PDF data")
    assert error is None and result == RESULT
    assert seen["url"] == "http://backend.test:9000/reports/upload"
    assert seen["files"]["file"][0] == "r.pdf"


def test_api_url_comes_from_environment(monkeypatch):
    import importlib
    monkeypatch.setenv("MEDIEXPLAIN_API_URL", "http://example.test:1234/")
    reloaded = importlib.reload(app)
    try:
        assert reloaded.API_URL == "http://example.test:1234"
    finally:
        monkeypatch.delenv("MEDIEXPLAIN_API_URL")
        importlib.reload(app)


@pytest.mark.parametrize("code", [422, 503, 500])
def test_explain_report_maps_http_errors(monkeypatch, code):
    monkeypatch.setattr(app.requests, "post", lambda *a, **k: FakeResponse(code, {"detail": "x"}))
    result, error = app.explain_report("r.pdf", b"%PDF")
    assert result is None and error == app.friendly_error(code)


def test_explain_report_backend_down(monkeypatch):
    def down(*a, **k):
        raise requests.exceptions.ConnectionError()
    monkeypatch.setattr(app.requests, "post", down)
    result, error = app.explain_report("r.pdf", b"%PDF")
    assert result is None and "not reachable" in error


def test_explain_report_timeout_is_treated_as_busy(monkeypatch):
    def slow(*a, **k):
        raise requests.exceptions.ReadTimeout()
    monkeypatch.setattr(app.requests, "post", slow)
    assert app.explain_report("r.pdf", b"%PDF") == (None, app.FRIENDLY_ERRORS[503])


def test_oversize_file_is_rejected_before_upload(monkeypatch):
    def never(*a, **k):
        raise AssertionError("should not upload")
    monkeypatch.setattr(app.requests, "post", never)
    _, error = app.explain_report("r.pdf", b"0" * (app.MAX_BYTES + 1))
    assert error == app.FRIENDLY_ERRORS[413]


def test_markers_table_and_highlighting():
    df = app.markers_table(RESULT["markers"])
    assert list(df["Status"]) == ["LOW", "Normal", "HIGH"]
    assert list(df["Checked"]) == ["Yes", "Yes", "Please check"]
    html = app.style_table(df).to_html()
    assert app.STATUS_STYLE["LOW"].split(";")[0] in html
    assert app.STATUS_STYLE["HIGH"].split(";")[0] in html


def test_markers_table_handles_old_backend_without_verification_fields():
    m = {k: v for k, v in RESULT["markers"][0].items()
         if k in ("name", "value", "unit", "reference_range", "status", "explanation")}
    df = app.markers_table([m])
    assert list(df["Checked"]) == [""]


def test_questions_text_is_numbered():
    text = app.questions_text(["A?", "B?"])
    assert "1. A?" in text and "2. B?" in text


# ---- page rendering (AppTest) -------------------------------------------------

def run_app(result=None, error=None):
    at = AppTest.from_file(APP_FILE, default_timeout=30)
    if result is not None:
        at.session_state["result"] = result
    if error is not None:
        at.session_state["error"] = error
    return at.run()


def all_text(at):
    parts = [e.value for e in at.markdown] + [e.value for e in at.caption]
    parts += [e.value for e in at.info] + [e.value for e in at.error] + [e.value for e in at.warning]
    return "\n".join(str(p) for p in parts)


def test_initial_page_has_disclaimer_top_and_bottom():
    at = run_app()
    assert not at.exception
    assert at.info[0].value == app.DEFAULT_DISCLAIMER
    assert app.DEFAULT_DISCLAIMER in at.caption[-1].value


def test_result_page_renders_everything():
    at = run_app(result=RESULT)
    assert not at.exception
    text = all_text(at)
    # Backend disclaimer at top and bottom.
    assert at.info[0].value == "Backend disclaimer text."
    assert "Backend disclaimer text." in at.caption[-1].value
    assert "Complete Blood Count" in [s.value for s in at.subheader]
    assert RESULT["warnings"][0] in text
    assert len(at.dataframe) == 1
    assert [e.label for e in at.expander] == [
        "Hemoglobin: 10.2 g/dL (LOW)", "WBC: 7.1 x10^3/uL", "Platelets: 450 x10^3/uL (HIGH)",
    ]
    assert "1. What may explain these results?" in at.code[0].value
    assert not at.error  # no emergency notice


def test_emergency_notice_is_shown():
    at = run_app(result={**RESULT, "emergency_notice": "Seek care now."})
    assert at.error[0].value == "Seek care now."


def test_error_message_is_shown():
    at = run_app(error=app.FRIENDLY_ERRORS[503])
    assert at.error[0].value == app.FRIENDLY_ERRORS[503]
