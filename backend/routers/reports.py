from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.services.parser import parse_pdf_text
from backend.services.explainer import generate_explanation
import os
import shutil

router = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", summary="Upload, Parse, and Explain Medical Report")
async def upload_and_parse_report(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        metrics, full_text = parse_pdf_text(file_path)
        explanation = generate_explanation(metrics, full_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    return {
        "status": "success",
        "filename": file.filename,
        "metrics_extracted_count": len(metrics),
        "metrics": metrics,
        "explanation_summary": explanation["summary"],
        "recommendations": explanation["recommendations"]
    }
