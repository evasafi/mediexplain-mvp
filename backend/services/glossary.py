"""Glossary retrieval (RAG) over MedlinePlus lab-test definitions.

- Data: backend/data/glossary.json, built by scripts/build_glossary.py from
  MedlinePlus lab test pages (public domain; credit "Source: MedlinePlus,
  National Library of Medicine"). Only short "what this test measures"
  definitions are kept, with no causes, conditions or medicines.
- Index: an in-memory ChromaDB collection (EphemeralClient), built once per
  process. Nothing is written to disk and no report text is stored: report
  lines are only used as queries. Chroma telemetry is turned off.
- Embeddings: Chroma's default all-MiniLM-L6-v2 ONNX model (Apache-2.0),
  downloaded once to ~/.cache/chroma on first use.
- Retrieval is optional. If anything fails (no model download, bad data),
  the explanation still runs without glossary context.
"""
import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "glossary.json"
COLLECTION = "medlineplus_lab_glossary"
# Squared L2 distance with the default embedding. Calibrated on sample report
# lines: correct matches scored 0.63-1.39, noise lines (names, dates, headers) 1.43+.
MAX_DISTANCE = 1.40
MAX_ENTRIES = 8
MAX_LINES = 80

_UNITS = {
    "dl", "ml", "ul", "fl", "pg", "ng", "mg", "mcg", "ug", "g", "l", "mmol", "umol", "iu",
    "miu", "uiu", "u", "cumm", "hr", "mm", "sec", "s", "meq", "cells", "lakh", "thou",
}
_NOISE = {
    "test", "tests", "result", "results", "units", "unit", "reference", "range", "ranges",
    "flag", "flags", "patient", "name", "page", "of", "collected", "received", "reported",
    "sample", "specimen", "report", "dr", "doctor", "pathologist", "date", "time", "age",
    "sex", "male", "female", "id", "not", "a", "real", "value", "normal", "high", "low",
}

_lock = threading.Lock()
_state: dict = {}


def _load_entries() -> tuple[list[dict], str]:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return data["entries"], data.get("attribution", "Source: MedlinePlus, National Library of Medicine")


def _collection():
    """Build the in-memory index once. Returns (collection, entries_by_id, attribution)."""
    with _lock:
        if "collection" not in _state:
            import chromadb
            from chromadb.config import Settings

            entries, attribution = _load_entries()
            client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
            col = client.get_or_create_collection(COLLECTION)
            if col.count() == 0:
                col.add(
                    ids=[e["id"] for e in entries],
                    # Embed the name and aliases: report lines name a test, they
                    # don't describe it.
                    documents=[f'{e["title"]}. Also called: {e["other_names"]}' for e in entries],
                )
            _state.update(
                collection=col,
                entries={e["id"]: e for e in entries},
                attribution=attribution,
            )
        return _state["collection"], _state["entries"], _state["attribution"]


def warm() -> None:
    """Build the index ahead of the first request (about 4 s). Never raises."""
    try:
        _collection()
        logger.info("Glossary index ready")
    except Exception as e:
        logger.warning("Glossary warm-up failed (%s)", type(e).__name__)


def query_terms(line: str) -> str:
    """The test-name words of a report line: no numbers, units or table headers."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", line)
    kept = [
        w for w in words
        if w.lower() not in _UNITS and w.lower() not in _NOISE and len(w) > 1
        and not re.fullmatch(r"x\d+", w.lower())  # x10 from x10^3/uL
    ]
    return " ".join(kept)


def retrieve(report_text: str) -> tuple[list[dict], str]:
    """Glossary entries relevant to this report, and the attribution line.

    Returns ([], "") if retrieval is unavailable. Never raises.
    """
    try:
        col, entries, attribution = _collection()
        queries = []
        for line in report_text.splitlines():
            q = query_terms(line)
            if q and q not in queries:
                queries.append(q)
            if len(queries) >= MAX_LINES:
                break
        if not queries:
            return [], ""
        res = col.query(query_texts=queries, n_results=1)
        best: dict[str, float] = {}
        for ids, dists in zip(res["ids"], res["distances"]):
            if ids and dists and dists[0] <= MAX_DISTANCE:
                best[ids[0]] = min(dists[0], best.get(ids[0], 9.0))
        chosen = sorted(best, key=best.get)[:MAX_ENTRIES]
        if not chosen:
            return [], ""  # credit only when definitions are actually used
        return [entries[i] for i in chosen], attribution
    except Exception as e:
        # Type only: the message of a search error can quote report lines.
        logger.warning("Glossary retrieval unavailable (%s); continuing without it",
                       type(e).__name__)
        return [], ""


def format_for_prompt(entries: list[dict]) -> str:
    if not entries:
        return ""
    lines = [f'- {e["title"]}: {e["definition"]}' for e in entries]
    return "\n".join(lines)
