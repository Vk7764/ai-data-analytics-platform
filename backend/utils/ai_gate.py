# backend/utils/ai_gate.py
import os
import json
import threading
import hashlib
import sqlite3
import datetime
from typing import Any, Callable, Dict, Optional

import pandas as pd
from fastapi import HTTPException

from backend.database.dataset_store import DB_PATH
from backend.auth.user_store import UserStore


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


FREE_DAILY_AI_LIMIT = _int_env("FREE_DAILY_AI_LIMIT", 30)
PREMIUM_DAILY_AI_LIMIT = _int_env("PREMIUM_DAILY_AI_LIMIT", 300)
CACHE_MAX_AGE_DAYS = 14

_INFLIGHT_GUARD = threading.Lock()
_INFLIGHT_LOCKS: Dict[str, threading.Lock] = {}


def _get_key_lock(key: str) -> threading.Lock:
    with _INFLIGHT_GUARD:
        lock = _INFLIGHT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _INFLIGHT_LOCKS[key] = lock
        return lock

# The daily counter resets at midnight India time (IST = UTC+5:30).
_IST_OFFSET = datetime.timedelta(hours=5, minutes=30)


class QuotaExceeded(Exception):
    """Raised when a user can't make an AI request right now (daily limit reached, or email not verified)."""
    status_code = 429


class EmailNotVerified(QuotaExceeded):
    """Raised when AI features are used before the account's email address is verified."""
    status_code = 403


def _today_ist() -> str:
    return (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + _IST_OFFSET).date().isoformat()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            user_id TEXT,
            usage_date TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            cache_key TEXT PRIMARY KEY,
            dataset_id TEXT,
            kind TEXT,
            response TEXT,
            created_at TEXT
        )
    """)
    return conn


def daily_limit_for(user_id: str) -> int:
    return PREMIUM_DAILY_AI_LIMIT if UserStore.get_plan(user_id) == "premium" else FREE_DAILY_AI_LIMIT


# ---------- Daily usage counter ----------

class UsageStore:
    @staticmethod
    def try_consume(user_id: str, limit: int) -> bool:
        """Atomically adds 1 to today's count, but only if the user is still under the limit."""
        today = _today_ist()
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO ai_usage (user_id, usage_date, count) VALUES (?, ?, 0)",
                (user_id, today),
            )
            cursor = conn.execute(
                "UPDATE ai_usage SET count = count + 1 WHERE user_id = ? AND usage_date = ? AND count < ?",
                (user_id, today, limit),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    @staticmethod
    def refund(user_id: str) -> None:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE ai_usage SET count = count - 1 WHERE user_id = ? AND usage_date = ? AND count > 0",
                (user_id, _today_ist()),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_used(user_id: str) -> int:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT count FROM ai_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, _today_ist()),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()


# ---------- Cache of AI-generated explanations ----------

class AICache:
    @staticmethod
    def get(cache_key: str) -> Optional[Dict[str, Any]]:
        cutoff = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=CACHE_MAX_AGE_DAYS)).isoformat()
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT response FROM ai_cache WHERE cache_key = ? AND created_at >= ?",
                (cache_key, cutoff),
            ).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()

    @staticmethod
    def set(cache_key: str, dataset_id: str, kind: str, response: Dict[str, Any]) -> None:
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO ai_cache (cache_key, dataset_id, kind, response, created_at) VALUES (?, ?, ?, ?, ?)",
                (cache_key, dataset_id, kind, json.dumps(response), datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def delete_for_dataset(dataset_id: str) -> None:
        """Called when a dataset is deleted, so no AI text derived from it is left behind."""
        conn = _get_connection()
        try:
            conn.execute("DELETE FROM ai_cache WHERE dataset_id = ?", (dataset_id,))
            conn.commit()
        finally:
            conn.close()


def _fingerprint(df: pd.DataFrame) -> str:
    """A hash of the dataset's current contents: any cleaning action changes it, which makes old cache entries unusable."""
    h = hashlib.sha256()
    h.update("|".join(map(str, df.columns)).encode("utf-8"))
    try:
        h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
    except Exception:
        h.update(df.to_csv(index=False).encode("utf-8"))
    return h.hexdigest()


def get_data_version(df: pd.DataFrame) -> str:
    """A short, stable identifier of the dataset's current contents (changes after any edit). Read-only helper."""
    return _fingerprint(df)[:16]


def _make_key(dataset_id: str, kind: str, params: Dict[str, Any], df: pd.DataFrame) -> str:
    raw = json.dumps(
        {"dataset": dataset_id, "kind": kind, "params": params, "data": _fingerprint(df)},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------- Helpers used by the routes ----------

def quota_message(user_id: str) -> str:
    limit = daily_limit_for(user_id)
    message = f"Daily AI limit reached ({limit}/{limit}). It resets at midnight IST."
    if UserStore.get_plan(user_id) != "premium":
        message += " Upgrade to Premium for a higher limit."
    return message


def consume_quota_or_raise(user_id: str) -> None:
    if not UserStore.is_email_verified(user_id):
        raise EmailNotVerified(
            "Please verify your email address to use AI features. "
            "Check your inbox for the verification link, or use the Resend button at the top of the page."
        )
    if not UsageStore.try_consume(user_id, daily_limit_for(user_id)):
        raise QuotaExceeded(quota_message(user_id))


def quota_or_http_429(user_id: str) -> None:
    """For endpoints that always need a fresh AI call (e.g. chat). Uses 403 for unverified email, 429 for the daily limit."""
    try:
        consume_quota_or_raise(user_id)
    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


def refund_quota(user_id: str) -> None:
    UsageStore.refund(user_id)


def cached_ai_call(
    dataset_id: str,
    user_id: str,
    kind: str,
    params: Dict[str, Any],
    df: pd.DataFrame,
    generate_fn: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Returns a saved answer if the same question was already answered for
    this exact data (costs nothing). Otherwise it counts one request
    against the user's daily limit, calls the AI, and saves the answer.
    If the AI call fails, the request is refunded.
    """
    key = _make_key(dataset_id, kind, params, df)

    with _get_key_lock(key):
        cached = AICache.get(key)
        if cached is not None:
            return cached

        consume_quota_or_raise(user_id)
        try:
            result = generate_fn()
        except Exception:
            UsageStore.refund(user_id)
            raise

        AICache.set(key, dataset_id, kind, result)
        return result


def get_usage_info(user_id: str) -> Dict[str, Any]:
    limit = daily_limit_for(user_id)
    return {
        "used": min(UsageStore.get_used(user_id), limit),
        "limit": limit,
        "plan": UserStore.get_plan(user_id),
    }