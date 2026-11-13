# backend/utils/payments.py
"""
Razorpay payment gateway helpers.

Uses Razorpay's plain REST API with `requests` (already a project dependency),
so no extra package is needed. Orders are created server-side; the checkout
response signature is verified server-side with HMAC-SHA256 before the plan
is upgraded, so a tampered client can never grant itself Premium.

Every upgraded order is recorded in the `processed_payments` table, so an
order/payment can never be replayed and the upgrade is idempotent.

Configure in .env:
  RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
  RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
  RAZORPAY_WEBHOOK_SECRET=xxxxxxxx   (optional: upgrades users whose browser closed mid-checkout)
  PREMIUM_PRICE_INR=499
While the keys are empty, /api/payments/status reports enabled=false and the
frontend hides the upgrade UI. The manual admin endpoint keeps working.
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import sqlite3

import requests

from backend.auth.user_store import UserStore
from backend.database.dataset_store import DB_PATH, configure_sqlite_connection

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"
_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _key_id() -> str:
    return (os.environ.get("RAZORPAY_KEY_ID") or "").strip()


def _key_secret() -> str:
    return (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()


def webhook_secret() -> str:
    return (os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip()


def get_public_key() -> str:
    return _key_id()


def premium_price_inr() -> int:
    try:
        return max(1, int(os.environ.get("PREMIUM_PRICE_INR", "499")))
    except (TypeError, ValueError):
        return 499


def is_configured() -> bool:
    return bool(_key_id() and _key_secret())


def _get_connection() -> sqlite3.Connection:
    conn = configure_sqlite_connection(sqlite3.connect(DB_PATH, timeout=30))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS processed_payments ("
        "order_id TEXT PRIMARY KEY, payment_id TEXT, user_id TEXT, created_at TEXT)"
    )
    return conn


def _claim_order(order_id: str, payment_id: str, user_id: str) -> str:
    """Atomically records an order. Returns 'new', 'same_user' (already processed) or 'other_user'."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO processed_payments (order_id, payment_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (order_id, payment_id or "", user_id, now),
        )
        conn.commit()
        if cursor.rowcount == 1:
            return "new"
        row = conn.execute(
            "SELECT user_id FROM processed_payments WHERE order_id = ?", (order_id,)
        ).fetchone()
        return "same_user" if row and row[0] == user_id else "other_user"
    finally:
        conn.close()


def _release_claim(order_id: str) -> None:
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM processed_payments WHERE order_id = ?", (order_id,))
        conn.commit()
    finally:
        conn.close()


def create_order(user_id: str, email: str) -> dict:
    """
    Creates a Razorpay order for the Premium upgrade. Amount is in paise.
    Returns {"order_id", "amount", "currency", "key_id"}.
    """
    if not is_configured():
        raise RuntimeError("Payments are not configured on the server.")
    amount_paise = premium_price_inr() * 100
    resp = requests.post(
        RAZORPAY_ORDERS_URL,
        auth=(_key_id(), _key_secret()),
        json={
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"premium:{user_id}"[:40],
            "notes": {"user_id": user_id, "email": email},
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Razorpay order creation failed (HTTP {resp.status_code}).")
    data = resp.json()
    if not data.get("id"):
        raise RuntimeError("Razorpay returned an unexpected order response.")
    return {
        "order_id": data["id"],
        "amount": data.get("amount", amount_paise),
        "currency": data.get("currency", "INR"),
        "key_id": _key_id(),
    }


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    Verifies the signature Razorpay Checkout returns in the browser:
    HMAC-SHA256(order_id + '|' + payment_id, key_secret).
    """
    if not is_configured():
        return False
    expected = hmac.new(
        _key_secret().encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verifies the X-Razorpay-Signature header: HMAC-SHA256(raw request body, webhook secret)."""
    secret = webhook_secret()
    if not secret or not isinstance(raw_body, (bytes, bytearray)):
        return False
    expected = hmac.new(secret.encode("utf-8"), bytes(raw_body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())


def fetch_order(order_id: str):
    """Fetches an order from Razorpay (authoritative). Returns a dict or None."""
    if not isinstance(order_id, str) or not _ORDER_ID_PATTERN.match(order_id):
        return None
    try:
        resp = requests.get(
            f"{RAZORPAY_ORDERS_URL}/{order_id}",
            auth=(_key_id(), _key_secret()),
            timeout=20,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def order_is_paid(order_id: str, user_id: str = None) -> bool:
    """
    Double-checks with Razorpay that the order is actually paid, not just signed.
    When user_id is given, the order must also have been created for that user.
    """
    data = fetch_order(order_id)
    if not data or data.get("status") != "paid":
        return False
    if user_id is not None:
        notes = data.get("notes")
        if not isinstance(notes, dict) or notes.get("user_id") != user_id:
            return False
    return True


def upgrade_to_premium(user_id: str, order_id: str = None, payment_id: str = None) -> bool:
    """
    Upgrades a user to Premium after a verified payment. When an order id is given, the order is
    recorded first so it can never be replayed or credited to a second account. A repeated call for an
    already-processed order does not change the plan again; it only reports whether the user is Premium.
    """
    user = UserStore.get_user(user_id)
    if not user:
        return False

    if not order_id:
        return UserStore.set_plan(user["email"], "premium")

    claim = _claim_order(order_id, payment_id or "", user_id)
    if claim == "other_user":
        return False
    if claim == "same_user":
        return UserStore.get_plan(user_id) == "premium"

    try:
        upgraded = UserStore.set_plan(user["email"], "premium")
    except Exception:
        _release_claim(order_id)
        raise
    if not upgraded:
        _release_claim(order_id)
    return upgraded


def handle_webhook_event(raw_body: bytes) -> str:
    """
    Processes a signature-verified Razorpay webhook body (payment.captured / order.paid).
    Returns 'upgraded', 'ignored' or 'failed'. The order is re-read from Razorpay, so the webhook body
    alone is never trusted for the user or the paid status.
    """
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return "ignored"
    if not isinstance(event, dict) or event.get("event") not in ("payment.captured", "order.paid"):
        return "ignored"

    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payment_wrapper = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    order_wrapper = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    payment = payment_wrapper.get("entity") if isinstance(payment_wrapper.get("entity"), dict) else {}
    order = order_wrapper.get("entity") if isinstance(order_wrapper.get("entity"), dict) else {}

    order_id = order.get("id") or payment.get("order_id")
    payment_id = payment.get("id")
    if not order_id or not payment_id:
        return "ignored"

    order_data = fetch_order(order_id)
    if not order_data or order_data.get("status") != "paid":
        return "ignored"

    notes = order_data.get("notes")
    user_id = notes.get("user_id") if isinstance(notes, dict) else None
    if not user_id:
        return "ignored"

    return "upgraded" if upgrade_to_premium(str(user_id), order_id, payment_id) else "failed"