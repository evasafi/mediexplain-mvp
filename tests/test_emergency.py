"""Emergency wording check: whole words, reviewed list, narrow negation."""
import pytest

from backend.services.emergency import TERMS, find_emergency_terms


# --- should trigger -----------------------------------------------------------

@pytest.mark.parametrize("text,label", [
    ("Potassium 7.1 CRITICAL VALUE called to ward", "critical value"),
    ("Critical results phoned to Dr. A at 10:42", "critical value"),
    ("Glucose critically low", "critically high/low"),
    ("PANIC VALUE", "panic value"),
    ("Potentially life-threatening level", "life-threatening"),
    ("potentially life threatening", "life-threatening"),
    ("Please notify physician immediately", "notify clinician immediately"),
    ("Called the doctor immediately", "notify clinician immediately"),
    ("Requires immediate medical attention", "immediate medical attention"),
    ("Suspected sepsis", "sepsis"),
    ("Septic shock protocol", "sepsis"),
    ("Acute stroke suspected", "stroke"),
    ("Multi-organ failure", "organ failure"),
    ("cardiac arrest", "cardiac arrest"),
    ("respiratory failure", "respiratory failure"),
])
def test_triggers(text, label):
    assert label in find_emergency_terms(text)


def test_term_split_across_pdf_line_break():
    assert find_emergency_terms("Result flagged as critical\nvalue by lab") == ["critical value"]


def test_case_insensitive():
    assert find_emergency_terms("SePsIs") == ["sepsis"]


# --- must not trigger: inside longer words (the original bug) -----------------

@pytest.mark.parametrize("text", [
    "Brushstrokes and keystrokes",
    "heatstroke",
    "Aseptic technique used",
    "Antiseptic applied",
    "non-critical value",
    "Hypercritical values",
    "noncritical results",
    "stroke-volume",
])
def test_no_match_inside_longer_words(text):
    assert find_emergency_terms(text) == []


# --- must not trigger: excluded phrases and narrow negation -------------------

@pytest.mark.parametrize("text", [
    "Stroke volume 70 mL",            # echo measurement, not an event
    "Stroke index 40 mL/m2",
    "No critical values.",
    "No critical values were found in this report.",
    "Negative for sepsis",
    "No evidence of stroke",
    "History of stroke (2019)",
    "Not life-threatening",
])
def test_excluded_or_negated(text):
    assert find_emergency_terms(text) == []


def test_negation_only_applies_on_the_same_line():
    text = "Blood culture: no growth\nSepsis suspected, notify team"
    assert find_emergency_terms(text) == ["sepsis"]


def test_negation_only_cancels_its_own_term():
    text = "No critical values. Acute stroke suspected."
    assert find_emergency_terms(text) == ["stroke"]


def test_negation_further_back_does_not_cancel():
    # Only words directly before the term count. Fail safe otherwise.
    text = "No change since the earlier report showing sepsis"
    assert find_emergency_terms(text) == ["sepsis"]


# --- normal reports ------------------------------------------------------------

def test_sample_cbc_text_has_no_emergency_terms():
    text = (
        "COMPLETE BLOOD COUNT (SAMPLE - NOT A REAL PATIENT)\n"
        "Test            Result   Units       Reference Range   Flag\n"
        "Hemoglobin      10.2     g/dL        12.0 - 15.5       L\n"
    )
    assert find_emergency_terms(text) == []


def test_empty_text():
    assert find_emergency_terms("") == []


def test_each_term_listed_once_and_has_a_reason():
    labels = [t.label for t in TERMS]
    assert len(labels) == len(set(labels))
    assert all(t.reason for t in TERMS)


def test_reports_each_term_once():
    assert find_emergency_terms("sepsis ... sepsis ... SEPSIS") == ["sepsis"]
