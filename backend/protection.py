"""Public-demo protections: access code and request caps.

Access code
- If ACCESS_CODE is set, POST /reports/upload needs a matching X-Access-Code
  header (compared in constant time), otherwise 401.
- If ACCESS_CODE is not set, the check is skipped so local development works.

Request caps (in memory)
- MAX_REQUESTS_PER_DAY (default 100): all uploads together, per UTC day.
- MAX_REQUESTS_PER_IP_PER_HOUR (default 10): per client IP, rolling hour.
- Over a cap -> 429. Only requests with a valid code count.
- The counters live in this process: a restart resets them, and each worker
  process has its own counters (run a single worker for the caps to hold).

Client IP
- By default the TCP peer address. If the backend is only reachable through
  the Streamlit front end or a proxy, every request comes from that one
  address; set TRUST_FORWARDED_FOR=true so the first X-Forwarded-For entry is
  used instead. Only do that when clients cannot reach the backend directly,
  since the header is easy to fake.
"""
import hmac
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import Header, HTTPException, Request

DEFAULT_PER_DAY = 100
DEFAULT_PER_IP_PER_HOUR = 10

ACCESS_DENIED = (
    "This demo needs an access code. Please enter the code you were given and try again."
)
IP_LIMIT = (
    "You have reached the limit of {n} reports per hour for this demo. "
    "Please try again later."
)
DAY_LIMIT = "This demo has reached its limit for today. Please try again tomorrow."


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
        return value if value > 0 else default
    except ValueError:
        return default


def access_code_required() -> bool:
    return bool(os.environ.get("ACCESS_CODE"))


def require_access_code(x_access_code: str | None = Header(default=None)) -> None:
    """FastAPI dependency. Read at request time so the setting can change without code edits."""
    expected = os.environ.get("ACCESS_CODE")
    if not expected:
        return  # local development: no code configured
    given = x_access_code or ""
    # compare_digest takes the same time whatever the input, so the code can't
    # be guessed character by character from response times.
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail=ACCESS_DENIED)


def client_ip(request: Request) -> str:
    if os.environ.get("TRUST_FORWARDED_FOR", "").lower() in ("1", "true", "yes"):
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RequestCaps:
    """Global daily cap and per-IP hourly cap, thread-safe, in memory."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._day = None
        self._day_count = 0
        self._per_ip: dict[str, deque] = {}

    def reset(self) -> None:
        with self._lock:
            self._day, self._day_count = None, 0
            self._per_ip.clear()

    def check_and_count(self, ip: str) -> None:
        """Count one request, or raise 429 without counting it."""
        per_day = _int_env("MAX_REQUESTS_PER_DAY", DEFAULT_PER_DAY)
        per_hour = _int_env("MAX_REQUESTS_PER_IP_PER_HOUR", DEFAULT_PER_IP_PER_HOUR)
        now = self._clock()
        today = datetime.fromtimestamp(now, timezone.utc).date()
        with self._lock:
            if today != self._day:
                self._day, self._day_count = today, 0
            hits = self._per_ip.setdefault(ip, deque())
            while hits and hits[0] <= now - 3600:
                hits.popleft()
            # Per-IP first: one busy user should not use up everyone's daily budget.
            if len(hits) >= per_hour:
                retry = int(hits[0] + 3600 - now) + 1
                raise HTTPException(status_code=429, detail=IP_LIMIT.format(n=per_hour),
                                    headers={"Retry-After": str(retry)})
            if self._day_count >= per_day:
                tomorrow = datetime.combine(today, datetime.min.time(), timezone.utc).timestamp() + 86400
                raise HTTPException(status_code=429, detail=DAY_LIMIT,
                                    headers={"Retry-After": str(int(tomorrow - now) + 1)})
            hits.append(now)
            self._day_count += 1
            # Drop IPs with no recent requests so memory stays small.
            if len(self._per_ip) > 10_000:
                for key in [k for k, v in self._per_ip.items() if not v]:
                    del self._per_ip[key]


caps = RequestCaps()


def enforce_caps(request: Request) -> None:
    """FastAPI dependency. Runs after the access check, so bad codes don't use the caps."""
    caps.check_and_count(client_ip(request))
