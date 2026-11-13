"""Make the summary and doctor questions honest about lab-flag conflicts.

A conflict is a marker whose lab flag (H/L) disagrees with what its printed
reference range says (found by verifier.py). When there is one:

1. The summary must not claim that all values are within range. Sentences
   making that claim are removed, and a code-written sentence says how many
   values need checking.
2. A doctor question naming each conflicting marker goes first. The list
   stays at 3 to 5 questions.

This runs in code after the model answers, so it holds whichever model
replied and whatever it wrote.
"""
import re

MIN_QUESTIONS = 3
MAX_QUESTIONS = 5

# A sentence claiming everything is fine: "All values are within range",
# "Everything looks normal", "None of the results are outside the range".
_ALL_FINE = re.compile(
    r"\b(?:all|every|everything|each)\b[^.!?]*\b(?:within|inside|normal|in range|"
    r"in the (?:normal|reference|standard|expected) range|look(?:s)? (?:fine|good|healthy))\b"
    r"|\b(?:no|none|nothing)\b[^.!?]*\b(?:outside|out of range|abnormal|flagged|high or low|"
    r"low or high|of concern|concerning)\b",
    re.IGNORECASE,
)

# Fallback questions if removing duplicates would leave fewer than 3.
_GENERAL = [
    "What is the next step to better understand these results?",
    "Should any of these results be checked again, and when?",
    "Is there anything in these results you would like to discuss with me?",
]


def find_conflicts(markers: list[dict]) -> list[dict]:
    """Markers whose lab flag disagrees with their printed range."""
    return [
        m for m in markers
        if m.get("lab_flag") in ("low", "high")
        and m.get("range_status") in ("low", "normal", "high")
        and m["lab_flag"] != m["range_status"]
    ]


def _where(range_status: str) -> str:
    return {
        "normal": "inside the printed range",
        "low": "below the printed range",
        "high": "above the printed range",
    }[range_status]


def conflict_question(marker: dict) -> str:
    name = marker.get("name") or "result"
    flag = marker["lab_flag"].upper()
    return (
        f"The lab marked my {name} as {flag}, but my value is "
        f"{_where(marker['range_status'])}. Which is correct?"
    )


def fix_summary(summary: str, conflicts: list[dict]) -> str:
    if not conflicts:
        return summary
    sentences = re.split(r"(?<=[.!?])\s+", (summary or "").strip())
    kept = [s for s in sentences if s and not _ALL_FINE.search(s)]
    names = ", ".join(m.get("name") or "one result" for m in conflicts)
    if len(conflicts) == 1:
        note = (f"One value needs checking: the lab's flag for {names} does not match "
                "the printed reference range.")
    else:
        note = (f"{len(conflicts)} values need checking: the lab's flags for {names} do not "
                "match the printed reference ranges.")
    return " ".join(kept + [note])


def _mentions_conflict(question: str, conflicts: list[dict]) -> bool:
    """A model question about the same flag conflict (would duplicate ours)."""
    q = question.lower()
    return any(
        (m.get("name") or "").lower() in q and re.search(r"\b(flag|flagged|marked)\b", q)
        for m in conflicts
    )


def fix_questions(questions: list[str], conflicts: list[dict]) -> list[str]:
    questions = [q for q in (questions or []) if q and q.strip()]
    if not conflicts:
        return questions
    ours = [conflict_question(m) for m in conflicts][:MAX_QUESTIONS]
    rest = [q for q in questions if not _mentions_conflict(q, conflicts)]
    merged = ours + rest
    for g in _GENERAL:
        if len(merged) >= MIN_QUESTIONS:
            break
        if g not in merged:
            merged.append(g)
    return merged[:MAX_QUESTIONS]
