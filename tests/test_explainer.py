"""Explainer tests with the Gemini client mocked."""
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from backend.services import explainer
from backend.services.explainer import Marker, ReportExplanation
from tests.conftest import server_error

PARSED = ReportExplanation(
    document_type="Complete Blood Count",
    summary="Some values are outside the printed range.",
    markers=[
        Marker(name="Hemoglobin", value="10.2", unit="g/dL",
               reference_range="13.0-17.0", status="low", explanation="e"),
    ],
    questions_for_doctor=["What may explain these results?"],
)


class FakeModels:
    def __init__(self, outcomes):
        # outcomes: list of exceptions or responses, consumed in order
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def use_fake(monkeypatch, outcomes):
    models = FakeModels(outcomes)
    client = SimpleNamespace(models=models)
    monkeypatch.setattr(explainer, "_get_client", lambda: client)
    return models


def ok(parsed=PARSED):
    return SimpleNamespace(parsed=parsed, text=parsed.model_dump_json())


def test_response_shape_and_code_added_disclaimer(monkeypatch):
    use_fake(monkeypatch, [ok()])
    out = explainer.generate_explanation("Hemoglobin 10.2 g/dL 13.0-17.0")
    # Original fields teammates build against, plus the added `warnings`.
    assert set(out) == {"disclaimer", "emergency_notice", "document_type",
                        "summary", "markers", "recommendations", "warnings"}
    assert out["disclaimer"] == explainer.DISCLAIMER
    assert out["emergency_notice"] is None
    original = {
        "name": "Hemoglobin", "value": "10.2", "unit": "g/dL",
        "reference_range": "13.0-17.0", "status": "low", "explanation": "e",
    }
    m = out["markers"][0]
    assert {k: m[k] for k in original} == original
    assert set(m) - set(original) == {"verified", "range_status", "lab_flag",
                                      "verification_notes"}
    # Report says 13.0-17.0, so 10.2 is low and the model's "low" verifies.
    assert m["verified"] is True and m["range_status"] == "low"
    assert out["warnings"] == []
    assert out["recommendations"] == PARSED.questions_for_doctor


def test_emergency_notice_added_by_code(monkeypatch):
    use_fake(monkeypatch, [ok()])
    out = explainer.generate_explanation("Potassium 7.1 CRITICAL VALUE called to ward")
    assert out["emergency_notice"] == explainer.EMERGENCY_NOTICE


def test_falls_back_to_json_text_when_parsed_missing(monkeypatch):
    use_fake(monkeypatch, [SimpleNamespace(parsed=None, text=PARSED.model_dump_json())])
    out = explainer.generate_explanation("report")
    assert out["document_type"] == "Complete Blood Count"


def test_prompt_wraps_report_and_uses_guardrailed_system_prompt(monkeypatch):
    models = use_fake(monkeypatch, [ok()])
    explainer.generate_explanation("REPORT BODY")
    call = models.calls[0]
    assert "<report>\nREPORT BODY" in call["contents"]
    assert call["config"].system_instruction == explainer.SYSTEM_PROMPT
    assert "Never diagnose" in explainer.SYSTEM_PROMPT
    assert "untrusted data" in explainer.SYSTEM_PROMPT


def test_text_is_truncated_to_max_chars(monkeypatch):
    models = use_fake(monkeypatch, [ok()])
    explainer.generate_explanation("Z" * (explainer.MAX_CHARS + 500))
    sent = models.calls[0]["contents"]
    assert sent.count("Z") == explainer.MAX_CHARS


def test_retries_then_falls_back_to_next_model(monkeypatch):
    models = use_fake(monkeypatch, [server_error()] * explainer.RETRIES + [ok()])
    out = explainer.generate_explanation("report")
    assert out["document_type"] == "Complete Blood Count"
    used = [c["model"] for c in models.calls]
    assert used == [explainer.MODELS[0]] * explainer.RETRIES + [explainer.MODELS[1]]


def test_raises_server_error_when_all_models_fail(monkeypatch):
    total = explainer.RETRIES * len(explainer.MODELS)
    models = use_fake(monkeypatch, [server_error()] * total)
    with pytest.raises(genai_errors.ServerError):
        explainer.generate_explanation("report")
    assert len(models.calls) == total


def not_found():
    return genai_errors.ClientError(
        404, {"error": {"code": 404, "message": "not found", "status": "NOT_FOUND"}}
    )


def test_missing_model_404_is_skipped_not_retried(monkeypatch):
    # Last model in the chain is retired: busy, busy, then 404 must still be a 503 path.
    outcomes = [server_error()] * explainer.RETRIES * 2 + [not_found()]
    models = use_fake(monkeypatch, outcomes)
    with pytest.raises(genai_errors.ServerError):
        explainer.generate_explanation("report")
    assert [c["model"] for c in models.calls].count(explainer.MODELS[2]) == 1


def test_404_on_first_model_falls_through_to_next(monkeypatch):
    models = use_fake(monkeypatch, [not_found(), ok()])
    out = explainer.generate_explanation("report")
    assert out["document_type"] == "Complete Blood Count"
    assert [c["model"] for c in models.calls] == explainer.MODELS[:2]


def test_other_client_errors_are_not_swallowed(monkeypatch):
    bad = genai_errors.ClientError(
        400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}}
    )
    use_fake(monkeypatch, [bad])
    with pytest.raises(genai_errors.ClientError):
        explainer.generate_explanation("report")


def test_client_has_timeout(monkeypatch):
    monkeypatch.undo()  # restore the real _get_client; no network call is made
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(explainer, "_client", None)
    client = explainer._get_client()
    assert client._api_client._http_options.timeout == explainer.TIMEOUT_MS


def rate_limited():
    return genai_errors.ClientError(
        429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )


def test_429_skips_to_next_model_without_retrying(monkeypatch):
    models = use_fake(monkeypatch, [rate_limited(), ok()])
    out = explainer.generate_explanation("report")
    assert out["document_type"] == "Complete Blood Count"
    assert [c["model"] for c in models.calls] == explainer.MODELS[:2]


def test_all_rate_limited_raises_429(monkeypatch):
    use_fake(monkeypatch, [rate_limited(), rate_limited(), not_found()])
    with pytest.raises(genai_errors.ClientError) as exc:
        explainer.generate_explanation("report")
    assert exc.value.code == 429
