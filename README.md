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
   Models are tried in order with retries on server errors.
4. **Verification** (`backend/services/verifier.py`). Code does not trust the
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
5. The API returns JSON:
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
- Gemini often returns 503 under load. The end-to-end time target has not been measured.

## Licences

Tesseract is licensed under Apache-2.0.
PyMuPDF is licensed under the **AGPL-3.0** (or a commercial licence from Artifex).
Using it in a deployed service can carry AGPL obligations. Check this before any
public deployment.
