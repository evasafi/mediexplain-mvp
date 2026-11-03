from fastapi import APIRouter, HTTPException
from backend.database import get_db_connection

router = APIRouter(prefix="/reports", tags=["Reports History"])

@router.get("/history/{user_id}")
def get_user_report_history(user_id: int):
    """
    Retrieve all uploaded lab reports, their extracted metrics, 
    and explanation summaries for a specific user.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Fetch user documents
            cur.execute(
                """
                SELECT id, filename, uploaded_at 
                FROM lab_documents 
                WHERE user_id = %s 
                ORDER BY uploaded_at DESC;
                """,
                (user_id,)
            )
            docs = cur.fetchall()
            
            history = []
            for doc in docs:
                doc_id, filename, uploaded_at = doc
                
                # Fetch metrics for this document
                cur.execute(
                    """
                    SELECT test_name, test_value, unit, reference_range, status 
                    FROM lab_metrics 
                    WHERE document_id = %s;
                    """,
                    (doc_id,)
                )
                metrics = [
                    {
                        "test_name": row[0],
                        "test_value": row[1],
                        "unit": row[2],
                        "reference_range": row[3],
                        "status": row[4]
                    }
                    for row in cur.fetchall()
                ]
                
                # Fetch explanation report for this document
                cur.execute(
                    """
                    SELECT summary, recommendations, created_at 
                    FROM explanation_reports 
                    WHERE document_id = %s;
                    """,
                    (doc_id,)
                )
                exp_row = cur.fetchone()
                explanation = None
                if exp_row:
                    explanation = {
                        "summary": exp_row[0],
                        "recommendations": exp_row[1],
                        "created_at": exp_row[2]
                    }
                
                history.append({
                    "document_id": doc_id,
                    "filename": filename,
                    "uploaded_at": uploaded_at,
                    "metrics_count": len(metrics),
                    "metrics": metrics,
                    "explanation": explanation
                })
                
        conn.close()
        return {
            "status": "success",
            "user_id": user_id,
            "total_reports": len(history),
            "reports": history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")
