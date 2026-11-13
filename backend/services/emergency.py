"""Detect report wording that can signal an urgent problem.

The emergency notice is added by code, never by the model. This module decides
when. It replaces a plain substring check that matched inside longer words.

Matching rules
- Case-insensitive, whole words only: a term never matches inside a longer
  word or a hyphenated compound ("non-critical value" does not match).
- Any whitespace, including a PDF line break, may sit between the words of a term.
- Common plural and verb forms are listed explicitly in each pattern.
- A term directly negated ("no critical values", "negative for sepsis") or
  given as past history ("history of stroke") does not trigger the notice.
  Negation is only checked right before the term, on purpose: anything less
  certain still triggers. A false notice is better than a missed one.

Review record
Each term has a reason. To change the list, edit TERMS here, add a test in
tests/test_emergency.py, and have a teammate review it. The list was reviewed
for wording that labs and reports use to flag urgency. It is not a clinical
triage tool, and education-only rules still apply.
"""
import re
from typing import NamedTuple


class Term(NamedTuple):
    label: str
    pattern: str
    reason: str


# Words between parts of a term: any whitespace, including line breaks.
_S = r"\s+"

TERMS: tuple[Term, ...] = (
    # --- Lab alerts: the lab itself says the result is dangerous. ---------
    Term("critical value", rf"critical{_S}(?:values?|results?|alerts?|levels?|ranges?)",
         "Standard lab wording for a result that must be phoned to a clinician."),
    Term("critically high/low", rf"critical(?:ly)?{_S}(?:high|low|abnormal|elevated)",
         "Lab wording for a result far outside the safe range."),
    Term("panic value", rf"panic{_S}(?:values?|results?|levels?|ranges?)",
         "Older lab wording for a critical value."),
    Term("life-threatening", rf"life(?:-|{_S})threatening",
         "Explicit statement of danger."),
    Term("notify clinician immediately",
         rf"(?:call|calls|called|notify|notified|contact|contacted|inform|informed)"
         rf"{_S}(?:the{_S})?(?:physician|doctor|clinician|provider|ward){_S}immediately",
         "Instruction on the report to act at once."),
    Term("immediate medical attention", rf"immediate{_S}medical{_S}attention",
         "Explicit instruction to seek care now."),
    Term("medical emergency", rf"medical{_S}emergency|seek{_S}emergency",
         "Explicit statement of an emergency."),
    # --- Acute conditions named on the report (kept from the original list). ---
    Term("cardiac arrest", rf"cardiac{_S}arrest", "Acute, life-threatening event."),
    Term("respiratory failure", rf"respiratory{_S}failure", "Acute, life-threatening event."),
    Term("organ failure", rf"(?:multi-?)?organ{_S}failure|multiple{_S}organ{_S}failure",
         "Acute, life-threatening event."),
    Term("sepsis", r"sepsis|septic(?:\s+shock)?", "Acute, life-threatening infection response."),
    Term("stroke", r"stroke|strokes", "Acute event where minutes matter."),
)

# Phrases that contain a term but are not urgent. Matched before the terms.
EXCLUSIONS: tuple[str, ...] = (
    rf"stroke{_S}(?:volume|index|work)",  # heart-function measurements on echo reports
)

# Directly before a term, these cancel it. Kept narrow on purpose.
_NEGATION = re.compile(
    rf"(?:\bno|\bnot|\bwithout|\bnegative{_S}for|\bno{_S}evidence{_S}of|"
    rf"\bno{_S}signs?{_S}of|\bhistory{_S}of|\bh/o|\bprevious|\bprior|\bold)"
    rf"{_S}$",
    re.IGNORECASE,
)

_BOUNDARY_BEFORE = r"(?<![\w-])"
_BOUNDARY_AFTER = r"(?![\w-])"

_COMPILED = [
    (t, re.compile(_BOUNDARY_BEFORE + "(?:" + t.pattern + ")" + _BOUNDARY_AFTER, re.IGNORECASE))
    for t in TERMS
]
_EXCLUDE = re.compile(
    _BOUNDARY_BEFORE + "(?:" + "|".join(EXCLUSIONS) + ")" + _BOUNDARY_AFTER, re.IGNORECASE
)


def _negated(text: str, start: int) -> bool:
    # Look back a short way on the same line only.
    line_start = text.rfind("\n", 0, start) + 1
    before = text[max(line_start, start - 40):start]
    return bool(_NEGATION.search(before))


def find_emergency_terms(text: str) -> list[str]:
    """Labels of the urgent terms found in `text`, in list order, each once."""
    if not text:
        return []
    excluded = [m.span() for m in _EXCLUDE.finditer(text)]
    found = []
    for term, rx in _COMPILED:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in excluded):
                continue
            if _negated(text, m.start()):
                continue
            found.append(term.label)
            break
    return found
