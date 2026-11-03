import os
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from pypdf import PdfReader
from backend.database import get_db_connection
from backend.services.parser import extract_lab_metrics
from backend.services.explainer import generate_explanation_report

router = APIRouter(prefix="/reports", tags=["Reports"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload")
async def upload_and_parse_report(file: UploadFile = File(...), user_id: int = 1):
    """
    Upload a medical PDF report, save it locally, extract its text, 
    parse metrics, generate a plain-language explanation, and store all records in PostgreSQL.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    # Save uploaded file locally
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Extract text using pypdf
    extracted_text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF text: {str(e)}")
    
    # Parse structured lab metrics from text
    parsed_metrics = extract_lab_metrics(extracted_text)
    
    # Generate plain-language explanation and recommendations
    summary, recommendations = generate_explanation_report(parsed_metrics)
    
    # Save document record, metrics, and explanation report to PostgreSQL
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Ensure default user exists
            cur.execute("INSERT INTO users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (user_id, "user@example.com"))
            
            # Insert document
            cur.execute(
                """
                INSERT INTO lab_documents (user_id, filename, file_path) 
                VALUES (%s, %s, %s) RETURNING id;
                """,
                (user_id, file.filename, file_path)
            )
            doc_id = cur.fetchone()[0]
            
            # Insert extracted metrics
            for metric in parsed_metrics:
                cur.execute(
                    """
                    INSERT INTO lab_metrics (document_id, test_name, test_value, unit, reference_range, status)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (
                        doc_id, 
                        metric["test_name"], 
                        metric["test_value"], 
                        metric["unit"], 
                        metric["reference_range"], 
                        metric["status"]
                    )
                )
                
            # Insert generated explanation report
            cur.execute(
                """
                INSERT INTO explanation_reports (document_id, summary, recommendations)
                VALUES (%s, %s, %s);
                """,
                (doc_id, summary, recommendations)
            )
                
            conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")

    return {
        "status": "success",
        "document_id": doc_id,
        "filename": file.filename,
        "metrics_extracted_count": len(parsed_metrics),
        "metrics": parsed_metrics,
        "explanation_summary": summary,
        "recommendations": recommendations
    }
