# backend/main.py
from dotenv import load_dotenv
load_dotenv()

import os
import hmac
import asyncio
import re
import time
import uuid
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.routes import router
from backend.database.dataset_store import DatasetLimitExceeded
from backend.auth.auth import create_token
from backend.auth.user_store import UserStore, is_valid_email
from backend.auth.dependencies import require_auth
from backend.auth.verification import send_verification_email, email_failure_message
from backend.scheduling.runner import scheduler_supervisor
from backend.utils.email_sender import send_email, get_last_error, email_verification_required
from backend.utils.rate_limiter import rate_limit, login_limiter

logger = logging.getLogger("app")

# Error monitoring (optional). Create a free project at https://sentry.io,
# put SENTRY_DSN in .env, and unhandled errors get reported there automatically.
try:
    import sentry_sdk
    _SENTRY_DSN = (os.environ.get("SENTRY_DSN") or "").strip()
    if _SENTRY_DSN:
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            traces_sample_rate=0.0,
        )
except ImportError:
    pass  # sentry-sdk not installed: monitoring stays off, app runs normally.

# Write errors to a rotating log file as well as the console, so problems
# stay traceable after the terminal is closed.
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_file_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "app.log"),
    maxBytes=5_000_000,
    backupCount=3,
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_file_handler)
logger.setLevel(logging.INFO)

_IS_PRODUCTION = (os.environ.get("ENV") or "").strip().lower() == "production"
if _IS_PRODUCTION and os.environ.get("ALLOW_UNSAFE_LOCAL_EXEC") == "1":
    raise RuntimeError(
        "ALLOW_UNSAFE_LOCAL_EXEC=1 is not allowed when ENV=production. Remove it from the environment."
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Starts the scheduled-exports supervisor before the application accepts requests, and stops it after
    requests have finished. The supervisor releases the scheduler lease in its own shutdown path.
    """
    scheduler_task = asyncio.create_task(scheduler_supervisor())
    app.state.scheduler_task = scheduler_task
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="AI Data Analytics Platform", lifespan=lifespan)

# Which origins may call this API. Set APP_CORS_ORIGINS (comma-separated) to
# the real frontend URL(s) when deployed.
_cors_origins_env = os.environ.get("APP_CORS_ORIGINS", "").strip()
if _cors_origins_env:
    allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    if _IS_PRODUCTION:
        raise RuntimeError(
            "APP_CORS_ORIGINS must be set (comma-separated frontend URL(s)) when ENV=production."
        )
    allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def _safe_path(path: str) -> str:
    """Normalized, length-limited path. Share tokens are masked so they never reach the logs."""
    normalized = path or ""
    normalized = re.sub(r"^(?:/api)?/shared/[^/]+", "/shared/:token", normalized)
    return normalized[:200]


def _redact_text(text: str, limit: int = 200) -> str:
    """Length-limited text with newlines, emails, bearer tokens, and share tokens masked."""
    masked = text or ""
    masked = re.sub(r"[\r\n\t]+", " ", masked)
    masked = re.sub(r"/(?:api/)?shared/[^/\s\"']+", "/shared/:token", masked)
    masked = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", masked)
    masked = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", masked, flags=re.IGNORECASE)
    return masked[:limit]


@app.middleware("http")
async def request_context_and_access_log(request: Request, call_next):
    """Assigns a request id to every request and writes one concise access line per completed request."""
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else str(uuid.uuid4())
    request.state.request_id = request_id
    path = _safe_path(request.url.path)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            f"request_id={request_id} method={request.method} path={path} "
            f"status_code=500 duration_ms={duration_ms}"
        )
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        f"request_id={request_id} method={request.method} path={path} "
        f"status_code={response.status_code} duration_ms={duration_ms}"
    )
    return response


@app.middleware("http")
async def disable_caching(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    # Conservative security headers. CSP and HSTS are intentionally omitted (see B-03a scope).
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    )

    return response


@app.exception_handler(DatasetLimitExceeded)
async def dataset_limit_handler(request: Request, exc: DatasetLimitExceeded):
    """Dataset-count and storage limits are user-facing errors, not server faults."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Hides raw stack traces from users. The server log keeps a structured record with the request id,
    method, normalized path, exception type and a redacted, length-limited message. Bodies, headers,
    SQL text, prompts and row values are never logged.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger.error(
        f"request_id={request_id} method={request.method} path={_safe_path(request.url.path)} "
        f"error_type={type(exc).__name__} error_message={_redact_text(str(exc))}"
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
        headers={"X-Request-ID": request_id},
    )


# ---------- Auth ----------

class SignupRequest(BaseModel):
    email: str
    password: str
    accepted_terms: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(request: SignupRequest, _rate_limit=Depends(rate_limit(login_limiter))):
    """Creates an account, emails a verification link, and logs the user in immediately."""
    if not is_valid_email(request.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not request.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the Terms of Service and Privacy Policy to sign up.")

    try:
        user_id = UserStore.create_user(request.email, request.password, terms_accepted=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # A failed email must not block signup: the user can use "Resend" later.
    email_sent = send_verification_email(user_id, request.email) if email_verification_required() else False

    token = create_token(user_id)
    return {"access_token": token, "token_type": "bearer", "verification_email_sent": email_sent}


@app.post("/api/auth/login")
def login(request: LoginRequest, _rate_limit=Depends(rate_limit(login_limiter))):
    user_id = UserStore.verify_credentials(request.email, request.password)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user_id)
    return {"access_token": token, "token_type": "bearer"}


class ForgotPasswordRequest(BaseModel):
    email: str


@app.post("/api/auth/forgot-password")
def forgot_password(request: ForgotPasswordRequest, _rate_limit=Depends(rate_limit(login_limiter))):
    """
    Always returns the same generic message whether or not the email exists,
    so this endpoint can't be used to discover which emails are registered.
    """
    token = UserStore.create_reset_token(request.email)

    if token:
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
        reset_link = f"{frontend_url}/reset-password?token={token}"
        sent = send_email(
            to_email=request.email.strip().lower(),
            subject="Reset your password",
            body_html=f"""
                <p>Someone requested a password reset for your account.</p>
                <p><a href="{reset_link}">Click here to reset your password</a></p>
                <p>This link expires in 1 hour. If you didn't request this, you can ignore this email.</p>
            """,
        )
        if not sent:
            # The response to the user must stay generic (no account
            # enumeration), but the failure must be visible in the server log.
            logger.error("Password reset email could not be sent. Reason: %s", get_last_error())

    return {"message": "If an account with that email exists, a reset link has been sent."}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@app.post("/api/auth/reset-password")
def reset_password(request: ResetPasswordRequest, _rate_limit=Depends(rate_limit(login_limiter))):
    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    success = UserStore.reset_password_with_token(request.token, request.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    return {"message": "Password reset successfully. You can now log in."}


class VerifyEmailRequest(BaseModel):
    token: str


@app.post("/api/auth/verify-email")
def verify_email(request: VerifyEmailRequest, _rate_limit=Depends(rate_limit(login_limiter))):
    """Confirms an email address using the token from the emailed link."""
    if not UserStore.verify_email_with_token(request.token):
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    return {"message": "Email verified. You can now use all AI features."}


@app.post("/api/auth/resend-verification")
def resend_verification(current_user: str = Depends(require_auth), _rate_limit=Depends(rate_limit(login_limiter))):
    """Sends a fresh verification link to the logged-in user's own email address."""
    user = UserStore.get_user(current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user["email_verified"]:
        return {"message": "Your email is already verified."}

    if not send_verification_email(current_user, user["email"]):
        raise HTTPException(status_code=503, detail=email_failure_message())
    return {"message": "Verification email sent. Please check your inbox (and spam folder)."}


# ---------- Current user + admin ----------

@app.get("/api/me")
def get_current_user_info(current_user: str = Depends(require_auth)):
    """The logged-in user's basic info, including their plan."""
    user = UserStore.get_user(current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


class AdminUpgradeRequest(BaseModel):
    email: str
    plan: str  # "free" or "premium"


ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY", "")


@app.post("/api/admin/set-plan")
def admin_set_plan(
    request: AdminUpgradeRequest,
    x_admin_key: str = Header(None),
    _rate_limit=Depends(rate_limit(login_limiter)),
):
    """
    Manual tool for switching a user between plans until real payments are
    wired up. Protected by a separate admin secret (ADMIN_SECRET_KEY in .env).
    """
    if not ADMIN_SECRET_KEY or not hmac.compare_digest(
        (x_admin_key or "").encode("utf-8"), ADMIN_SECRET_KEY.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Invalid admin key")

    try:
        success = UserStore.set_plan(request.email, request.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail="No user found with that email")

    return {"message": f"User {request.email} is now on the '{request.plan}' plan."}


# ---------- Background jobs + health ----------

# Scheduler startup and shutdown are handled by the lifespan context manager above.


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "AI Data Analytics Platform is running"}