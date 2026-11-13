import logging
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from google.genai import errors as genai_errors

from backend.services.explainer import generate_explanation
from backend.services.parser import parse_pdf_text

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = "uploads"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload", summary="Upload, Parse, and Explain Medical Report")
def upload_and_parse_report(file: UploadFile = File(...)):
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (10 MB max).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}.pdf")
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(data)

        full_text = parse_pdf_text(file_path)
        if not full_text or not full_text.strip():
            raise HTTPException(
                status_code=422,
                detail="No readable text found. Scanned PDFs are not supported yet.",
            )
        result = generate_explanation(full_text)
    except HTTPException:
        raise
    except genai_errors.ServerError as e:
        logger.exception("Model unavailable after retries: %s", type(e).__name__)
        raise HTTPException(
            status_code=503,
            detail="The explanation service is busy. Please try again in a minute.",
        )
    except Exception as e:
        # Real type + traceback go to the server log; the client gets a generic message.
        logger.exception(
            "Report processing failed with %s.%s",
            type(e).__module__, type(e).__name__,
        )
        raise HTTPException(status_code=500, detail="Could not process this report.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    return {"status": "success", **result}
