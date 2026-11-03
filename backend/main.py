from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from backend.database import get_db_connection
from backend.routers import reports, history

load_dotenv()

app = FastAPI(
    title="MediExplain API",
    description="Backend service for parsing medical reports and generating plain-language explanations.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(reports.router)
app.include_router(history.router)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "MediExplain API",
        "message": "Server is running successfully."
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/db-test")
def test_database_connection():
    """Test connection to PostgreSQL database."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            db_version = cur.fetchone()
        conn.close()
        return {
            "status": "success",
            "message": "Successfully connected to PostgreSQL!",
            "database_version": db_version[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
