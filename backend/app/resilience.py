from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import Request

from .config import get_settings


_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = Lock()
_last_cleanup = 0.0


def client_ip(request: Request) -> str:
    """Return the peer address resolved by the trusted ASGI server.

    X-Forwarded-For is deliberately ignored because its leftmost entries are
    client-controlled. Uvicorn runs with --proxy-headers, so request.client
    already contains the address supplied by the trusted proxy.
    """
    return (request.client.host if request.client else "unknown")[:80]


def rate_limit_retry_after(request: Request) -> int | None:
    """Return seconds to retry, or None when this request is allowed.

    This is a bounded, per-instance protection against accidental floods and
    small abusive bursts. Volumetric DDoS protection still belongs at the edge.
    """
    global _last_cleanup
    if not request.url.path.startswith("/api/") or request.url.path.startswith("/api/health"):
        return None

    settings = get_settings()
    expensive = request.method in {"POST", "PUT", "PATCH"} and request.url.path in {
        "/api/scans", "/api/analysis/advanced",
    }
    scope = "upload" if expensive else "api"
    maximum = settings.upload_requests_per_minute if expensive else settings.api_requests_per_minute
    key = (scope, client_ip(request))
    now = monotonic()
    cutoff = now - 60

    with _lock:
        bucket = _requests[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= maximum:
            return max(1, round(60 - (now - bucket[0])))
        bucket.append(now)

        if now - _last_cleanup > 60:
            stale = [item for item, values in _requests.items() if not values or values[-1] <= cutoff]
            for item in stale:
                _requests.pop(item, None)
            _last_cleanup = now
    return None


def reset_rate_limits() -> None:
    global _last_cleanup
    with _lock:
        _requests.clear()
        _last_cleanup = 0.0
