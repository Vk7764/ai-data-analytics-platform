# backend/auth/account_deletion.py
import os
import hashlib
import secrets
import sqlite3
import datetime
from typing import Tuple

from backend.database.dataset_store import DB_PATH, DatasetStore, configure_sqlite_connection
from backend.agents.orchestrator import Orchestrator
from backend.utils.ai_gate import AICache
from backend.reports.generator import ReportGenerator, OUTPUT_DIR
from backend.auth.user_store import UserStore
from backend.utils.email_sender import send_email

DELETION_LINK_MINUTES = 30
MAX_PASSWORD_ATTEMPTS = 5


# ---------- Deletion confirmation links ----------

def _get_connection() -> sqlite3.Connection:
    conn = configure_sqlite_connection(sqlite3.connect(DB_PATH, timeout=30))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_deletion_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT,
            email TEXT,
            expires_at TEXT,
            attempts INTEGER DEFAULT 0
        )
    """)
    return conn


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_deletion_token(user_id: str, email: str) -> str:
    """
    Creates a short-lived confirmation token. Only its hash is stored, and
    the email address it was sent to is stored with it, so a link emailed to
    an old address stops working if the account's email is changed later.
    Any earlier link for the same user is replaced.
    """
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(minutes=DELETION_LINK_MINUTES)).isoformat()

    conn = _get_connection()
    try:
        conn.execute("DELETE FROM account_deletion_tokens WHERE user_id = ?", (user_id,))
        conn.execute(
            "INSERT INTO account_deletion_tokens (token_hash, user_id, email, expires_at, attempts) VALUES (?, ?, ?, ?, 0)",
            (_hash(token), user_id, email, expires_at),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def send_deletion_email(user_id: str, email: str) -> bool:
    """Emails the confirmation link. Returns True if the email was sent."""
    token = create_deletion_token(user_id, email)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    link = f"{frontend_url}/confirm-delete?token={token}"
    return send_email(
        to_email=email,
        subject="Confirm your account deletion",
        body_html=f"""
            <p>You asked to permanently delete your account and all its data.</p>
            <p><a href="{link}">Confirm account deletion</a></p>
            <p>On the next page you'll be asked for your password. This link expires in {DELETION_LINK_MINUTES} minutes.</p>
            <p>If you didn't ask for this, ignore this email: nothing will be deleted.
            You may also want to change your password, in case someone else has access to your logged-in session.</p>
        """,
    )


def confirm_deletion(token: str, password: str) -> Tuple[str, int]:
    """
    Checks the emailed token and the account password, and deletes the
    account only if both are right.
    Returns (status, attempts_left) where status is one of:
    "deleted", "wrong_password", "too_many_attempts", "invalid_link".
    """
    token_hash = _hash(token)
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT user_id, email, expires_at, attempts FROM account_deletion_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if not row:
            return "invalid_link", 0
        user_id, email, expires_at, attempts = row

        expired = datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        user = UserStore.get_user(user_id)
        # Also invalid if the account is gone or its email changed after the link was sent.
        if expired or not user or user["email"] != email:
            conn.execute("DELETE FROM account_deletion_tokens WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return "invalid_link", 0

        if UserStore.verify_credentials(email, password) != user_id:
            attempts += 1
            if attempts >= MAX_PASSWORD_ATTEMPTS:
                conn.execute("DELETE FROM account_deletion_tokens WHERE token_hash = ?", (token_hash,))
                conn.commit()
                return "too_many_attempts", 0
            conn.execute(
                "UPDATE account_deletion_tokens SET attempts = ? WHERE token_hash = ?",
                (attempts, token_hash),
            )
            conn.commit()
            return "wrong_password", MAX_PASSWORD_ATTEMPTS - attempts
    finally:
        conn.close()

    # Only reached when the link and the password are both correct.
    delete_account(user_id)
    return "deleted", 0


# ---------- The deletion itself ----------

def purge_report_files(dataset_id: str) -> None:
    """
    Deletes generated report/export files (PDF, Excel, PPT, JSON, SQL) for a
    dataset that are still sitting on the server's disk. Without this,
    deleting a dataset would leave copies of its data behind in files.
    """
    prefix = ReportGenerator._safe_filename(dataset_id) + "_"
    try:
        names = os.listdir(OUTPUT_DIR)
    except OSError:
        return
    for name in names:
        if name.startswith(prefix):
            try:
                os.remove(os.path.join(OUTPUT_DIR, name))
            except OSError:
                pass


def delete_account(user_id: str) -> None:
    """
    Permanently removes a user and everything tied to them: datasets (and
    their undo snapshots and audit logs), chat history, cached AI text,
    generated report files, schedules, branding, daily usage counters,
    login-related tokens, and finally the user record itself.
    """
    owned_dataset_ids = []
    for dataset in DatasetStore.list_all(user_id, limit=None):
        dataset_id = dataset["dataset_id"]
        owned_dataset_ids.append(dataset_id)
        Orchestrator.reset_conversation(dataset_id)
        AICache.delete_for_dataset(dataset_id)
        purge_report_files(dataset_id)
        DatasetStore.delete(dataset_id, user_id)

    conn = sqlite3.connect(DB_PATH)
    try:
        # Fixed table names (never user input). A table may not exist yet if
        # its feature was never used, hence the OperationalError guard.
        for table, column in [
            ("scheduled_exports", "user_id"),
            ("saved_analyses", "user_id"),
            ("dataset_shares", "owner_user_id"),
            ("user_branding", "user_id"),
            ("ai_usage", "user_id"),
            ("password_reset_tokens", "user_id"),
            ("email_verification_tokens", "user_id"),
            ("account_deletion_tokens", "user_id"),
            ("users", "id"),
        ]:
            try:
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (user_id,))
            except sqlite3.OperationalError:
                pass
        for orphan_dataset_id in owned_dataset_ids:
            try:
                conn.execute("DELETE FROM chat_history WHERE dataset_id = ?", (orphan_dataset_id,))
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()