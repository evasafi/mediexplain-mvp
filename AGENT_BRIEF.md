# MediExplain: brief for the coding agent

Read this whole file before changing anything. Work through the tasks in order.

## Goal

A web app where a user uploads a medical lab report (PDF, PNG or JPG, 10 MB max) and gets a plain-language explanation: each marker with value, unit, reference range, a low/normal/high flag and a short explanation, plus 3 to 5 questions to ask their doctor, plus a disclaimer.

- No login, no accounts, no stored data.
- Education only. Never a diagnosis.
- Course project for an agentic AI class, group of 7. The team's SRS asks for a Streamlit UI, a FastAPI backend, OCR, and a ChromaDB glossary for retrieval (RAG).

## What exists and works today

- `backend/main.py`: FastAPI app with `GET /health` and the router mounted at `/reports`.
- `backend/routers/reports.py`: `POST /reports/upload`. Checks size and the `%PDF` header, saves a temp file under a random name, always deletes it in `finally`, extracts text, calls the explainer. A Gemini server error becomes HTTP 503. Any other error becomes HTTP 500 with a generic message. Empty text becomes HTTP 422.
- `backend/services/parser.py`: PyMuPDF text extraction. It also builds a crude colon-split `metrics` dict that the explainer ignores (legacy, remove it when convenient).
- `backend/services/explainer.py`: calls Gemini through `google-genai` with structured output (pydantic `ReportExplanation` and `Marker`). Has a guardrailed system prompt, a model fallback list (`gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-2.5-flash`) with 2 retries per model on server errors, and adds the disclaimer and emergency notice in code.
- Response shape: `status`, `disclaimer`, `emergency_notice`, `document_type`, `summary`, `markers` (each: `name`, `value`, `unit`, `reference_range`, `status`, `explanation`), `recommendations`.
- `try_report.py`: test script. Usage: `python try_report.py <pdf> [forbidden words]`. The server must be running: `uvicorn backend.main:app --reload`.
- `sample_cbc.pdf`: a made-up CBC. Expected result: Hemoglobin 10.2 g/dL low, WBC 7.1 normal, Platelets 450 high, MCV 78 fL low.
- Environment: Windows, PowerShell, Python 3.14, virtual environment in `./venv`, Gemini key in `.env` as `GEMINI_API_KEY`.

## Rules that must not break

- No database, no accounts, no storage of uploads beyond the request. Temp files are always deleted.
- Never print, log or commit `.env` or the API key. Check `git status` before every commit.
- Test only with fake or template reports. Never use real patient data.
- The model must never diagnose, name a condition the patient has, advise on medication, or point to one specific cause, vitamin, drug or test. Keep the prompt rules and extend them, do not weaken them.
- The disclaimer and the emergency notice stay added by code, not by the model.
- No invented values. Use "unknown" when something is missing.
- Pin every dependency version in `requirements.txt` (it is currently unpinned).
- When giving the human commands, use PowerShell only, and keep each command block short (long blocks get cut off in their terminal).

## Tasks, in order

Do one at a time, run its done-check, commit, then report before moving on.

1. **Harden the backend.** Log the real exception type and traceback server-side for every 500. Pin dependency versions. Rewrite the README for the stateless design (it must not mention PostgreSQL). Add pytest tests for upload validation, and for the explainer with the model mocked.
   Done when: `pytest` passes, and `python try_report.py sample_cbc.pdf` returns HTTP 200 with the four markers above.
2. **Verification step (the agentic part).** After the model answers, code checks that each marker's value appears in the extracted text and that its status matches the printed range. If something does not match, mark that marker as unverified and add a warning instead of trusting the model silently. Handle a lab's own flag contradicting its range (for example a count of 4,200 with range 4,000 to 11,000 flagged LOW) by showing the conflict, not by quietly picking one. Handle Indian digit grouping such as `1,32,000`.
   Done when: a made-up report with a contradictory flag and one with `1,32,000` both produce correct, flagged output.
3. **Fix the emergency check.** The current substring match is crude (for example "stroke" matches inside longer words). Use word-boundary matching and a reviewed term list.
4. **Streamlit front end** in `frontend/app.py`. Upload, spinner, results table with low and high highlighted, explanations, doctor questions with copy or download, the disclaimer at the top and bottom, friendly messages for HTTP 422 (no readable text) and HTTP 503 (busy). It calls the backend over HTTP, and the backend URL comes from an environment variable.
5. **OCR** for PNG, JPG and scanned PDFs, using Tesseract or a vision-capable model. Validate by file signature, not by extension.
6. **Glossary retrieval (RAG), optional.** ChromaDB with an open medical glossary whose licence you have checked. Pass retrieved definitions into the prompt. Ask the human before starting this one.

## Known issues

- An unexplained HTTP 500 happened once on upload and was not reproduced after a restart. Task 1's logging should reveal the cause if it returns.
- Only the first 30,000 characters of a report are sent to the model.
- PyMuPDF is AGPL-licensed. Note this in the README.
- Gemini models often return 503 under load. The fallback chain helps, but the SRS target of 10 seconds end to end has not been measured.
- Free-tier Gemini terms can allow the provider to use submitted content, which conflicts with the privacy requirement. Fake data only.
- A realistic sample (an image of a lab table, 15 test rows) was rejected with HTTP 422 because it is an image. Task 5 fixes that. Do not commit that file.

## How to work

- Small commits, one task at a time.
- Ask the human before: changing the existing response fields (teammates build against them; adding fields is fine), adding paid services, deleting files, or starting task 6.
- If blocked by a missing key or a decision, stop and ask. Do not invent.
