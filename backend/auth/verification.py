# backend/auth/verification.py
import os

from backend.auth.user_store import UserStore
from backend.utils.email_sender import send_email, get_last_error


def send_verification_email(user_id: str, email: str) -> bool:
    """Creates a fresh verification link and emails it. Returns True if the email was sent."""
    token = UserStore.create_verification_token(user_id)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    link = f"{frontend_url}/verify-email?token={token}"
    return send_email(
        to_email=email.strip().lower(),
        subject="Verify your email address",
        body_html=f"""
            <p>Welcome! Please confirm your email address to unlock the AI features.</p>
            <p><a href="{link}">Verify my email</a></p>
            <p>This link expires in 24 hours. If you didn't create an account, you can ignore this email.</p>
        """,
    )


def email_failure_message() -> str:
    """
    The message shown to the user when an email can't be sent. The technical
    reason is added only while SHOW_EMAIL_ERRORS=1 is set in .env (for
    testing). Remove that line before launch so customers never see
    server-configuration details.
    """
    base = "Could not send the email right now. Please try again later."
    if os.environ.get("SHOW_EMAIL_ERRORS") == "1":
        reason = get_last_error()
        if reason:
            return f"{base} ({reason})"
    return base