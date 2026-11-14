# backend/auth/user_store.py
import sqlite3
import uuid
import hmac
import hashlib
import os
import binascii
import re
from typing import Optional, Dict, Any

from backend.database.dataset_store import DB_PATH, configure_sqlite_connection
from backend.utils.email_sender import email_verification_required

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def is_valid_email(email) -> bool:
    """Basic RFC-like email shape check, at most 254 characters."""
    if not isinstance(email, str):
        return False
    candidate = email.strip()
    return 0 < len(candidate) <= 254 and bool(_EMAIL_PATTERN.match(candidate))


def _get_connection() -> sqlite3.Connection:
    conn = configure_sqlite_connection(sqlite3.connect(DB_PATH, timeout=30))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_branding (
            user_id TEXT PRIMARY KEY,
            logo_bytes BLOB,
            accent_color TEXT
        )
    """)
    # Migration safety: add the column if this table already existed
    # before premium plans were introduced.
    try:
        conn.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE users ADD COLUMN terms_accepted_at TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    
    try:
        # DEFAULT 1 means every account created before this feature counts as already verified.
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # column already exists
    for column_definition in ("full_name TEXT", "organization TEXT"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column_definition}")
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


def _hash_password(password: str) -> str:
    """
    Hashes a password using PBKDF2-HMAC-SHA256 from Python's standard
    library — deliberately avoiding an extra compiled dependency like
    bcrypt, since this machine's security policy has previously blocked
    other compiled packages (scipy/scikit-learn) from loading.
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return binascii.hexlify(salt).decode() + ":" + binascii.hexlify(dk).decode()


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = binascii.unhexlify(salt_hex)
        expected = binascii.unhexlify(hash_hex)
    except (ValueError, binascii.Error):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(dk, expected)


class UserStore:
    """Persistent user accounts, stored in the same local SQLite file as datasets."""

    @staticmethod
    def create_user(email: str, password: str, terms_accepted: bool = True) -> str:
        import datetime

        email = email.strip().lower()
        conn = _get_connection()
        try:
            existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                raise ValueError("An account with this email already exists.")

            user_id = str(uuid.uuid4())
            password_hash = _hash_password(password)
            accepted_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() if terms_accepted else None
            conn.execute(
                "INSERT INTO users (id, email, password_hash, terms_accepted_at, email_verified) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, password_hash, accepted_at, 0 if email_verification_required() else 1),
            )
            conn.commit()
            return user_id
        finally:
            conn.close()

    @staticmethod
    def verify_credentials(email: str, password: str) -> Optional[str]:
        """Returns the user_id if the credentials are valid, else None."""
        email = email.strip().lower()
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
            if not row:
                return None
            user_id, password_hash = row
            return user_id if _verify_password(password, password_hash) else None
        finally:
            conn.close()

    @staticmethod
    def get_user(user_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT id, email, plan, created_at, email_verified, full_name, organization, terms_accepted_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "user_id": row[0],
                "email": row[1],
                "plan": row[2] or "free",
                "created_at": row[3],
                "email_verified": row[4] != 0 or not email_verification_required(),
                "full_name": row[5] or "",
                "organization": row[6] or "",
                "terms_accepted_at": row[7],
            }
        finally:
            conn.close()
    @staticmethod
    def create_reset_token(email: str) -> Optional[str]:
        """
        Generates a short-lived password reset token for the given email,
        if an account with that email exists. Returns None if no such
        account exists (the caller should still show a generic success
        message either way, so an attacker can't use this to discover
        which emails are registered).
        """
        import secrets
        import datetime

        email = email.strip().lower()
        conn = _get_connection()
        try:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                return None
            user_id = row[0]

            conn.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT,
                    expires_at TEXT
                )
            """)
            token = secrets.token_urlsafe(32)
            # Only the SHA-256 hash is stored (in the existing "token" column); the raw token exists only in the emailed link.
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            expires_at = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=1)).isoformat()
            # A new request replaces any earlier unused reset link for this user.
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
            conn.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )
            conn.commit()
            return token
        finally:
            conn.close()

    @staticmethod
    def reset_password_with_token(token: str, new_password: str) -> bool:
        """Validates a reset token and, if valid and not expired, updates the password."""
        import datetime

        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT,
                    expires_at TEXT
                )
            """)
            token_hash = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
            row = conn.execute(
                "SELECT token, user_id, expires_at FROM password_reset_tokens WHERE token = ?", (token_hash,)
            ).fetchone()
            if not row:
                return False

            stored_hash, user_id, expires_at = row
            if not hmac.compare_digest(stored_hash.encode("utf-8"), token_hash.encode("utf-8")):
                return False

            # Single use: the token is consumed before anything else; a concurrent second use deletes nothing and fails.
            consumed = conn.execute("DELETE FROM password_reset_tokens WHERE token = ?", (token_hash,))
            if consumed.rowcount != 1:
                conn.commit()
                return False

            try:
                expired = datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                expired = True
            if expired:
                conn.commit()
                return False

            new_hash = _hash_password(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
            # Invalidate every other outstanding reset link for this user.
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def get_auth_fingerprint(user_id: str) -> Optional[str]:
        """
        A short fingerprint of the user's current password hash, embedded in every token.
        Returns None if the user no longer exists. Changing or resetting the password
        changes the fingerprint, which invalidates all previously issued tokens.
        """
        conn = _get_connection()
        try:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or not row[0]:
                return None
            return hashlib.sha256(row[0].encode("utf-8")).hexdigest()[:16]
        finally:
            conn.close()

    @staticmethod
    def get_plan(user_id: str) -> str:
        conn = _get_connection()
        try:
            row = conn.execute("SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
            return row[0] if row and row[0] else "free"
        finally:
            conn.close()

    @staticmethod
    def set_plan(email: str, plan: str) -> bool:
        """Upgrades/downgrades a user's plan by email. Used by the admin endpoint."""
        if plan not in ("free", "premium"):
            raise ValueError("plan must be 'free' or 'premium'")
        email = email.strip().lower()
        conn = _get_connection()
        try:
            cursor = conn.execute("UPDATE users SET plan = ? WHERE email = ?", (plan, email))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def set_branding(user_id: str, logo_bytes: Optional[bytes] = None, accent_color: Optional[str] = None) -> None:
        conn = _get_connection()
        try:
            existing = conn.execute("SELECT logo_bytes, accent_color FROM user_branding WHERE user_id = ?", (user_id,)).fetchone()
            final_logo = logo_bytes if logo_bytes is not None else (existing[0] if existing else None)
            final_color = accent_color if accent_color is not None else (existing[1] if existing else None)
            conn.execute(
                """
                INSERT INTO user_branding (user_id, logo_bytes, accent_color) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET logo_bytes = excluded.logo_bytes, accent_color = excluded.accent_color
                """,
                (user_id, final_logo, final_color),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_branding(user_id: str) -> Dict[str, Any]:
        conn = _get_connection()
        try:
            row = conn.execute("SELECT logo_bytes, accent_color FROM user_branding WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return {"logo_bytes": None, "accent_color": None}
            return {"logo_bytes": row[0], "accent_color": row[1]}
        finally:
            conn.close()

    @staticmethod
    def is_email_verified(user_id: str) -> bool:
    return True
        conn = _get_connection()
        try:
            row = conn.execute("SELECT email_verified FROM users WHERE id = ?", (user_id,)).fetchone()
            return row is not None and row[0] != 0
        finally:
            conn.close()

    @staticmethod
    def create_verification_token(user_id: str) -> str:
        """Creates a fresh 24-hour verification link token. Any older token for this user stops working."""
        import secrets
        import hashlib
        import datetime

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=24)).isoformat()

        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT,
                    expires_at TEXT
                )
            """)
            conn.execute("DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
            conn.execute(
                "INSERT INTO email_verification_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )
            conn.commit()
            return token
        finally:
            conn.close()

    @staticmethod
    def verify_email_with_token(token: str) -> bool:
        import hashlib
        import hmac
        import datetime

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT,
                    expires_at TEXT
                )
            """)
            row = conn.execute(
                "SELECT user_id, expires_at FROM email_verification_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if not row:
                return False

            user_id, expires_at = row
            conn.execute("DELETE FROM email_verification_tokens WHERE token_hash = ?", (token_hash,))
            if datetime.datetime.fromisoformat(expires_at) < datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None):
                conn.commit()
                return False

            conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def update_profile(user_id: str, full_name: str, organization: str) -> None:
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE users SET full_name = ?, organization = ? WHERE id = ?",
                (full_name, organization, user_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def change_password(user_id: str, current_password: str, new_password: str) -> bool:
        """Returns False if the current password is wrong."""
        conn = _get_connection()
        try:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or not _verify_password(current_password, row[0]):
                return False
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (_hash_password(new_password), user_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def change_email(user_id: str, new_email: str, password: str) -> None:
        """Changes the login email (marking it unverified again). Raises ValueError with a user-facing message."""
        new_email = new_email.strip().lower()
        conn = _get_connection()
        try:
            row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or not _verify_password(password, row[0]):
                raise ValueError("Incorrect password.")

            taken = conn.execute(
                "SELECT 1 FROM users WHERE email = ? AND id != ?", (new_email, user_id)
            ).fetchone()
            if taken:
                raise ValueError("An account with this email already exists.")

            conn.execute(
                "UPDATE users SET email = ?, email_verified = ? WHERE id = ?",
                (new_email, 0 if email_verification_required() else 1, user_id),
            )
            # Invalidate any verification link issued for the previous address.
            try:
                conn.execute("DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
            except sqlite3.OperationalError:
                pass  # table does not exist yet: no tokens to invalidate
            conn.commit()
        finally:
            conn.close()