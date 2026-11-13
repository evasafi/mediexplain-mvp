"""Lab-flag conflicts must show in the summary and the doctor questions."""
from types import SimpleNamespace

import pytest

from backend.services import explainer
from backend.services.conflicts import (
    MAX_QUESTIONS, MIN_QUESTIONS, conflict_question, find_conflicts, fix_questions, fix_summary,
)
from backend.services.explainer import Marker, ReportExplanation
from make_samples import SAMPLES

CONFLICT_TEXT = "\n".join(SAMPLES["sample_conflict_flag.pdf"]) + "\n\n"

WBC_CONFLICT = {"name": "WBC Count", "value": "4,200", "lab_flag": "low", "range_status": "normal"}
HB_OK = {"name": "Hemoglobin", "value": "14.1", "lab_flag": None, "range_status": "normal"}
PLT_FLAG_AGREES = {"name": "Platelets", "value": "450", "lab_flag": "high", "range_status": "high"}


# --- finding conflicts ------------------------------------------------------------

def test_find_conflicts_only_flag_vs_range_disagreements():
    unknown_range = {"name": "X", "lab_flag": "low", "range_status": "unknown"}
    assert find_conflicts([WBC_CONFLICT, HB_OK, PLT_FLAG_AGREES, unknown_range]) == [WBC_CONFLICT]


# --- fix 1: summary ---------------------------------------------------------------------

@pytest.mark.parametrize("claim", [
    "All values are within the normal range.",
    "All of your results are within range.",
    "Everything looks normal.",
    "Every value is inside the reference range.",
    "None of the results are outside the range.",
    "No values are flagged.",
    "All your results look healthy.",
])
def test_summary_drops_all_in_range_claims(claim):
    out = fix_summary(f"This is a blood count. {claim} Talk to your doctor.", [WBC_CONFLICT])
    assert claim not in out
    assert out.startswith("This is a blood count.")
    assert "Talk to your doctor." in out
    assert out.endswith(
        "One value needs checking: the lab's flag for WBC Count does not match "
        "the printed reference range."
    )


def test_summary_keeps_claims_that_are_not_all_fine():
    s = "Most values are within range. Hemoglobin is in range."
    out = fix_summary(s, [WBC_CONFLICT])
    assert out.startswith(s)


def test_summary_with_two_conflicts():
    other = {"name": "MCV", "lab_flag": "high", "range_status": "normal"}
    out = fix_summary("All values are normal.", [WBC_CONFLICT, other])
    assert "All values are normal." not in out
    assert out == ("2 values need checking: the lab's flags for WBC Count, MCV do not match "
                   "the printed reference ranges.")


def test_summary_untouched_without_conflict():
    s = "All values are within the normal range."
    assert fix_summary(s, []) == s


# --- fix 2: doctor questions -----------------------------------------------------------

def test_conflict_question_wording():
    assert conflict_question(WBC_CONFLICT) == (
        "The lab marked my WBC Count as LOW, but my value is inside the printed range. "
        "Which is correct?"
    )
    outside = {"name": "MCV", "lab_flag": "low", "range_status": "high"}
    assert "above the printed range" in conflict_question(outside)


def test_conflict_question_goes_first_and_total_stays_at_most_5():
    model_qs = [f"Question {i}?" for i in range(1, 6)]  # model already wrote 5
    out = fix_questions(model_qs, [WBC_CONFLICT])
    assert out[0] == conflict_question(WBC_CONFLICT)
    assert len(out) == MAX_QUESTIONS
    assert out[1:] == model_qs[:4]


def test_duplicate_model_question_about_the_flag_is_replaced():
    model_qs = [
        "What may explain my white blood cell count result given the lab flag?",
        "What may explain my WBC Count being flagged low?",
        "What is the next step?",
    ]
    out = fix_questions(model_qs, [WBC_CONFLICT])
    assert out[0] == conflict_question(WBC_CONFLICT)
    assert "What may explain my WBC Count being flagged low?" not in out
    assert MIN_QUESTIONS <= len(out) <= MAX_QUESTIONS


def test_minimum_of_3_questions_is_kept():
    out = fix_questions(["What may explain my WBC Count being flagged low?"], [WBC_CONFLICT])
    assert out[0] == conflict_question(WBC_CONFLICT)
    assert len(out) == MIN_QUESTIONS


def test_many_conflicts_still_cap_at_5():
    many = [{"name": f"Test{i}", "lab_flag": "high", "range_status": "normal"} for i in range(7)]
    out = fix_questions(["Q?"] * 3, many)
    assert len(out) == MAX_QUESTIONS
    assert all(q.startswith("The lab marked my Test") for q in out)


def test_questions_untouched_without_conflict():
    qs = ["A?", "B?", "C?"]
    assert fix_questions(qs, []) == qs


# --- end to end through the explainer (model mocked) -----------------------------------------

def run_with_model_answer(monkeypatch, summary, questions, wbc_status="normal"):
    parsed = ReportExplanation(
        document_type="Complete Blood Count",
        summary=summary,
        markers=[
            Marker(name="Hemoglobin", value="14.1", unit="g/dL", reference_range="13.0 - 17.0",
                   status="normal", explanation="e"),
            Marker(name="WBC Count", value="4,200", unit="/uL", reference_range="4,000 - 11,000",
                   status=wbc_status, explanation="e"),
            Marker(name="Platelets", value="250", unit="x10^3/uL", reference_range="150 - 400",
                   status="normal", explanation="e"),
        ],
        questions_for_doctor=questions,
    )
    client = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda model, contents, config: SimpleNamespace(
            parsed=parsed, text=parsed.model_dump_json())))
    monkeypatch.setattr(explainer, "_get_client", lambda: client)
    return explainer.generate_explanation(CONFLICT_TEXT)


@pytest.mark.parametrize("wbc_status", ["normal", "unknown", "low"])
def test_conflict_report_end_to_end(monkeypatch, wbc_status):
    out = run_with_model_answer(
        monkeypatch,
        summary="This is a blood count. All values are within the normal range.",
        questions=["What is the next step?", "Do I need any follow-up?", "Is this result typical?"],
        wbc_status=wbc_status,
    )
    assert "All values are within the normal range." not in out["summary"]
    assert "One value needs checking" in out["summary"] and "WBC Count" in out["summary"]
    assert out["recommendations"][0] == (
        "The lab marked my WBC Count as LOW, but my value is inside the printed range. "
        "Which is correct?"
    )
    assert MIN_QUESTIONS <= len(out["recommendations"]) <= MAX_QUESTIONS


def test_report_without_conflict_is_unchanged(monkeypatch):
    clean_text = CONFLICT_TEXT.replace("4,000 - 11,000    L", "4,000 - 11,000")
    parsed_summary = "All values are within the normal range."
    questions = ["What is the next step?", "Do I need any follow-up?", "Is this result typical?"]
    parsed = ReportExplanation(
        document_type="CBC", summary=parsed_summary,
        markers=[Marker(name="WBC Count", value="4,200", unit="/uL", reference_range="4,000 - 11,000",
                        status="normal", explanation="e")],
        questions_for_doctor=questions,
    )
    client = SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda model, contents, config: SimpleNamespace(
            parsed=parsed, text=parsed.model_dump_json())))
    monkeypatch.setattr(explainer, "_get_client", lambda: client)
    out = explainer.generate_explanation(clean_text)
    assert out["summary"] == parsed_summary
    assert out["recommendations"] == questions
