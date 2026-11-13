# backend/utils/email_sender.py
import base64
import os
import smtplib
import logging
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger("app")

_last_error = ""

RESEND_API_URL = "https://api.resend.com/emails"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
_HTTP_TIMEOUT_SECONDS = 20


def email_verification_required() -> bool:
    """
    Email verification is required by default. Set REQUIRE_EMAIL_VERIFICATION=0 (or false/no/off)
    on hosts where outbound email cannot work, so users are not locked out of AI features.
    """
    value = (os.environ.get("REQUIRE_EMAIL_VERIFICATION") or "1").strip().lower()
    return value not in ("0", "false", "no", "off")


def get_last_error() -> str:
    """A short, human-readable reason for the most recent failed send ('' if the last send worked)."""
    return _last_error


def _fail(reason: str) -> bool:
    global _last_error
    _last_error = reason
    print(f"[email_sender] FAILED: {reason}", flush=True)
    logger.error(f"Email send failed: {reason}")
    return False


def _send_via_resend(api_key, sender, to_email, subject, body_html, attachment_bytes, attachment_filename):
    """HTTPS email API (port 443). Returns (ok, reason)."""
    payload = {
        "from": sender or "onboarding@resend.dev",
        "to": [to_email],
        "subject": subject,
        "html": body_html,
    }
    if attachment_bytes and attachment_filename:
        payload["attachments"] = [
            {"filename": attachment_filename, "content": base64.b64encode(attachment_bytes).decode("ascii")}
        ]
    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 201, 202):
            return True, ""
        return False, f"Resend rejected the email (HTTP {resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        return False, f"Could not reach the Resend API: {e}"


def _send_via_brevo(api_key, sender, to_email, subject, body_html, attachment_bytes, attachment_filename):
    """HTTPS email API (port 443). Returns (ok, reason)."""
    if not sender:
        return False, "Brevo needs a verified sender address: set EMAIL_FROM (or GMAIL_ADDRESS) in .env."
    payload = {
        "sender": {"email": sender, "name": (os.environ.get("EMAIL_FROM_NAME") or "AI Data Analytics").strip()},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": body_html,
    }
    if attachment_bytes and attachment_filename:
        payload["attachment"] = [
            {"name": attachment_filename, "content": base64.b64encode(attachment_bytes).decode("ascii")}
        ]
    try:
        resp = requests.post(
            BREVO_API_URL,
            headers={"api-key": api_key, "Content-Type": "application/json", "accept": "application/json"},
            json=payload,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 201, 202):
            return True, ""
        return False, f"Brevo rejected the email (HTTP {resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        return False, f"Could not reach the Brevo API: {e}"


def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    attachment_bytes: bytes = None,
    attachment_filename: str = None,
) -> bool:
    """
    Sends an email. Order: Resend HTTPS API, then Brevo HTTPS API (both work where outbound SMTP
    port 587 is blocked), then Gmail SMTP with an App Password. Returns True on success. On failure
    it returns False and records a readable reason (see get_last_error) instead of raising, so a
    broken email never crashes the request that triggered it.
    """
    global _last_error
    _last_error = ""

    # Read at send time rather than import time, so this never depends on
    # import order or on when .env was loaded.
    address = (os.environ.get("GMAIL_ADDRESS") or "").strip()
    app_password = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
    email_from = (os.environ.get("EMAIL_FROM") or "").strip()
    resend_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    brevo_key = (os.environ.get("BREVO_API_KEY") or "").strip()

    api_error = ""

    if resend_key:
        ok, reason = _send_via_resend(
            resend_key, email_from, to_email, subject, body_html, attachment_bytes, attachment_filename
        )
        if ok:
            print(f"[email_sender] Sent '{subject}' to {to_email} via Resend", flush=True)
            return True
        api_error = reason
        print(f"[email_sender] Resend failed: {reason}", flush=True)

    if brevo_key:
        ok, reason = _send_via_brevo(
            brevo_key, email_from or address, to_email, subject, body_html, attachment_bytes, attachment_filename
        )
        if ok:
            print(f"[email_sender] Sent '{subject}' to {to_email} via Brevo", flush=True)
            return True
        api_error = reason
        print(f"[email_sender] Brevo failed: {reason}", flush=True)

    if not address or not app_password:
        return _fail(
            api_error
            or "Email sending is not configured on the server: set RESEND_API_KEY, BREVO_API_KEY, "
            "or GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env."
        )

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to_email

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body_html, "html"))
    msg.attach(body_part)

    if attachment_bytes and attachment_filename:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={attachment_filename}")
        msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(address, app_password)
            server.sendmail(address, to_email, msg.as_string())
        print(f"[email_sender] Sent '{subject}' to {to_email}", flush=True)
        return True
    except smtplib.SMTPAuthenticationError:
        return _fail("Gmail rejected the login. Check GMAIL_ADDRESS and the 16-character App Password in .env (it must be an App Password, not the normal Gmail password).")
    except smtplib.SMTPRecipientsRefused:
        return _fail(f"The address {to_email} was rejected by the mail server.")
    except smtplib.SMTPException as e:
        return _fail(f"Gmail returned an error: {e}")
    except (TimeoutError, OSError) as e:
        return _fail(f"Could not reach Gmail's mail server (network, firewall, or antivirus may be blocking port 587): {e}")
    except Exception as e:
        return _fail(f"Unexpected email error: {e}")