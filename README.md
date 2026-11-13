# MediExplain (MVP backend)

Upload a lab report PDF and get a plain-language explanation of each marker
(value, unit, reference range, low/normal/high flag, short explanation),
3 to 5 questions to ask a doctor, and a disclaimer.

**Education only. This is not medical advice and never a diagnosis.**

## Design: stateless by default

- No login, no accounts, no database.
- An upload is written to a temp file with a random name under `uploads/`,
  read, and **always deleted** in a `finally` block before the response is sent.
- Nothing about the report is stored after the request ends.
- The disclaimer and the emergency notice are added by code, not by the model.

## How it works

1. `POST /reports/upload` checks the file: 10 MB max, must start with `%PDF`.
2. PyMuPDF extracts the text layer (`backend/services/parser.py`).
3. The first 30,000 characters go to Gemini with a guardrailed system prompt
   and a structured output schema (`backend/services/explainer.py`).
   Models are tried in order with retries on server errors.
4. The API returns JSON:
   `status`, `disclaimer`, `emergency_notice`, `document_type`, `summary`,
   `markers` (`name`, `value`, `unit`, `reference_range`, `status`, `explanation`),
   `recommendations`.

| Situation | HTTP |
|---|---|
| Not a PDF | 400 |
| Over 10 MB | 413 |
| No readable text (for example a scanned PDF) | 422 |
| Model busy after all retries | 503 |
| Anything else | 500 (generic message; real type and traceback in the server log) |

## Setup (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Create `.env` in the project root with your key. Never commit this file.

```
GEMINI_API_KEY=your-key-here
```

## Run

```powershell
uvicorn backend.main:app --reload
```

In a second terminal:

```powershell
python try_report.py sample_cbc.pdf
```

`sample_cbc.pdf` is a made-up report. Expected: Hemoglobin 10.2 g/dL low,
WBC 7.1 normal, Platelets 450 high, MCV 78 fL low.

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

- Text-layer PDFs only. Images and scanned PDFs return 422 until OCR is added.
- Only the first 30,000 characters of a report are sent to the model.
- Gemini often returns 503 under load. The end-to-end time target has not been measured.

## Licences

PyMuPDF is licensed under the **AGPL-3.0** (or a commercial licence from Artifex).
Using it in a deployed service can carry AGPL obligations. Check this before any
public deployment.
