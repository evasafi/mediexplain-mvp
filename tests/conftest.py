import pymupdf
import pytest
from google.genai import errors as genai_errors

from backend.services import explainer


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Fail loudly if any test tries to reach the real Gemini API."""
    def _blocked():
        raise AssertionError("Tests must not call the real model client.")
    monkeypatch.setattr(explainer, "_get_client", _blocked)
    monkeypatch.setattr(explainer.time, "sleep", lambda s: None)


def make_pdf(text: str | None) -> bytes:
    """Build a small in-memory PDF. `None` gives a page with no text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def server_error(code: int = 503) -> genai_errors.ServerError:
    return genai_errors.ServerError(
        code, {"error": {"code": code, "message": "busy", "status": "UNAVAILABLE"}}
    )
