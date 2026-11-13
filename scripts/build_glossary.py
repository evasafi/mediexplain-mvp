"""Build backend/data/glossary.json from MedlinePlus lab-test pages.

Licence (checked 2026-11-13): MedlinePlus lists "Medical test information"
as public domain (a U.S. government work). NLM asks for the credit line
"Source: MedlinePlus, National Library of Medicine". Only copyrighted parts
of MedlinePlus (A.D.A.M. encyclopedia, drug monographs, images) are
restricted, and none of those are used here.
https://medlineplus.gov/about/using/usingcontent/
robots.txt allows /lab-tests/. Requests are made one per second.

What is kept from each page: the title, the first section ("What is a ...
test?"), and its "Other names" line. Sentences about what an abnormal result
means for "you" (for example "it may be a sign that you have a blood
disorder") are dropped, because the explanation must never suggest a
diagnosis. The rest of the page is not used.

Usage (needs internet, run from the project root):
    python scripts/build_glossary.py
"""
import html
import json
import re
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE = "https://medlineplus.gov/lab-tests/"
OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "glossary.json"
HEADERS = {"User-Agent": "MediExplain course project glossary builder"}
ATTRIBUTION = "Source: MedlinePlus, National Library of Medicine"

# Common markers on routine lab reports (CBC, metabolic panels, lipids, liver,
# kidney, thyroid, iron, inflammation, clotting).
SLUGS = [
    "complete-blood-count-cbc", "hemoglobin-test", "hematocrit-test",
    "red-blood-cell-rbc-count", "red-blood-cell-rbc-indices", "mcv-mean-corpuscular-volume",
    "rdw-red-cell-distribution-width", "white-blood-count-wbc", "blood-differential",
    "platelet-tests", "reticulocyte-count", "erythrocyte-sedimentation-rate-esr",
    "c-reactive-protein-crp-test",
    "basic-metabolic-panel-bmp", "comprehensive-metabolic-panel-cmp", "electrolyte-panel",
    "blood-glucose-test", "hemoglobin-a1c-hba1c-test", "sodium-blood-test",
    "potassium-blood-test", "chloride-blood-test", "carbon-dioxide-co2-in-blood",
    "calcium-blood-test", "magnesium-blood-test", "phosphate-in-blood",
    "bun-blood-urea-nitrogen", "creatinine-test",
    "estimated-glomerular-filtration-rate-egfr-and-gfr-tests", "uric-acid-test",
    "microalbumin-creatinine-ratio",
    "liver-function-tests", "alt-blood-test", "ast-test", "alkaline-phosphatase",
    "bilirubin-blood-test", "gamma-glutamyl-transferase-ggt-test", "albumin-blood-test",
    "globulin-test", "total-protein-and-albumin-globulin-a-g-ratio",
    "cholesterol-levels", "triglycerides-test", "lipoprotein-a-blood-test",
    "tsh-thyroid-stimulating-hormone-test", "thyroxine-t4-test",
    "iron-tests", "ferritin-blood-test", "vitamin-b-test", "vitamin-d-test",
    "prothrombin-time-test-and-inr-ptinr", "partial-thromboplastin-time-ptt-test",
    "prostate-specific-antigen-psa-test", "parathyroid-hormone-pth-test",
]

# Sentences that interpret results for the reader are dropped (see docstring).
_DROP = re.compile(
    r"\byou have\b|\byou may have\b|\bsign of\b|\ba sign\b|\bmay mean\b|\bcould mean\b|"
    r"\bdiagnos|\bdiseases?\b|\bdisorders?\b|\bconditions?\b|\btreat|"
    r"\billness|\binfections?\b|\bsick\b|\bmedicines?\b|\bmedications?\b|\bdrugs?\b|"
    r"\bsupplements?\b|\bchemotherapy\b|\bcaus|\bbacteria|\bvirus|\bcancer|\bdiabetes|"
    r"\banemia|\binflammation\b|\bincreases? your\b|\blowers? your\b|"
    r"\b(?:too )?(?:high|low)\b",
    re.IGNORECASE,
)
# Keep definitions short: what the test measures, not everything on the page.
MAX_SENTENCES = 4


class FirstSection(HTMLParser):
    """Collects the <h1>, the first <h2>, and the <p> text of the first section."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.heading, self.paras = "", "", []
        self._in = None
        self._buf = []
        self._sections = 0
        self._done = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "section" and self.title:
            # Only sections after the page title: the first one is the
            # site-wide government banner, not the definition.
            self._sections += 1
            if self._sections > 1:
                self._done = True
        elif (tag == "h1" and not self.title) or (tag in ("h2", "p") and self._sections == 1):
            self._in, self._buf = tag, []

    def handle_endtag(self, tag):
        if tag != self._in:
            return
        text = " ".join("".join(self._buf).split())
        if tag == "h1" and not self.title:
            self.title = text
        elif tag == "h2" and not self.heading:
            self.heading = text
        elif tag == "p" and text:
            self.paras.append(text)
        self._in = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def parse(page_html: str) -> dict:
    p = FirstSection()
    p.feed(page_html)
    other_names = ""
    body = []
    for para in p.paras:
        if para.lower().startswith("other names:"):
            other_names = para.split(":", 1)[1].strip()
        else:
            body.append(para)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(body))
    # Drop interpreting sentences, and list intros whose bullet list is not kept.
    kept = [s for s in sentences if s and not _DROP.search(s) and not s.endswith(":")]
    kept = kept[:MAX_SENTENCES]
    m = re.search(r'id="lastupdate">\s*Last updated ([^<]+)<', page_html)
    return {
        "title": html.unescape(p.title),
        "other_names": other_names,
        "definition": " ".join(kept),
        "source_updated": m.group(1).strip() if m else "",
    }


def fetch(url: str, tries: int = 4) -> requests.Response | None:
    for attempt in range(tries):
        try:
            return requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as e:
            wait = 2 ** (attempt + 1)
            print(f"     network error ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)
    return None


def main():
    entries = []
    for slug in SLUGS:
        url = BASE + slug + "/"
        r = fetch(url)
        if r is None:
            print(f"skip {slug}: network error")
            continue
        r.encoding = "utf-8"  # the server does not always say; avoid mojibake
        if r.status_code != 200:
            print(f"skip {slug}: HTTP {r.status_code}")
            continue
        entry = parse(r.text)
        if not entry["title"] or not entry["definition"]:
            print(f"skip {slug}: no definition found")
            continue
        entry.update(id=slug, url=url)
        entries.append(entry)
        print(f"ok   {slug}: {entry['title']}")
        time.sleep(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "MedlinePlus lab test information, National Library of Medicine",
        "licence": "Public domain (U.S. government work). See https://medlineplus.gov/about/using/usingcontent/",
        "attribution": ATTRIBUTION,
        "retrieved": date.today().isoformat(),
        "entries": entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} entries to {OUT}")


if __name__ == "__main__":
    main()
