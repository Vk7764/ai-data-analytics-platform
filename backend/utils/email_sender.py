# backend/utils/email_sender.py
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger("app")

_last_error = ""


def get_last_error() -> str:
    """A short, human-readable reason for the most recent failed send ('' if the last send worked)."""
    return _last_error


def _fail(reason: str) -> bool:
    global _last_error
    _last_error = reason
    print(f"[email_sender] FAILED: {reason}", flush=True)
    logger.error(f"Email send failed: {reason}")
    return False


def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    attachment_bytes: bytes = None,
    attachment_filename: str = None,
) -> bool:
    """
    Sends an email through Gmail's SMTP server using an App Password.
    Returns True on success. On failure it returns False and records a
    readable reason (see get_last_error) instead of raising, so a broken
    email never crashes the request that triggered it.
    """
    global _last_error
    _last_error = ""

    # Read at send time rather than import time, so this never depends on
    # import order or on when .env was loaded.
    address = (os.environ.get("GMAIL_ADDRESS") or "").strip()
    app_password = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")

    if not address or not app_password:
        return _fail("Email sending is not configured on the server: GMAIL_ADDRESS or GMAIL_APP_PASSWORD is missing in .env.")

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