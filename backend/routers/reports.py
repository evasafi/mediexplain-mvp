import logging
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from google.genai import errors as genai_errors

from backend.services.explainer import generate_explanation
from backend.services.parser import (
    OcrUnavailableError,
    UnreadableFileError,
    UnsupportedFileError,
    detect_kind,
    extract_text,
)

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
    try:
        # Decided by the file's signature, never by its name or content type.
        kind = detect_kind(data)
    except UnsupportedFileError:
        raise HTTPException(status_code=400, detail="Only PDF, PNG or JPG files are supported.")

    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}.{kind}")
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(data)

        extracted = extract_text(file_path, kind)
        if not extracted.text.strip():
            raise HTTPException(
                status_code=422,
                detail="No readable text found in this file.",
            )
        result = generate_explanation(extracted.text)
        result["ocr_used"] = extracted.ocr_used
    except HTTPException:
        raise
    except UnreadableFileError as e:
        logger.warning("Unreadable %s upload: %s", kind, e)
        raise HTTPException(status_code=400, detail="This file could not be read. It may be damaged.")
    except OcrUnavailableError:
        logger.exception("OCR needed but not set up on this server")
        raise HTTPException(
            status_code=501,
            detail="Reading images and scanned reports is not set up on this server.",
        )
    except genai_errors.ServerError as e:
        logger.exception("Model unavailable after retries: %s", type(e).__name__)
        raise HTTPException(
            status_code=503,
            detail="The explanation service is busy. Please try again in a minute.",
        )
    except genai_errors.ClientError as e:
        if e.code != 429:
            logger.exception("Model request rejected: %s %s", e.code, e.status)
            raise HTTPException(status_code=500, detail="Could not process this report.")
        logger.exception("Model quota or rate limit reached (429)")
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
