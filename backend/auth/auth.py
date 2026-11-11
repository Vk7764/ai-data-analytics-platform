# backend/auth/auth.py
import os
import secrets
import jwt
import datetime

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

from backend.database.dataset_store import DB_PATH

# Legacy location (inside the code directory, lost on redeploy). Only read once to migrate an existing key.
_LEGACY_SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret_key")
# Persistent location: next to the database, so the key lives on the same volume as the data.
# Override with APP_SECRET_KEY_FILE (for example a mounted secret path).
_SECRET_KEY_FILE = (os.environ.get("APP_SECRET_KEY_FILE") or "").strip() or os.path.join(
    os.path.dirname(DB_PATH), ".secret_key"
)


def _load_or_create_secret_key() -> str:
    import hashlib
    env_key = (os.environ.get("APP_SECRET_KEY") or "").strip()
    if env_key:
        if len(env_key.encode("utf-8")) < 32:
            return hashlib.sha256(env_key.encode("utf-8")).hexdigest()
        return env_key
    import time

    # In production, require an explicit secret so every container and worker signs with the same key.
    if (os.environ.get("REQUIRE_APP_SECRET_KEY") or "").strip() == "1":
        raise RuntimeError(
            "APP_SECRET_KEY is required (REQUIRE_APP_SECRET_KEY=1) but is not set. "
            "Set the same APP_SECRET_KEY for every container and worker."
        )

    def _read_key(path: str) -> str:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except OSError:
            return ""

    existing = _read_key(_SECRET_KEY_FILE)
    if existing:
        return existing

    # Reuse a key from the legacy location when present, so existing sessions survive the move.
    new_key = _read_key(_LEGACY_SECRET_KEY_FILE) or secrets.token_hex(32)

    try:
        os.makedirs(os.path.dirname(_SECRET_KEY_FILE) or ".", exist_ok=True)
        # O_EXCL makes creation atomic: concurrent workers cannot overwrite each other's key.
        fd = os.open(_SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(new_key)
        return new_key
    except FileExistsError:
        # Another worker created the file first: wait for its content and use that key.
        for _ in range(30):
            existing = _read_key(_SECRET_KEY_FILE)
            if existing:
                return existing
            time.sleep(0.1)
        raise RuntimeError(f"The signing secret file {_SECRET_KEY_FILE} exists but is empty.")
    except OSError as e:
        raise RuntimeError(
            f"Could not persist the signing secret at {_SECRET_KEY_FILE}: {e}. Set APP_SECRET_KEY instead."
        )


SECRET_KEY = _load_or_create_secret_key()


def create_token(user_id: str) -> str:
    """Creates a JWT access token identifying this user, bound to the current password state."""
    from backend.auth.user_store import UserStore  # Imported lazily to avoid a circular import.

    payload = {
        "sub": user_id,
        "pwv": UserStore.get_auth_fingerprint(user_id) or "",
        "exp": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    """Decodes and validates a JWT token. Returns the user_id, or raises an exception if invalid."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload["sub"]


def decode_token(token: str) -> dict:
    """Decodes and validates a JWT token. Returns the full payload, or raises an exception if invalid."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])