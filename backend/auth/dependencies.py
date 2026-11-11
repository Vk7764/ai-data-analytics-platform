# backend/auth/dependencies.py
from fastapi import Header, HTTPException, Depends
import jwt

import hmac

from backend.auth.auth import decode_token
from backend.auth.user_store import UserStore


def require_auth(authorization: str = Header(None)) -> str:
    """
    FastAPI dependency that protects an endpoint: requires a valid
    'Authorization: Bearer <token>' header. Returns the user_id if valid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.replace("Bearer ", "").strip()

    try:
        payload = decode_token(token)
        user_id = payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Reject tokens of deleted accounts and tokens issued before the last password change or reset.
    current_fingerprint = UserStore.get_auth_fingerprint(user_id)
    if current_fingerprint is None or not hmac.compare_digest(current_fingerprint, str(payload.get("pwv", ""))):
        raise HTTPException(status_code=401, detail="Session is no longer valid, please log in again")

    return user_id


def require_premium(current_user: str = Depends(require_auth)) -> str:
    """
    FastAPI dependency that additionally requires the logged-in user's
    plan to be 'premium'. Use this (instead of require_auth) on any
    endpoint that should be gated behind a paid plan.
    """
    plan = UserStore.get_plan(current_user)
    if plan != "premium":
        raise HTTPException(
            status_code=403,
            detail="This feature requires a Premium plan. Please upgrade to access it.",
        )
    return current_user