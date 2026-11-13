"""Logging that never writes report text, the access code, or API keys.

- Exceptions are logged as their type and stack frames only. Exception
  *messages* are left out, because they can carry report content (for
  example a JSON validation error quoting the model's output, or a search
  error quoting a report line). Gemini API errors keep their HTTP code and
  status, which are safe and useful.
- As a last line of defence, the values of GEMINI_API_KEY and ACCESS_CODE
  are masked in every formatted log line, from our loggers and uvicorn's.
- Our own log messages only ever contain counts, model names, timings,
  file kinds and fixed text, never report text.
"""
import logging
import os
import traceback

SECRET_ENV_VARS = ("GEMINI_API_KEY", "ACCESS_CODE")
MASK = "[REDACTED]"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def redact(text: str) -> str:
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 4:  # don't mask tiny strings that appear everywhere
            text = text.replace(value, MASK)
    return text


def _describe(exc: BaseException) -> str:
    name = f"{type(exc).__module__}.{type(exc).__qualname__}"
    code, status = getattr(exc, "code", None), getattr(exc, "status", None)
    if type(exc).__module__.startswith("google.genai") and code is not None:
        return f"{name} (code={code}, status={status})"
    return name


def safe_exception_text(exc: BaseException) -> str:
    """Traceback with frames and exception types, without exception messages."""
    chain, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    lines = ["Traceback (exception messages omitted so no report data is logged):"]
    for i, e in enumerate(reversed(chain)):
        if i:
            lines.append("During handling of the above, another exception occurred:")
        lines.extend(l.rstrip("\n") for l in traceback.format_tb(e.__traceback__))
        lines.append(_describe(e))
    return "\n".join(lines)


class SafeFormatter(logging.Formatter):
    def formatException(self, ei) -> str:
        exc = ei[1]
        return safe_exception_text(exc) if exc is not None else ""

    def format(self, record: logging.LogRecord) -> str:
        # Don't reuse a cached traceback another formatter may have built with messages.
        record.exc_text = None
        return redact(super().format(record))


class RedactFilter(logging.Filter):
    """For handlers we don't format ourselves (uvicorn's): mask secrets in the message."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = next((h for h in root.handlers if getattr(h, "_mediexplain", False)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler._mediexplain = True
        root.addHandler(handler)
    handler.setFormatter(SafeFormatter(FORMAT))
    protect_other_handlers()


def protect_other_handlers() -> None:
    """Add secret masking to uvicorn's handlers (they exist once uvicorn has started)."""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactFilter) for f in h.filters):
                h.addFilter(RedactFilter())
