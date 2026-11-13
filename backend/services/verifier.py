"""Code-side checks on the model's markers.

The model's answer is not trusted silently. For each marker we look at the
extracted report text and check:

1. the value really appears in that marker's row,
2. the status the model gave matches the printed reference range,
3. the lab's own H/L flag (if any) agrees with the printed range.

Anything that does not line up marks the marker `verified: False` and adds a
plain-language warning. When the lab's flag and the printed range disagree we
show both and do not pick one.

The model's `status` is never overwritten. `range_status` is what the printed
range says, computed by code.
"""
import re

# One number as printed on a report. Order matters: Western grouping
# (1,234,567) is tried before Indian grouping (1,32,000) so a long Western
# number is not cut short. Plain numbers last.
_NUMBER = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?"       # 4,000  1,234,567
    r"|\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?"  # 1,32,000  12,34,56,789
    r"|\d+(?:\.\d+)?)"                      # 450  10.2
    r"(?![\d,]\d)"
)

# A lab flag token: H, L, HIGH, LOW, HH, LL, arrows, optionally starred.
# The look-behind stops "L" in units such as "g/L" or "10^9/L" from counting.
_FLAG = re.compile(
    r"(?<![\w/^.])\*?(HH|LL|H|L|HIGH|LOW|High|Low|↑|↓)\*?(?![\w/])"
)
_FLAG_MEANING = {
    "H": "high", "HH": "high", "HIGH": "high", "High": "high", "↑": "high",
    "L": "low", "LL": "low", "LOW": "low", "Low": "low", "↓": "low",
}


def parse_number(text: str) -> float | None:
    """Parse one printed number, e.g. '1,32,000' -> 132000.0. None if not a plain number."""
    if text is None:
        return None
    m = _NUMBER.fullmatch(text.strip())
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def numbers_in(text: str) -> list[float]:
    return [float(m.group(1).replace(",", "")) for m in _NUMBER.finditer(text)]


def parse_range(text: str) -> tuple[float | None, float | None] | None:
    """Parse a printed reference range.

    '4,000 - 11,000' -> (4000, 11000); '< 200' / 'up to 200' -> (None, 200);
    '> 40' -> (40, None). None if it cannot be read.
    """
    if not text:
        return None
    nums = numbers_in(text)
    lowered = text.lower()
    if len(nums) == 2:
        lo, hi = nums
        return (lo, hi) if lo <= hi else None
    if len(nums) == 1:
        if re.search(r"<|≤|up to|upto|below|less than", lowered):
            return (None, nums[0])
        if re.search(r">|≥|above|more than|greater than", lowered):
            return (nums[0], None)
    return None


def status_from_range(value: float, rng: tuple[float | None, float | None]) -> str:
    lo, hi = rng
    if lo is not None and value < lo:
        return "low"
    if hi is not None and value > hi:
        return "high"
    return "normal"


def _name_variants(name: str) -> list[str]:
    """'White Blood Cells (WBC)' -> ['White Blood Cells (WBC)', 'White Blood Cells', 'WBC']."""
    variants = [name.strip()]
    base = re.sub(r"\s*\(.*?\)\s*", " ", name).strip()
    if base and base not in variants:
        variants.append(base)
    variants += [p.strip() for p in re.findall(r"\((.*?)\)", name) if p.strip()]
    return variants


def _find_name(name: str, text: str) -> int | None:
    """Start of the marker's row. Prefers an occurrence followed soon by a number,
    so a title or note that repeats the name is not taken as the row."""
    fallback = None
    for v in _name_variants(name):
        pattern = r"(?<!\w)" + re.escape(v) + r"(?!\w)"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if re.search(r"\d", text[m.end():m.end() + 80]):
                return m.start()
            if fallback is None:
                fallback = m.start()
    return fallback


def _row_windows(markers: list[dict], text: str, max_len: int = 300) -> list[str | None]:
    """Text belonging to each marker's row: from its name to the next marker's name."""
    starts = [_find_name(m.get("name", ""), text) for m in markers]
    found = sorted(s for s in starts if s is not None)
    windows = []
    for s in starts:
        if s is None:
            windows.append(None)
            continue
        later = [f for f in found if f > s]
        end = min(later[0] if later else len(text), s + max_len)
        # Stop at a blank line: that is the end of the table block.
        blank = text.find("\n\n", s, end)
        windows.append(text[s:blank if blank != -1 else end])
    return windows


def _lab_flag(row: str, skip: list[str]) -> str | None:
    """The lab's own H/L flag in this row, ignoring text from the name/unit/range fields."""
    cleaned = row
    for s in skip:
        if s:
            cleaned = cleaned.replace(s, " ")
    flags = {_FLAG_MEANING[m.group(1)] for m in _FLAG.finditer(cleaned)}
    return flags.pop() if len(flags) == 1 else None


def _fmt(n: float) -> str:
    return f"{n:g}" if n < 1e6 else f"{n:,.0f}"


def verify_marker(marker: dict, row: str | None, full_text: str) -> tuple[dict, list[str]]:
    name = marker.get("name") or "This marker"
    value_str = marker.get("value", "")
    range_str = marker.get("reference_range", "")
    model_status = marker.get("status", "unknown")
    notes: list[str] = []
    warnings: list[str] = []
    ok = True

    scope = row if row is not None else full_text
    if row is None:
        notes.append("Could not find this marker's row in the report text.")
        ok = False

    # 1. The value must appear in the report.
    value = parse_number(value_str)
    if value_str.strip().lower() in ("", "unknown"):
        notes.append("No value was read for this marker.")
        ok = False
    elif value is not None:
        if not any(abs(n - value) < 1e-9 for n in numbers_in(scope)):
            notes.append(f"The value {value_str} was not found in the report text.")
            warnings.append(
                f"{name}: the value {value_str} could not be found in your report. "
                "Check it against the original report."
            )
            ok = False
    elif value_str.lower() not in scope.lower():
        notes.append(f"The value '{value_str}' was not found in the report text.")
        warnings.append(
            f"{name}: the result '{value_str}' could not be found in your report. "
            "Check it against the original report."
        )
        ok = False

    # 2. Status against the printed range (only if that range is really printed).
    rng = parse_range(range_str)
    range_status = "unknown"
    if rng is not None:
        range_nums = [x for x in rng if x is not None]
        if all(any(abs(n - r) < 1e-9 for n in numbers_in(scope)) for r in range_nums):
            if value is not None:
                range_status = status_from_range(value, rng)
        else:
            notes.append(f"The range '{range_str}' was not found in the report text.")
            ok = False

    if range_status != "unknown" and model_status == "unknown":
        # The model abstained (for example because the lab flag disagrees).
        # Not a wrong claim, so a note, not a warning.
        notes.append(f"No status was given; the printed range means '{range_status}'.")
    elif range_status != "unknown" and model_status != range_status:
        notes.append(
            f"Status given as '{model_status}', but the printed range means '{range_status}'."
        )
        warnings.append(
            f"{name}: the explanation called this '{model_status}', but {value_str} "
            f"against the printed range {range_str} is '{range_status}'. "
            "Check it against the original report."
        )
        ok = False

    # 3. The lab's own flag against the printed range.
    lab_flag = None
    if row is not None:
        lab_flag = _lab_flag(row, [name, *_name_variants(name), marker.get("unit", "")])
    if lab_flag and range_status != "unknown" and lab_flag != range_status:
        notes.append(
            f"The lab flagged this as '{lab_flag}', but the value is "
            f"'{range_status}' for the printed range."
        )
        where = "within" if range_status == "normal" else f"{range_status} for"
        warnings.append(
            f"{name}: the lab marked this result as {lab_flag.upper()}, but {value_str} "
            f"is {where} the printed range {range_str}. These two do not agree. "
            "Ask your doctor or the lab which one is correct."
        )
        ok = False
    elif lab_flag and range_status == "unknown" and model_status not in ("unknown", lab_flag):
        notes.append(f"The lab flagged this as '{lab_flag}', but the status given is '{model_status}'.")
        ok = False

    out = dict(marker)
    out.update(
        verified=ok,
        range_status=range_status,
        lab_flag=lab_flag,
        verification_notes=notes,
    )
    return out, warnings


def verify_markers(markers: list[dict], full_text: str) -> tuple[list[dict], list[str]]:
    rows = _row_windows(markers, full_text)
    checked, warnings = [], []
    for marker, row in zip(markers, rows):
        out, w = verify_marker(marker, row, full_text)
        checked.append(out)
        warnings += w
    return checked, warnings
