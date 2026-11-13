import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.logsafe import protect_other_handlers, setup_logging
from backend.protection import access_code_required
from backend.routers import reports
from backend.services import glossary
from backend.services.parser import ocr_available

# No report text, access code or API key ever reaches the logs. See logsafe.py.
setup_logging()
logger = logging.getLogger("backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the glossary index in the background so the first upload doesn't
    # wait for it. Requests still work (just slower) if this hasn't finished.
    threading.Thread(target=glossary.warm, name="glossary-warm", daemon=True).start()
    protect_other_handlers()  # uvicorn's own log handlers exist by now
    yield


app = FastAPI(
    title="MediExplain MVP Backend",
    description="Stateless, privacy-focused medical report parser and synthesizer",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(reports.router, prefix="/reports", tags=["Reports"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Last-resort handler: anything not caught by a route still gets its real
    # type and traceback in the server log, while the client sees a generic 500.
    logger.error(
        "Unhandled %s on %s %s",
        type(exc).__name__, request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "MediExplain Stateless Backend",
        "ocr_available": ocr_available(),
        # Lets the web page show the code field only when it is needed.
        "access_code_required": access_code_required(),
    }
