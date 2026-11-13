from fastapi import FastAPI
from backend.routers import reports

app = FastAPI(
    title="MediExplain MVP Backend",
    description="Stateless, privacy-focused medical report parser and synthesizer",
    version="2.0.0"
)

app.include_router(reports.router, prefix="/reports", tags=["Reports"])

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "service": "MediExplain Stateless Backend"}
