from types import SimpleNamespace

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
    # Skip retry back-off in the explainer only. Patching `explainer.time.sleep`
    # would replace time.sleep for the whole process and break other code
    # (Streamlit's AppTest runner busy-loops and times out).
    monkeypatch.setattr(explainer, "time", SimpleNamespace(sleep=lambda s: None))
    # Explainer tests don't depend on the glossary index; test_glossary.py covers it.
    monkeypatch.setattr(explainer, "retrieve", lambda text: ([], ""))


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
