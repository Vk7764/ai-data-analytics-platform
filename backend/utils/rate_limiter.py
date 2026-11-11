# backend/utils/rate_limiter.py
import os
import sqlite3
import time
import ipaddress
from collections import defaultdict
from threading import Lock
from fastapi import Request, HTTPException
import jwt as pyjwt

from backend.auth.auth import verify_token
from backend.database.dataset_store import DB_PATH

# Optional shared limiter: set RATE_LIMIT_SHARED=1 to count requests in the existing SQLite database,
# so limits hold across multiple workers. Disabled by default; any failure falls back to the in-memory limiter.
_SHARED_RETRY_AFTER_FAILURE_SECONDS = 30
_SHARED_SWEEP_INTERVAL_CALLS = 200
_SHARED_IDLE_GRACE_SECONDS = 3600
_shared_disabled_until = 0.0
_shared_calls = 0
_shared_schema_ready = False
_SHARED_STATE_LOCK = Lock()
_SHARED_SCHEMA_LOCK = Lock()


def _shared_enabled() -> bool:
    return (os.environ.get("RATE_LIMIT_SHARED") or "").strip() == "1" and time.time() >= _shared_disabled_until


def _mark_shared_unavailable() -> None:
    global _shared_disabled_until, _shared_calls, _shared_schema_ready
    with _SHARED_STATE_LOCK:
        _shared_disabled_until = time.time() + _SHARED_RETRY_AFTER_FAILURE_SECONDS
        _shared_calls = 0
    with _SHARED_SCHEMA_LOCK:
        _shared_schema_ready = False


def _should_sweep() -> bool:
    global _shared_calls
    with _SHARED_STATE_LOCK:
        _shared_calls += 1
        return _shared_calls % _SHARED_SWEEP_INTERVAL_CALLS == 0


def _ensure_shared_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rate_limit_hits ("
        "bucket TEXT, hit_at REAL, window_seconds INTEGER)"
    )
    try:
        conn.execute("ALTER TABLE rate_limit_hits ADD COLUMN window_seconds INTEGER")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_bucket_hit "
        "ON rate_limit_hits (bucket, hit_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_expiry "
        "ON rate_limit_hits (hit_at)"
    )


def _ensure_shared_schema_once(conn: sqlite3.Connection) -> None:
    global _shared_schema_ready
    if _shared_schema_ready:
        return
    with _SHARED_SCHEMA_LOCK:
        if _shared_schema_ready:
            return
        _ensure_shared_schema(conn)
        _shared_schema_ready = True


def _shared_check(bucket: str, max_requests: int, window_seconds: int):
    """
    Records one hit in SQLite when the bucket is under its limit.
    Returns True (allowed), False (limit reached) or None (shared store unavailable: use the in-memory limiter).
    """
    conn = None
    try:
        now = time.time()
        cutoff = now - window_seconds
        conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)  # autocommit: transactions are explicit
        conn.execute("BEGIN IMMEDIATE")  # takes the write lock, so concurrent workers count atomically
        _ensure_shared_schema_once(conn)
        conn.execute(
            "DELETE FROM rate_limit_hits WHERE bucket = ? AND hit_at < ?",
            (bucket, cutoff),
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM rate_limit_hits WHERE bucket = ?", (bucket,)
        ).fetchone()[0]
        allowed = count < max_requests
        if allowed:
            conn.execute(
                "INSERT INTO rate_limit_hits (bucket, hit_at, window_seconds) VALUES (?, ?, ?)",
                (bucket, now, window_seconds),
            )

        if _should_sweep():
            # Remove rows that expired at least an hour ago. This keeps idle buckets from growing without
            # bound without assuming a maximum limiter window.
            conn.execute(
                "DELETE FROM rate_limit_hits WHERE hit_at + COALESCE(window_seconds, 0) < ?",
                (now - _SHARED_IDLE_GRACE_SECONDS,),
            )

        conn.execute("COMMIT")
        return allowed
    except Exception as e:
        print(f"[rate_limiter] Shared limiter unavailable, using in-memory fallback: {e}")
        _mark_shared_unavailable()
        try:
            if conn is not None:
                conn.execute("ROLLBACK")
        except Exception:
            pass
        return None
    finally:
        if conn is not None:
            conn.close()


class RateLimiter:
    """
    A simple in-memory, sliding-window rate limiter. Good enough for a
    single-server deployment; if this app is ever scaled across multiple
    server instances, this would need to move to a shared store (Redis) so
    limits are enforced consistently across all instances.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str) -> None:
        if _shared_enabled():
            # Limiters with different limits never share a bucket, even for the same key.
            shared_result = _shared_check(
                f"{self.max_requests}:{self.window_seconds}:{key}", self.max_requests, self.window_seconds
            )
            if shared_result is True:
                return
            if shared_result is False:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Please wait a moment and try again (limit: {self.max_requests} per {self.window_seconds}s).",
                )
            # shared_result is None: fall through to the in-memory limiter below.

        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            # Drop idle keys so the table cannot grow without bound.
            if len(self._hits) > 10000:
                stale_keys = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
                for stale_key in stale_keys:
                    del self._hits[stale_key]
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Please wait a moment and try again (limit: {self.max_requests} per {self.window_seconds}s).",
                )
            hits.append(now)


# Shared limiter instances used across the app
llm_limiter = RateLimiter(max_requests=20, window_seconds=60)      # AI-powered endpoints (cost control)
login_limiter = RateLimiter(max_requests=8, window_seconds=60)     # Login/signup attempts (brute-force protection)
upload_limiter = RateLimiter(max_requests=15, window_seconds=60)   # File uploads
export_limiter = RateLimiter(max_requests=12, window_seconds=60)   # Heavy chart/export endpoints
report_limiter = RateLimiter(max_requests=10, window_seconds=60)   # Heavy report generation endpoints
sql_limiter = RateLimiter(max_requests=20, window_seconds=60)      # Local SQL query endpoints
share_view_limiter = RateLimiter(max_requests=30, window_seconds=60)  # Public read-only share viewer
write_limiter = RateLimiter(max_requests=30, window_seconds=60)    # Lightweight DB write endpoints
security_limiter = RateLimiter(max_requests=10, window_seconds=60) # Share link create/revoke and sensitive writes


def get_client_key(request: Request) -> str:
    """
    Identifies who to rate-limit. For any logged-in request (which is every
    LLM/upload endpoint), the key is the user's account id — so usage is
    fairly counted per account, not per network. This matters for a
    multi-tenant SaaS: without it, several users sharing an office WiFi
    would all share (and exhaust) one limit, while a single user switching
    networks would get a fresh one. Falls back to IP address only for
    pre-login endpoints (login/signup) where there's no account yet.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "").strip()
        try:
            # We only need the user id for rate-limit keying here — the
            # actual signature/expiry check still happens in require_auth
            # right after, so a tampered token simply falls back to IP
            # keying rather than being trusted for anything.
            # The signature and expiry are verified: forged or rotated fake tokens fall through to IP keying.
            user_id = verify_token(token)
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass

    client_host = request.client.host if request.client else ""

    # Behind a private-network reverse proxy (nginx sets X-Real-IP), key on the real client address.
    # Requests arriving directly from a public address can never spoof this header.
    try:
        from_private_proxy = ipaddress.ip_address(client_host).is_private
    except ValueError:
        from_private_proxy = False
    if from_private_proxy:
        forwarded_ip = (request.headers.get("x-real-ip") or "").strip()
        if forwarded_ip:
            return f"ip:{forwarded_ip}"

    return f"ip:{client_host}" if client_host else "ip:unknown"


def rate_limit(limiter: RateLimiter):
    """FastAPI dependency factory: use as Depends(rate_limit(llm_limiter))."""
    def dependency(request: Request):
        limiter.check(get_client_key(request))
    return dependency