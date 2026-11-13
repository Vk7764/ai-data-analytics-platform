# backend/scheduling/runner.py
import asyncio
import atexit
import datetime
import os
import sqlite3
import time
import uuid
import requests

from backend.scheduling.schedule_store import ScheduleStore, validate_webhook_url
from backend.database.dataset_store import DatasetStore, DB_PATH
from backend.reports.generator import ReportGenerator, cleanup_old_reports
from backend.agents.insight_agent import InsightAgent
from backend.agents.report_agent import ReportAgent
from backend.analytics.anomaly import AnomalyDetector
from backend.analytics.forecasting import Forecaster
from backend.data.profiler import DataProfiler
from backend.visualization.charts import ChartEngine
from backend.visualization.chart_image import ChartImageExporter
from backend.auth.user_store import UserStore
from backend.utils.email_sender import send_email, get_last_error

from backend.utils.ai_gate import cached_ai_call, QuotaExceeded

CHECK_INTERVAL_SECONDS = 600  # check every 10 minutes

EXTENSIONS = {"pdf": "pdf", "excel": "xlsx", "pptx": "pptx", "json": "json", "sql": "sql", "csv": "csv"}
MEDIA_TYPES = {
    "csv": "text/csv",
    "pdf": "application/pdf",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "json": "application/json",
    "sql": "application/sql",
}


def _ai_summary(dataset_id: str, user_id: str, df) -> str | None:
    """AI summary via the same cache and daily limit as the app, so scheduled reports can't bypass per-user limits."""
    try:
        return cached_ai_call(
            dataset_id, user_id, "insight", {"q": None}, df,
            lambda: InsightAgent.generate_insight(df),
        )["insight"]
    except (QuotaExceeded, RuntimeError):
        return None


def _report_extras(dataset_id: str, user_id: str, df) -> dict:
    """Builds the same optional report sections (and premium branding) as the interactive download."""
    extras = {
        "executive_summary": _ai_summary(dataset_id, user_id, df),
        "display_name": DatasetStore.get_filename(dataset_id, user_id) or dataset_id,
    }

    profile_info = DataProfiler.profile(df)
    date_cols = profile_info["date_columns"]
    metric_cols = [c for c in profile_info["numeric_columns"] if not ChartEngine.is_identifier_name(c)]
    if date_cols and metric_cols:
        try:
            fc = Forecaster.forecast(df, date_cols[0], metric_cols[0], periods=3)
            extras["forecast_summary"] = (
                f"Trend for '{metric_cols[0]}' over '{date_cols[0]}' is {fc['trend_direction']}. "
                "Next forecasted values: "
                + ", ".join(
                    f"{p['date']}: {p['predicted_value']} (range {p['lower_bound']} to {p['upper_bound']})"
                    for p in fc["forecast"]
                )
            )
        except Exception:
            pass

    try:
        extras["recommendations"] = cached_ai_call(
            dataset_id, user_id, "report_recommendations", {}, df,
            lambda: ReportAgent.generate_recommendations(df),
        )["recommendations"]
    except (QuotaExceeded, RuntimeError):
        pass

    try:
        anomalies = AnomalyDetector.detect_all(df)
        if anomalies["numeric_outliers"] or anomalies["category_anomalies"]:
            extras["anomaly_summary"] = cached_ai_call(
                dataset_id, user_id, "anomaly_explanation", {}, df,
                lambda: InsightAgent.explain_anomalies(anomalies),
            )["explanation"]
    except (QuotaExceeded, RuntimeError):
        pass

    if UserStore.get_plan(user_id) == "premium":
        try:
            extras["chart_image_bytes"] = ChartImageExporter.render(df)
        except Exception:
            pass
        branding = UserStore.get_branding(user_id)
        extras["logo_bytes"] = branding["logo_bytes"]
        extras["accent_color"] = branding["accent_color"]

    return extras


def _generate_report_bytes(dataset_id: str, user_id: str, fmt: str) -> tuple[bytes, str]:
    """Generates a report file and returns (bytes, filename)."""
    df = DatasetStore.get(dataset_id, user_id)
    if df is None:
        raise ValueError("Dataset no longer exists")

    if fmt == "excel":
        path = ReportGenerator.generate_excel(df, dataset_id)
    elif fmt == "json":
        path = ReportGenerator.generate_json(df, dataset_id)
    elif fmt == "sql":
        path = ReportGenerator.generate_sql_script(df, dataset_id)
    elif fmt == "csv":
        path = ReportGenerator.generate_csv(df, dataset_id)
    elif fmt == "pptx":
        path = ReportGenerator.generate_pptx(df, dataset_id, **_report_extras(dataset_id, user_id, df))
    else:  # pdf
        path = ReportGenerator.generate_pdf(df, dataset_id, **_report_extras(dataset_id, user_id, df))

    try:
        with open(path, "rb") as f:
            content = f.read()
    finally:
        # The bytes are now in memory; sweep expired artifacts on success and on failure alike.
        cleanup_old_reports()
    filename = f"report.{EXTENSIONS[fmt]}"
    return content, filename

def failure_reason(schedule: dict) -> str:
    """A short, user-visible reason for a failed run."""
    if schedule.get("destination_type") == "email":
        return (get_last_error() or "Report generation or email delivery failed.")[:300]
    return "Report generation or webhook delivery failed. Check the dataset and the webhook address."


# Failure notifications are throttled per schedule, so a broken schedule
# cannot spam the owner's inbox on every retry (checks run every 10 minutes).
_FAILURE_NOTIFY_MIN_GAP_SECONDS = 24 * 3600
_last_failure_notified_at: dict = {}


def _notify_owner_of_failure(schedule: dict, reason: str) -> None:
    """Emails the schedule owner (if verified) that an automated export failed. Throttled to once per day per schedule."""
    try:
        schedule_id = str(schedule.get("schedule_id") or "")
        now = time.time()
        last = _last_failure_notified_at.get(schedule_id, 0)
        if now - last < _FAILURE_NOTIFY_MIN_GAP_SECONDS:
            return
        owner = UserStore.get_user(schedule.get("user_id"))
        if not owner or not owner.get("email_verified"):
            return
        safe_reason = str(reason or "unknown error").replace("<", "&lt;").replace(">", "&gt;")
        sent = send_email(
            to_email=owner["email"],
            subject="Your scheduled export failed",
            body_html=f"""
                <p>An automated scheduled export of dataset <b>{schedule.get('dataset_id')}</b> failed.</p>
                <p>Reason: {safe_reason}</p>
                <p>The schedule will keep retrying automatically. Open the Reports section to check or fix the schedule.</p>
            """,
        )
        if sent:
            _last_failure_notified_at[schedule_id] = now
    except Exception as e:
        print(f"[Scheduler] Failure notification could not be sent: {e}")


def execute_schedule(schedule: dict) -> bool:
    """Runs a single schedule immediately: generates the report and delivers it. Returns True on success."""
    try:
        content, filename = _generate_report_bytes(schedule["dataset_id"], schedule["user_id"], schedule["format"])
    except Exception as e:
        print(f"[Scheduler] Failed to generate report for schedule {schedule['schedule_id']}: {e}")
        cleanup_old_reports()  # Remove partial or expired files left behind by the failed run.
        return False

    if schedule["destination_type"] == "email":
        owner = UserStore.get_user(schedule["user_id"])
        if (
            not owner
            or not owner["email_verified"]
            or owner["email"].strip().lower() != str(schedule["destination"]).strip().lower()
        ):
            print(f"[Scheduler] Email destination for schedule {schedule['schedule_id']} no longer matches the verified account email.")
            return False
        sent = send_email(
            to_email=schedule["destination"],
            subject="Your scheduled data report",
            body_html="<p>Your automated report is attached.</p>",
            attachment_bytes=content,
            attachment_filename=filename,
        )
        return sent

    if schedule["destination_type"] == "webhook":
        try:
            safe_url = validate_webhook_url(schedule["destination"])
            resp = requests.post(
                safe_url,
                files={"file": (filename, content, MEDIA_TYPES.get(schedule["format"], "application/octet-stream"))},
                timeout=20,
                allow_redirects=False,
            )
            return resp.ok
        except Exception as e:
            print(f"[Scheduler] Webhook delivery failed for schedule {schedule['schedule_id']}: {e}")
            return False

    return False


# ---------- Single-instance scheduler lease (multi-worker safety) ----------

LEASE_NAME = "scheduler"
LEASE_TTL_SECONDS = 120    # a crashed holder loses the lease after this long
LEASE_RENEW_SECONDS = 30   # the holder renews well inside the TTL
_LEASE_OWNER = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _lease_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit: transactions are explicit
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scheduler_lease (name TEXT PRIMARY KEY, owner TEXT, expires_at TEXT)"
    )
    return conn


def acquire_or_renew_lease() -> bool:
    """
    Atomically takes the scheduler lease when it is free, expired or already ours, and extends it.
    Returns True only if this process holds a fresh lease afterwards. Never raises.
    """
    conn = None
    try:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        new_expiry = (now + datetime.timedelta(seconds=LEASE_TTL_SECONDS)).isoformat()
        conn = _lease_connection()
        conn.execute("BEGIN IMMEDIATE")  # takes the write lock, so two workers cannot both win
        row = conn.execute(
            "SELECT owner, expires_at FROM scheduler_lease WHERE name = ?", (LEASE_NAME,)
        ).fetchone()
        if row is None:
            may_hold = True
        else:
            current_owner, current_expiry = row
            try:
                expired = datetime.datetime.fromisoformat(current_expiry) < now
            except (TypeError, ValueError):
                expired = True
            may_hold = current_owner == _LEASE_OWNER or expired
        if may_hold:
            conn.execute(
                "INSERT OR REPLACE INTO scheduler_lease (name, owner, expires_at) VALUES (?, ?, ?)",
                (LEASE_NAME, _LEASE_OWNER, new_expiry),
            )
        conn.execute("COMMIT")
        return may_hold
    except Exception as e:
        print(f"[Scheduler] Lease check failed: {e}")
        try:
            if conn is not None:
                conn.execute("ROLLBACK")
        except Exception:
            pass
        return False
    finally:
        if conn is not None:
            conn.close()


def release_lease() -> None:
    """Clears the lease if this process owns it, so another worker can take over immediately."""
    conn = None
    try:
        conn = _lease_connection()
        conn.execute(
            "DELETE FROM scheduler_lease WHERE name = ? AND owner = ?", (LEASE_NAME, _LEASE_OWNER)
        )
    except Exception as e:
        print(f"[Scheduler] Lease release failed: {e}")
    finally:
        if conn is not None:
            conn.close()


async def scheduler_supervisor():
    """
    Runs the scheduler loop only in the worker that holds the lease. The lease is renewed periodically;
    if it is lost the loop is stopped, and it is released on shutdown/process exit.
    """
    atexit.register(release_lease)
    worker = None
    try:
        while True:
            has_lease = await asyncio.to_thread(acquire_or_renew_lease)
            if has_lease:
                if worker is None:
                    print("[Scheduler] Lease acquired: starting scheduler loop in this worker.")
                    worker = asyncio.create_task(scheduler_loop())
                elif worker.done():
                    if not worker.cancelled():
                        exc = worker.exception()
                        if exc is not None:
                            print(f"[Scheduler] Scheduler loop stopped with error: {exc}")
                    worker = None
            elif worker is not None:
                print("[Scheduler] Lease lost: stopping scheduler loop in this worker.")
                worker.cancel()
                worker = None
            await asyncio.sleep(LEASE_RENEW_SECONDS)
    finally:
        if worker is not None:
            worker.cancel()
        release_lease()


async def scheduler_loop():
    """
    Runs forever in the background: every CHECK_INTERVAL_SECONDS, finds any
    schedule whose next_run_at has passed, executes it, and reschedules it.
    State lives entirely in SQLite, so this is safe across server restarts
    — a missed check just gets picked up on the next loop iteration.
    """
    while True:
        try:
            await asyncio.to_thread(cleanup_old_reports)
            due = await asyncio.to_thread(ScheduleStore.get_due_schedules)
            for schedule in due:
                print(f"[Scheduler] Running due schedule {schedule['schedule_id']}")
                # Blocking work (report generation, AI, SMTP, webhooks) runs off the event loop.
                success = await asyncio.to_thread(execute_schedule, schedule)
                if success:
                    await asyncio.to_thread(
                        ScheduleStore.mark_run,
                        schedule["schedule_id"],
                        schedule["frequency"],
                        True,
                        None,
                    )
                else:
                    reason = failure_reason(schedule)
                    await asyncio.to_thread(
                        ScheduleStore.mark_run,
                        schedule["schedule_id"],
                        schedule["frequency"],
                        False,
                        reason,
                    )
                    await asyncio.to_thread(_notify_owner_of_failure, schedule, reason)
                print(f"[Scheduler] Schedule {schedule['schedule_id']} {'succeeded' if success else 'failed'}")
        except Exception as e:
            print(f"[Scheduler] Loop error: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)