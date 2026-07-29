import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# In-memory per-IP rate limiting. No Redis: this app runs as a single Fly.io
# container (no horizontal scaling across processes), so an in-process store is
# sufficient and avoids an extra infrastructure dependency. State resets on
# deploy/restart, which is an acceptable tradeoff for a demo-scale app.
_request_log: dict[str, deque] = defaultdict(deque)

DATASET_UPLOAD_LIMIT = 5
DATASET_UPLOAD_WINDOW_SECONDS = 60 * 60

MATCH_LIMIT = 5
MATCH_WINDOW_SECONDS = 60 * 60


def _client_ip(request: Request) -> str:
    # Fly.io terminates TLS at its edge and forwards the real client IP via
    # Fly-Client-IP; fall back to the direct connection IP for local/dev runs.
    return request.headers.get("Fly-Client-IP") or (request.client.host if request.client else "unknown")


def _check_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    key = f"{bucket}:{_client_ip(request)}"
    now = time.monotonic()
    timestamps = _request_log[key]

    while timestamps and now - timestamps[0] > window_seconds:
        timestamps.popleft()

    if len(timestamps) >= limit:
        retry_after = int(window_seconds - (now - timestamps[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {limit} requests per {window_seconds // 60} minutes. "
            f"Try again in {retry_after}s.",
        )

    timestamps.append(now)


def rate_limit_dataset_upload(request: Request) -> None:
    _check_rate_limit(request, "dataset_upload", DATASET_UPLOAD_LIMIT, DATASET_UPLOAD_WINDOW_SECONDS)


def rate_limit_match(request: Request) -> None:
    _check_rate_limit(request, "match", MATCH_LIMIT, MATCH_WINDOW_SECONDS)
