"""Verification step: code checks the model's markers against the report text."""
import pytest

from backend.services.verifier import (
    parse_number, parse_range, verify_markers,
)
from make_samples import SAMPLES

CBC = (
    "COMPLETE BLOOD COUNT (SAMPLE - NOT A REAL PATIENT)\n"
    "Test            Result   Units       Reference Range   Flag\n"
    "Hemoglobin      10.2     g/dL        12.0 - 15.5       L\n"
    "WBC             7.1      x10^3/uL    4.0 - 11.0\n"
    "Platelets       450      x10^3/uL    150 - 400         H\n"
    "MCV             78       fL          80 - 100          L\n\n"
)
CONFLICT = "\n".join(SAMPLES["sample_conflict_flag.pdf"]) + "\n\n"
INDIAN = "\n".join(SAMPLES["sample_indian_grouping.pdf"]) + "\n\n"


def mk(name, value, unit, rng, status):
    return {"name": name, "value": value, "unit": unit, "reference_range": rng,
            "status": status, "explanation": "e"}


# --- number and range parsing -------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1,32,000", 132000), ("12,34,567", 1234567), ("4,200", 4200),
    ("1,234,567", 1234567), ("132,000", 132000), ("10.2", 10.2), ("450", 450),
    ("1,50,000.5", 150000.5),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["Positive", "<0.5", "1,2,3", "", "unknown", "12,34"])
def test_parse_number_rejects_non_numbers(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("text,expected", [
    ("4,000 - 11,000", (4000, 11000)),
    ("1,50,000 - 4,50,000", (150000, 450000)),
    ("12.0-15.5", (12.0, 15.5)),
    ("13.0 – 17.0", (13.0, 17.0)),
    ("< 200", (None, 200)),
    ("Up to 5", (None, 5)),
    ("> 40", (40, None)),
    ("unknown", None),
])
def test_parse_range(text, expected):
    assert parse_range(text) == expected


# --- the sample CBC: everything consistent ----------------------------------

def test_consistent_cbc_is_fully_verified():
    markers = [
        mk("Hemoglobin", "10.2", "g/dL", "12.0 - 15.5", "low"),
        mk("WBC", "7.1", "x10^3/uL", "4.0 - 11.0", "normal"),
        mk("Platelets", "450", "x10^3/uL", "150 - 400", "high"),
        mk("MCV", "78", "fL", "80 - 100", "low"),
    ]
    out, warnings = verify_markers(markers, CBC)
    assert warnings == []
    assert [m["verified"] for m in out] == [True] * 4
    assert [m["range_status"] for m in out] == ["low", "normal", "high", "low"]
    assert [m["lab_flag"] for m in out] == ["low", None, "high", "low"]
    # Original fields are untouched.
    assert out[0]["status"] == "low" and out[0]["value"] == "10.2"


# --- lab flag contradicts printed range --------------------------------------

@pytest.mark.parametrize("model_status", ["normal", "low"])
def test_lab_flag_contradicting_range_is_shown_not_resolved(model_status):
    markers = [mk("WBC Count", "4,200", "/uL", "4,000 - 11,000", model_status)]
    out, warnings = verify_markers(markers, CONFLICT)
    m = out[0]
    assert m["lab_flag"] == "low"
    assert m["range_status"] == "normal"
    assert m["verified"] is False
    assert m["status"] == model_status  # code does not quietly pick a side
    conflict = [w for w in warnings if "do not agree" in w]
    assert len(conflict) == 1
    assert "LOW" in conflict[0] and "4,000 - 11,000" in conflict[0]


def test_conflict_does_not_leak_to_other_rows():
    markers = [
        mk("Hemoglobin", "14.1", "g/dL", "13.0 - 17.0", "normal"),
        mk("WBC Count", "4,200", "/uL", "4,000 - 11,000", "normal"),
        mk("Platelets", "250", "x10^3/uL", "150 - 400", "normal"),
    ]
    out, _ = verify_markers(markers, CONFLICT)
    assert [m["verified"] for m in out] == [True, False, True]
    assert [m["lab_flag"] for m in out] == [None, "low", None]


# --- Indian digit grouping ---------------------------------------------------

def test_indian_grouping_value_and_range():
    markers = [
        mk("Hemoglobin", "13.5", "g/dL", "13.0 - 17.0", "normal"),
        mk("Total WBC Count", "8,500", "/cumm", "4,000 - 11,000", "normal"),
        mk("Platelet Count", "1,32,000", "/cumm", "1,50,000 - 4,50,000", "low"),
    ]
    out, warnings = verify_markers(markers, INDIAN)
    assert warnings == []
    assert all(m["verified"] for m in out)
    assert out[2]["range_status"] == "low"
    assert out[2]["lab_flag"] == "low"


def test_indian_grouping_model_reformatted_value_still_matches():
    # Model wrote 132000 instead of 1,32,000: same number, still found.
    markers = [mk("Platelet Count", "132000", "/cumm", "150000 - 450000", "low")]
    out, _ = verify_markers(markers, INDIAN)
    assert out[0]["verified"] is True


def test_indian_grouping_model_says_normal_is_flagged():
    markers = [mk("Platelet Count", "1,32,000", "/cumm", "1,50,000 - 4,50,000", "normal")]
    out, warnings = verify_markers(markers, INDIAN)
    assert out[0]["verified"] is False
    assert out[0]["range_status"] == "low"
    assert any("'normal'" in w and "'low'" in w for w in warnings)


def test_misread_grouping_is_caught():
    # 1,32,000 misread as 1,320,000 / 13,200 must not verify.
    for wrong in ("1,320,000", "13,200"):
        out, warnings = verify_markers(
            [mk("Platelet Count", wrong, "/cumm", "1,50,000 - 4,50,000", "low")], INDIAN
        )
        assert out[0]["verified"] is False
        assert any("could not be found" in w for w in warnings)


# --- model mistakes ---------------------------------------------------------

def test_invented_value_is_unverified():
    out, warnings = verify_markers(
        [mk("Hemoglobin", "11.4", "g/dL", "12.0 - 15.5", "low")], CBC
    )
    assert out[0]["verified"] is False
    assert any("11.4" in w for w in warnings)


def test_value_from_another_row_is_not_accepted():
    # 7.1 is WBC's value; it must not verify as Hemoglobin.
    markers = [
        mk("Hemoglobin", "7.1", "g/dL", "12.0 - 15.5", "low"),
        mk("WBC", "7.1", "x10^3/uL", "4.0 - 11.0", "normal"),
    ]
    out, _ = verify_markers(markers, CBC)
    assert [m["verified"] for m in out] == [False, True]


def test_wrong_status_is_flagged():
    out, warnings = verify_markers(
        [mk("Platelets", "450", "x10^3/uL", "150 - 400", "normal")], CBC
    )
    assert out[0]["verified"] is False
    assert out[0]["range_status"] == "high"
    assert len(warnings) == 1


def test_invented_range_is_unverified():
    out, _ = verify_markers([mk("WBC", "7.1", "x10^3/uL", "3.5 - 10.5", "normal")], CBC)
    assert out[0]["verified"] is False
    assert out[0]["range_status"] == "unknown"


def test_marker_not_in_report():
    out, warnings = verify_markers([mk("Ferritin", "30", "ng/mL", "unknown", "unknown")], CBC)
    assert out[0]["verified"] is False
    assert any("row" in n for n in out[0]["verification_notes"])


def test_unknown_value_is_unverified_without_crashing():
    out, _ = verify_markers([mk("WBC", "unknown", "unknown", "unknown", "unknown")], CBC)
    assert out[0]["verified"] is False


# --- cell-per-line layout and unit letters -----------------------------------

def test_cells_on_separate_lines():
    text = ("Test\nResult\nRange\nFlag\n"
            "WBC Count\n4,200\n/uL\n4,000 - 11,000\nL\n"
            "Platelets\n250\nx10^3/uL\n150 - 400\n\n")
    markers = [
        mk("WBC Count", "4,200", "/uL", "4,000 - 11,000", "normal"),
        mk("Platelets", "250", "x10^3/uL", "150 - 400", "normal"),
    ]
    out, _ = verify_markers(markers, text)
    assert out[0]["lab_flag"] == "low" and out[0]["verified"] is False
    assert out[1]["lab_flag"] is None and out[1]["verified"] is True


def test_unit_letter_l_is_not_a_flag():
    text = "Hemoglobin   140   g/L   130 - 170\nWBC   7.1   x10^9/L   4.0 - 11.0\n\n"
    out, warnings = verify_markers([
        mk("Hemoglobin", "140", "g/L", "130 - 170", "normal"),
        mk("WBC", "7.1", "x10^9/L", "4.0 - 11.0", "normal"),
    ], text)
    assert warnings == []
    assert [m["lab_flag"] for m in out] == [None, None]


def test_model_abstaining_on_conflict_gives_one_warning_not_two():
    markers = [mk("WBC Count", "4,200", "/uL", "4,000 - 11,000", "unknown")]
    out, warnings = verify_markers(markers, CONFLICT)
    assert out[0]["verified"] is False
    assert len(warnings) == 1 and "do not agree" in warnings[0]
    assert any("No status was given" in n for n in out[0]["verification_notes"])
