# MediExplain (MVP)

Upload a lab report (PDF, PNG or JPG) and get a plain-language explanation of each marker
(value, unit, reference range, low/normal/high flag, short explanation),
3 to 5 questions to ask a doctor, and a disclaimer.

**Education only. This is not medical advice and never a diagnosis.**

## Design: stateless by default

- No login, no accounts, no database.
- An upload is written to a temp file with a random name under `uploads/`,
  read, and **always deleted** in a `finally` block before the response is sent.
- Nothing about the report is stored after the request ends.
- The disclaimer and the emergency notice are added by code, not by the model.
- The emergency notice is triggered by a reviewed list of urgent wording
  (`backend/services/emergency.py`): whole words only, with narrow handling of
  negation such as "No critical values". Each term has a written reason.

## How it works

1. `POST /reports/upload` checks the file: 10 MB max, and the type is decided by
   its signature (magic bytes): PDF, PNG or JPG. The file name and the browser's
   content type are ignored.
2. Text extraction (`backend/services/parser.py`):
   - PDF pages with a text layer are read directly with PyMuPDF.
   - Images and PDF pages without a text layer (scans) are read with OCR:
     PyMuPDF's built-in Tesseract engine with Tesseract's English data, at 300 DPI,
     up to 10 pages. Images over 40 megapixels are refused before decoding.
   - The response says `ocr_used: true` when any text came from OCR, and the
     web page then asks the user to compare numbers with the original.
3. The first 30,000 characters go to Gemini with a guardrailed system prompt
   and a structured output schema (`backend/services/explainer.py`).
   Models are tried fastest first: `gemini-3.5-flash-lite` (about 2 s on the sample),
   then `gemini-3.8-flash` and `gemini-3.5-flash`. Each call has its own deadline
   (20 s for Lite, 40 s for Flash) and the whole chain has a 90 s budget. A busy model
   (503) gets one quick retry; a timed-out (504), rate-limited (429) or missing (404)
   model is skipped. Code verification and the prompt rules apply to every model.
4. **Glossary retrieval (RAG)** (`backend/services/glossary.py`). Each report line
   is reduced to its test-name words and looked up in an in-memory ChromaDB index of
   52 MedlinePlus lab-test definitions (`backend/data/glossary.json`). Up to 8 close
   matches go to the model in a `<glossary>` block before the report, with a prompt
   rule to use them only to explain what a test measures. Definitions are trimmed to
   "what the test measures": sentences about causes, conditions or medicines are
   removed when the data is built. The response adds `glossary_sources` and
   `glossary_attribution`, and the web page shows the credit. Nothing is stored:
   the index lives in memory and report lines are only used as queries. If retrieval
   fails, the explanation runs without it. Rebuild the data with
   `python scripts/build_glossary.py`.
5. **Verification** (`backend/services/verifier.py`). Code does not trust the
   model silently. For each marker it finds the marker's row in the report text and checks:
   - the value really appears in that row (numbers compared by value, so
     Indian grouping like `1,32,000` and `132000` match);
   - the model's status matches the printed reference range;
   - the lab's own flag (H / L / HIGH / LOW / arrows) agrees with the printed range.
     If they disagree (for example 4,200 flagged LOW with range 4,000 - 11,000),
     both are shown in a warning. Code never quietly picks one.

   Anything that does not line up sets `verified: false` and adds a warning.
   The model's `status` is never overwritten. `range_status` is what code computed
   from the printed range.
6. The API returns JSON:
   `status`, `disclaimer`, `emergency_notice`, `document_type`, `summary`,
   `markers` (`name`, `value`, `unit`, `reference_range`, `status`, `explanation`,
   plus added `verified`, `range_status`, `lab_flag`, `verification_notes`),
   `recommendations`, and added `warnings` (plain-language list).

| Situation | HTTP |
|---|---|
| Not a PDF, PNG or JPG by signature, or a damaged file | 400 |
| Over 10 MB | 413 |
| No readable text, even after OCR | 422 |
| OCR needed but Tesseract is not installed on the server | 501 |
| Model busy, timed out, or rate-limited (429) on every model | 503 |
| Anything else | 500 (generic message; real type and traceback in the server log) |

## Setup (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

### OCR (for photos and scanned reports)

Install Tesseract for Windows (free, open source). The UB Mannheim build is the
usual choice: https://github.com/UB-Mannheim/tesseract/wiki . Keep the default
folder `C:\Program Files\Tesseract-OCR`, and English is included. The backend
finds it there, or on PATH, or through `TESSDATA_PREFIX`. Check with:

```powershell
curl.exe http://127.0.0.1:8000/health
```

`"ocr_available": true` means it was found. Without Tesseract, text PDFs still
work and images return 501.

### API key

Create `.env` in the project root with your key. Never commit this file.

```
GEMINI_API_KEY=your-key-here
```

## Run

```powershell
uvicorn backend.main:app --reload
```

Start the web page in a second terminal:

```powershell
streamlit run frontend/app.py
```

It opens at http://localhost:8501. The page calls the backend over HTTP.
To use a backend somewhere else, set its URL first:

```powershell
$env:MEDIEXPLAIN_API_URL = "http://127.0.0.1:8000"
```

To test the backend alone from a terminal instead:

```powershell
python try_report.py sample_cbc.pdf
```

`sample_cbc.pdf` is a made-up report. Expected: Hemoglobin 10.2 g/dL low,
WBC 7.1 normal, Platelets 450 high, MCV 78 fL low.

Two more made-up reports test verification (regenerate with `python make_samples.py`):

- `sample_conflict_flag.pdf`: WBC 4,200 flagged L with range 4,000 - 11,000.
  Expected: WBC unverified, with a warning that the flag and range disagree.
- `sample_indian_grouping.pdf`: Platelets 1,32,000 with range 1,50,000 - 4,50,000.
  Expected: low, verified.

## Deployment (public demo)

The demo is for made-up or template reports only. The page shows a banner
saying so, and the protections below limit who can use it and how much.

### Environment variables

| Variable | Used by | Required | What it does |
|---|---|---|---|
| `GEMINI_API_KEY` | backend | Yes | Gemini API key. Keep it in `.env` or the host's secret settings; never commit it. |
| `ACCESS_CODE` | backend | For a public demo | If set, `POST /reports/upload` needs a matching `X-Access-Code` header (compared in constant time), otherwise 401. If unset, no code is needed (local development). `/health` is always open. |
| `MAX_REQUESTS_PER_DAY` | backend | No (default 100) | Uploads allowed per UTC day, all users together. Over it: 429. |
| `MAX_REQUESTS_PER_IP_PER_HOUR` | backend | No (default 10) | Uploads allowed per client IP in a rolling hour. Over it: 429. |
| `TRUST_FORWARDED_FOR` | backend | No (default off) | `true` makes the per-IP cap use the first `X-Forwarded-For` address. Turn it on only when clients can reach the backend solely through the Streamlit page or a proxy, because the header is easy to fake. Without it, every request through the page counts as the page server's IP. |
| `TESSDATA_PREFIX` | backend | No | Folder with Tesseract's language data, if Tesseract is not in its default folder or on PATH. |
| `MEDIEXPLAIN_API_URL` | front end | No (default `http://127.0.0.1:8000`) | Where the Streamlit page sends uploads. |

**OCR needs Tesseract installed on the backend host** (with English language
data). Without it, text PDFs still work and images or scanned PDFs return 501.
`GET /health` shows `ocr_available` and `access_code_required`.

The glossary's embedding model (about 80 MB) downloads on the backend's first
start, so the host needs internet access then.

### How the protections behave

- **Access code:** the Streamlit page asks for it in a password-style field
  (shown only when the backend requires one), keeps it in the browser session
  only, and sends it as `X-Access-Code`. A wrong code is rejected before the
  file is read and does not count against the caps.
- **Request caps are in memory.** A restart resets them, and each worker
  process keeps its own counters, so run the backend as **one** worker
  (`uvicorn backend.main:app`, no `--workers`) for the caps to hold.
- **Logs** never contain report text, the access code or API keys. Errors are
  logged as their type and stack frames without the exception message, and the
  key and code values are masked in every log line.

## Tests

```powershell
pytest
```

The tests mock the model and never call Gemini.

## Data and privacy notes

- Test only with fake or template reports. Never upload real patient data.
- Free-tier Gemini terms can allow the provider to use submitted content.
  That conflicts with the privacy goal, so use fake data only.

## Known limitations

- OCR is English only, and handwritten reports are not supported.
- OCR can misread numbers. Task 2's verification then checks the model against
  the OCR text, not against the original image.
- Only the first 30,000 characters of a report are sent to the model.
- Gemini often returns 503 under load. With Lite first, the sample takes a few seconds;
  if Lite is down, the full Flash models can take 30-60 s (90 s at most).

## Licences

Tesseract is licensed under Apache-2.0.

Glossary text: MedlinePlus lab test information is public domain (U.S. government
work). Source: MedlinePlus, National Library of Medicine.
https://medlineplus.gov/about/using/usingcontent/ (checked 2026-11-13).
ChromaDB and its default embedding model (all-MiniLM-L6-v2) are Apache-2.0. The model
(about 80 MB) downloads to `~/.cache/chroma` on first use, so the first run needs
internet access.
PyMuPDF is licensed under the **AGPL-3.0** (or a commercial licence from Artifex).
Using it in a deployed service can carry AGPL obligations. Check this before any
public deployment.
