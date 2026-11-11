# backend/scheduling/schedule_store.py
import sqlite3
import uuid
import datetime
import ipaddress
import socket
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

from backend.database.dataset_store import DB_PATH

MAX_SCHEDULES_PER_USER = 10

# Retry delays (minutes) after consecutive failed runs; once exhausted, the normal weekly/monthly cadence resumes.
RETRY_DELAYS_MINUTES = (15, 60, 360)


def validate_webhook_url(url: str) -> str:
    """
    Accepts only https webhook URLs whose host resolves exclusively to public addresses.
    Raises ValueError otherwise. Returns the cleaned URL.
    """
    candidate = (url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Webhook URL must be a valid https:// address.")
    if parsed.username or parsed.password:
        raise ValueError("Webhook URL must not contain embedded credentials.")

    try:
        port = parsed.port or 443
        addresses = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, ValueError, OSError):
        raise ValueError("Webhook host could not be resolved.")

    for info in addresses:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            raise ValueError("Webhook URL must point to a public internet address.")
    return candidate


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_exports (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            dataset_id TEXT,
            format TEXT,
            frequency TEXT,
            destination_type TEXT,
            destination TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_run_at TEXT,
            next_run_at TEXT
        )
    """)
    # Migration-safe additions: failure tracking columns.
    for column_definition in (
        "last_status TEXT",
        "last_error TEXT",
        "last_attempt_at TEXT",
        "consecutive_failures INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(f"ALTER TABLE scheduled_exports ADD COLUMN {column_definition}")
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


def _compute_next_run(frequency: str, from_time: datetime.datetime = None) -> str:
    base = from_time or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if frequency == "weekly":
        return (base + datetime.timedelta(days=7)).isoformat()
    if frequency == "monthly":
        return (base + datetime.timedelta(days=30)).isoformat()
    raise ValueError("frequency must be 'weekly' or 'monthly'")


class ScheduleStore:
    """Persistent store for automated report export schedules."""

    @staticmethod
    def create(user_id: str, dataset_id: str, format: str, frequency: str, destination_type: str, destination: str) -> str:
        if frequency not in ("weekly", "monthly"):
            raise ValueError("frequency must be 'weekly' or 'monthly'")
        if destination_type not in ("email", "webhook"):
            raise ValueError("destination_type must be 'email' or 'webhook'")
        if format not in ("pdf", "excel", "pptx", "json", "sql", "csv"):
            raise ValueError("format must be one of pdf, excel, pptx, json, sql, csv")

        if destination_type == "webhook":
            destination = validate_webhook_url(destination)

        cap_conn = _get_connection()
        try:
            existing_count = cap_conn.execute(
                "SELECT COUNT(*) FROM scheduled_exports WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        finally:
            cap_conn.close()
        if existing_count >= MAX_SCHEDULES_PER_USER:
            raise ValueError(f"You can have at most {MAX_SCHEDULES_PER_USER} scheduled exports. Delete one to add another.")

        schedule_id = str(uuid.uuid4())
        next_run = _compute_next_run(frequency)

        conn = _get_connection()
        try:
            conn.execute(
                """
                INSERT INTO scheduled_exports
                (id, user_id, dataset_id, format, frequency, destination_type, destination, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (schedule_id, user_id, dataset_id, format, frequency, destination_type, destination, next_run),
            )
            conn.commit()
        finally:
            conn.close()
        return schedule_id

    @staticmethod
    def list_for_user(user_id: str) -> List[Dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT id, dataset_id, format, frequency, destination_type, destination, last_run_at, next_run_at, "
                "last_status, last_error, last_attempt_at, consecutive_failures "
                "FROM scheduled_exports WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [
                {
                    "schedule_id": r[0], "dataset_id": r[1], "format": r[2], "frequency": r[3],
                    "destination_type": r[4], "destination": r[5], "last_run_at": r[6], "next_run_at": r[7],
                    "last_status": r[8], "last_error": r[9], "last_attempt_at": r[10],
                    "consecutive_failures": r[11] or 0,
                }
                for r in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def delete(schedule_id: str, user_id: str) -> bool:
        conn = _get_connection()
        try:
            cursor = conn.execute("DELETE FROM scheduled_exports WHERE id = ? AND user_id = ?", (schedule_id, user_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def delete_for_dataset(dataset_id: str, user_id: str) -> int:
        """Removes every scheduled export that targets a dataset. Returns the number of removed schedules."""
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM scheduled_exports WHERE dataset_id = ? AND user_id = ?",
                (dataset_id, user_id),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    @staticmethod
    def get(schedule_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT id, user_id, dataset_id, format, frequency, destination_type, destination FROM scheduled_exports WHERE id = ? AND user_id = ?",
                (schedule_id, user_id),
            ).fetchone()
            if not row:
                return None
            return {
                "schedule_id": row[0], "user_id": row[1], "dataset_id": row[2],
                "format": row[3], "frequency": row[4], "destination_type": row[5], "destination": row[6],
            }
        finally:
            conn.close()

    @staticmethod
    def get_due_schedules() -> List[Dict[str, Any]]:
        """Returns every schedule whose next_run_at has already passed."""
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT id, user_id, dataset_id, format, frequency, destination_type, destination FROM scheduled_exports WHERE next_run_at <= ?",
                (now,),
            ).fetchall()
            return [
                {
                    "schedule_id": r[0], "user_id": r[1], "dataset_id": r[2],
                    "format": r[3], "frequency": r[4], "destination_type": r[5], "destination": r[6],
                }
                for r in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def mark_run(schedule_id: str, frequency: str, success: bool = True, error: Optional[str] = None) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT consecutive_failures FROM scheduled_exports WHERE id = ?", (schedule_id,)
            ).fetchone()
            if row is None:
                return  # The schedule was deleted while it was running.
            failures = row[0] or 0

            if success:
                conn.execute(
                    "UPDATE scheduled_exports SET last_run_at = ?, last_attempt_at = ?, last_status = 'success', "
                    "last_error = NULL, consecutive_failures = 0, next_run_at = ? WHERE id = ?",
                    (now.isoformat(), now.isoformat(), _compute_next_run(frequency, now), schedule_id),
                )
            else:
                failures += 1
                if failures <= len(RETRY_DELAYS_MINUTES):
                    next_run = (now + datetime.timedelta(minutes=RETRY_DELAYS_MINUTES[failures - 1])).isoformat()
                else:
                    # Retries exhausted: resume the normal cadence and start a fresh retry cycle next time.
                    next_run = _compute_next_run(frequency, now)
                    failures = 0
                # last_run_at is deliberately left unchanged: it records the last SUCCESSFUL delivery only.
                conn.execute(
                    "UPDATE scheduled_exports SET last_attempt_at = ?, last_status = 'failed', last_error = ?, "
                    "consecutive_failures = ?, next_run_at = ? WHERE id = ?",
                    (now.isoformat(), (error or "Delivery failed.")[:300], failures, next_run, schedule_id),
                )
            conn.commit()
        finally:
            conn.close()