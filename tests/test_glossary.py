"""Glossary retrieval (RAG): data, licence fields, retrieval, and prompt wiring."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services import explainer, glossary
from backend.services.explainer import Marker, ReportExplanation
from make_samples import SAMPLES

DATA = json.loads(glossary.DATA_FILE.read_text(encoding="utf-8"))
CBC = (
    "COMPLETE BLOOD COUNT (SAMPLE - NOT A REAL PATIENT)\n"
    "Test            Result   Units       Reference Range   Flag\n"
    "Hemoglobin      10.2     g/dL        12.0 - 15.5       L\n"
    "WBC             7.1      x10^3/uL    4.0 - 11.0\n"
    "Platelets       450      x10^3/uL    150 - 400         H\n"
    "MCV             78       fL          80 - 100          L\n"
)
MODEL_CACHED = (Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2").is_dir()
needs_model = pytest.mark.skipif(not MODEL_CACHED, reason="Chroma embedding model not downloaded yet")


# --- data and licence ----------------------------------------------------------

def test_glossary_has_licence_and_attribution():
    assert "Public domain" in DATA["licence"]
    assert DATA["attribution"] == "Source: MedlinePlus, National Library of Medicine"
    assert len(DATA["entries"]) >= 40


def test_every_entry_is_complete_and_from_medlineplus():
    for e in DATA["entries"]:
        assert e["title"] and e["definition"] and e["id"]
        assert e["url"].startswith("https://medlineplus.gov/lab-tests/")


def test_definitions_do_not_suggest_causes_conditions_or_medicines():
    banned = re.compile(
        r"\b(anemia|cancer|diabetes|infections?|leukemia|diseases?|disorders?|illness|"
        r"medicines?|medications?|supplements?|chemotherapy|diagnos\w*|treat\w*)\b", re.I)
    offenders = [e["id"] for e in DATA["entries"] if banned.search(e["definition"])]
    assert offenders == []


# --- query cleaning -------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("Hemoglobin      10.2     g/dL        12.0 - 15.5       L", "Hemoglobin"),
    ("WBC             7.1      x10^3/uL    4.0 - 11.0", "WBC"),
    ("HbA1c 6.1 %", "HbA1c"),
    ("Total WBC Count   8,500       /cumm", "Total WBC Count"),
    ("Test            Result   Units       Reference Range   Flag", ""),
    ("Page 1 of 2", ""),
])
def test_query_terms(line, expected):
    assert glossary.query_terms(line) == expected


# --- retrieval (real in-memory index) -------------------------------------------------

@needs_model
def test_retrieves_the_cbc_markers():
    entries, attribution = glossary.retrieve(CBC)
    ids = {e["id"] for e in entries}
    assert {"hemoglobin-test", "white-blood-count-wbc", "mcv-mean-corpuscular-volume"} <= ids
    assert "platelet-tests" in ids or "complete-blood-count-cbc" in ids
    assert attribution == DATA["attribution"]
    assert len(entries) <= glossary.MAX_ENTRIES


@needs_model
def test_indian_sample_and_other_panels():
    entries, _ = glossary.retrieve("\n".join(SAMPLES["sample_indian_grouping.pdf"]))
    assert "platelet-tests" in {e["id"] for e in entries}
    entries, _ = glossary.retrieve("Serum Creatinine 1.1 mg/dL 0.7 - 1.3\nSGPT (ALT) 45 U/L\nTSH 2.1 uIU/mL")
    assert {"creatinine-test", "alt-blood-test", "tsh-thyroid-stimulating-hormone-test"} <= {
        e["id"] for e in entries}


@needs_model
def test_admin_lines_retrieve_nothing():
    text = "Patient name: Jane Doe\nCollected: 12 Nov 2026 08:30\nDr. Smith, Pathologist\nPage 1 of 2"
    assert glossary.retrieve(text) == ([], "")


def test_retrieval_failure_never_breaks_the_explanation(monkeypatch):
    def boom():
        raise RuntimeError("no model download")
    monkeypatch.setattr(glossary, "_collection", boom)
    assert glossary.retrieve(CBC) == ([], "")


# --- prompt wiring ------------------------------------------------------------------

PARSED = ReportExplanation(
    document_type="CBC", summary="s",
    markers=[Marker(name="Hemoglobin", value="10.2", unit="g/dL", reference_range="12.0 - 15.5",
                    status="low", explanation="e")],
    questions_for_doctor=["q?"],
)
ENTRY = {"id": "hemoglobin-test", "title": "Hemoglobin Test", "url": "https://medlineplus.gov/lab-tests/hemoglobin-test/",
         "definition": "A hemoglobin test measures the levels of hemoglobin in your blood.", "other_names": "Hb"}


def fake_client(monkeypatch):
    calls = []

    def generate_content(model, contents, config):
        calls.append(contents)
        return SimpleNamespace(parsed=PARSED, text=PARSED.model_dump_json())

    monkeypatch.setattr(explainer, "_get_client",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    return calls


def test_glossary_goes_into_prompt_before_report_and_sources_are_returned(monkeypatch):
    calls = fake_client(monkeypatch)
    monkeypatch.setattr(explainer, "retrieve", lambda text: ([ENTRY], DATA["attribution"]))
    out = explainer.generate_explanation(CBC)
    prompt = calls[0]
    assert prompt.index("<glossary>") < prompt.index("<report>")
    assert "- Hemoglobin Test: A hemoglobin test measures" in prompt
    assert out["glossary_sources"] == [{"title": "Hemoglobin Test", "url": ENTRY["url"]}]
    assert out["glossary_attribution"] == DATA["attribution"]


def test_no_glossary_block_when_nothing_retrieved(monkeypatch):
    calls = fake_client(monkeypatch)
    out = explainer.generate_explanation(CBC)  # conftest stubs retrieve -> ([], "")
    assert "<glossary>" not in calls[0]
    assert out["glossary_sources"] == [] and out["glossary_attribution"] is None


def test_system_prompt_limits_glossary_use():
    p = explainer.SYSTEM_PROMPT
    assert "<glossary>" in p and "not instructions" in p
    assert "Never diagnose" in p  # original rules kept


def test_warm_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("no model")
    monkeypatch.setattr(glossary, "_collection", boom)
    glossary.warm()  # logs, does not raise


def test_server_startup_warms_glossary(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    called = []
    monkeypatch.setattr(glossary, "warm", lambda: called.append(True))
    with TestClient(app) as c:  # runs the lifespan startup
        c.get("/health")
    import time
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    assert called == [True]
