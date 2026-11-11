# backend/database/dataset_store.py
import sqlite3
import uuid
import os
import threading
from functools import wraps
import pandas as pd
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "app_data.db")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


SQLITE_BUSY_TIMEOUT_SECONDS = 30
MAX_DATASETS_PER_USER = _env_int("MAX_DATASETS_PER_USER", 50)
MAX_DATASET_CELLS = _env_int("MAX_DATASET_CELLS", 50_000_000)  # rows x columns of a single dataset
MAX_USER_CELLS = _env_int("MAX_USER_CELLS", 100_000_000)  # rows x columns across all of a user's datasets


class DatasetLimitExceeded(Exception):
    """Raised when a new dataset would exceed the per-user dataset-count or storage limits."""
    status_code = 413


# SQLite allows a single writer at a time: dataset writes are serialized so concurrent
# uploads, edits and undo operations queue up instead of failing with "database is locked".
_WRITE_LOCK = threading.RLock()


def _serialized(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _WRITE_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _dtype_table_name(snapshot_table: str) -> str:
    """Companion table holding the original pandas dtypes of one undo snapshot (dropped together with it)."""
    return f"{snapshot_table}__dtypes"


def _save_snapshot_dtypes(conn: sqlite3.Connection, snapshot_table: str, df: pd.DataFrame) -> None:
    dtype_table = _dtype_table_name(snapshot_table)
    conn.execute(f'DROP TABLE IF EXISTS "{dtype_table}"')
    conn.execute(f'CREATE TABLE "{dtype_table}" (position INTEGER, column_name TEXT, dtype TEXT)')
    conn.executemany(
        f'INSERT INTO "{dtype_table}" (position, column_name, dtype) VALUES (?, ?, ?)',
        [(i, str(col), str(dtype)) for i, (col, dtype) in enumerate(zip(df.columns, df.dtypes))],
    )


def _restore_snapshot_dtypes(conn: sqlite3.Connection, snapshot_table: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Re-applies the dtypes recorded at snapshot time. Best effort: a column that cannot be converted
    safely keeps the type SQLite returned. Legacy snapshots without dtype info are returned unchanged.
    """
    dtype_table = _dtype_table_name(snapshot_table)
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (dtype_table,)
    ).fetchone()
    if not exists:
        return df

    rows = conn.execute(f'SELECT position, dtype FROM "{dtype_table}" ORDER BY position ASC').fetchall()
    for position, dtype_name in rows:
        if position >= df.shape[1]:
            continue
        current = df.iloc[:, position]
        if str(current.dtype) == dtype_name:
            continue
        try:
            if dtype_name.startswith("datetime64"):
                converted = pd.to_datetime(current, errors="coerce")
            elif dtype_name == "bool" and current.isna().any():
                continue  # Missing values cannot be represented in a plain bool column.
            else:
                converted = current.astype(dtype_name)

            try:
                df.isetitem(position, converted)
            except AttributeError:
                df.iloc[:, position] = converted
        except Exception:
            continue
    return df


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
    try:
        # WAL lets readers proceed while a write is in progress.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        pass  # Keep the default journal mode if WAL is unsupported on this filesystem.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS datasets_meta (
            id TEXT PRIMARY KEY,
            filename TEXT,
            table_name TEXT,
            user_id TEXT,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration safety: if this table already existed from before multi-user
    # support was added, add the new column instead of crashing.
    try:
        conn.execute("ALTER TABLE datasets_meta ADD COLUMN user_id TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dataset_snapshot_meta (
            dataset_id TEXT PRIMARY KEY,
            action_label TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dataset_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT,
            action TEXT,
            column_name TEXT,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dataset_notes (
            dataset_id TEXT PRIMARY KEY,
            note TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dataset_undo_stack (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT,
            snapshot_table TEXT,
            action_label TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn


UNDO_STACK_LIMIT = 5


class DatasetStore:
    """
    Persistent dataset storage backed by a local SQLite file. Every dataset
    is scoped to the user_id of whoever uploaded it — get/update/delete/list
    all filter by user_id, so one user's data is never visible to, or
    editable by, another user.
    """

    @staticmethod
    @_serialized
    def create(df: pd.DataFrame, filename: str, user_id: str) -> str:
        dataset_id = str(uuid.uuid4())
        table_name = f"dataset_{dataset_id.replace('-', '_')}"

        new_cells = int(df.shape[0]) * int(df.shape[1])
        if new_cells > MAX_DATASET_CELLS:
            raise DatasetLimitExceeded(
                f"This dataset is too large ({new_cells:,} cells). The maximum is {MAX_DATASET_CELLS:,} cells (rows x columns)."
            )

        conn = _get_connection()
        try:
            DatasetStore._enforce_user_limits(conn, user_id, new_cells)
            df.to_sql(table_name, conn, index=False, if_exists="replace", chunksize=10000)
            conn.execute(
                "INSERT INTO datasets_meta (id, filename, table_name, user_id) VALUES (?, ?, ?, ?)",
                (dataset_id, filename, table_name, user_id),
            )
            conn.commit()
        finally:
            conn.close()

        return dataset_id

    @staticmethod
    def _enforce_user_limits(conn: sqlite3.Connection, user_id: str, new_cells: int) -> None:
        """Raises DatasetLimitExceeded if adding a dataset of new_cells would pass the user's limits."""
        tables = conn.execute(
            "SELECT table_name FROM datasets_meta WHERE user_id = ?", (user_id,)
        ).fetchall()
        if len(tables) >= MAX_DATASETS_PER_USER:
            raise DatasetLimitExceeded(
                f"You can store at most {MAX_DATASETS_PER_USER} datasets. Delete one to add another."
            )

        total_cells = new_cells
        for (table,) in tables:
            try:
                row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                column_count = len(conn.execute(f'PRAGMA table_info("{table}")').fetchall())
            except sqlite3.OperationalError:
                continue  # The table is missing; it does not count toward storage.
            total_cells += row_count * column_count

        if total_cells > MAX_USER_CELLS:
            raise DatasetLimitExceeded(
                f"Your storage limit of {MAX_USER_CELLS:,} cells (rows x columns) would be exceeded. Delete a dataset first."
            )

    @staticmethod
    def get(dataset_id: str, user_id: str) -> Optional[pd.DataFrame]:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT table_name FROM datasets_meta WHERE id = ? AND user_id = ?",
                (dataset_id, user_id),
            ).fetchone()
            if not row:
                return None
            table_name = row[0]
            return pd.read_sql(f"SELECT * FROM {table_name}", conn)
        finally:
            conn.close()

    @staticmethod
    @_serialized
    def update(dataset_id: str, user_id: str, df: pd.DataFrame) -> None:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT table_name FROM datasets_meta WHERE id = ? AND user_id = ?",
                (dataset_id, user_id),
            ).fetchone()
            if not row:
                raise ValueError(f"Dataset '{dataset_id}' not found")
            table_name = row[0]
            df.to_sql(table_name, conn, index=False, if_exists="replace", chunksize=10000)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def rename(dataset_id: str, user_id: str, new_filename: str) -> bool:
        conn = _get_connection()
        try:
            cursor = conn.execute(
                "UPDATE datasets_meta SET filename = ? WHERE id = ? AND user_id = ?",
                (new_filename, dataset_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def duplicate(dataset_id: str, user_id: str) -> Optional[Dict[str, str]]:
        df = DatasetStore.get(dataset_id, user_id)
        filename = DatasetStore.get_filename(dataset_id, user_id)
        if df is None or filename is None:
            return None
        copy_name = f"Copy of {filename}"
        new_id = DatasetStore.create(df, copy_name, user_id)
        return {"dataset_id": new_id, "filename": copy_name}

    @staticmethod
    def get_filename(dataset_id: str, user_id: str) -> Optional[str]:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT filename FROM datasets_meta WHERE id = ? AND user_id = ?",
                (dataset_id, user_id),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    @staticmethod
    def list_all(user_id: str, search: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = _get_connection()
        try:
            if search and search.strip():
                rows = conn.execute(
                    "SELECT id, filename, uploaded_at FROM datasets_meta "
                    "WHERE user_id = ? AND LOWER(filename) LIKE ? ORDER BY uploaded_at DESC",
                    (user_id, f"%{search.strip().lower()}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, filename, uploaded_at FROM datasets_meta WHERE user_id = ? ORDER BY uploaded_at DESC",
                    (user_id,),
                ).fetchall()
            return [{"dataset_id": r[0], "filename": r[1], "uploaded_at": r[2]} for r in rows]
        finally:
            conn.close()

    @staticmethod
    @_serialized
    def delete(dataset_id: str, user_id: str) -> bool:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT table_name FROM datasets_meta WHERE id = ? AND user_id = ?",
                (dataset_id, user_id),
            ).fetchone()
            if not row:
                return False
            table_name = row[0]
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            stale_snapshots = conn.execute(
                "SELECT snapshot_table FROM dataset_undo_stack WHERE dataset_id = ?", (dataset_id,)
            ).fetchall()
            for (snap,) in stale_snapshots:
                conn.execute(f"DROP TABLE IF EXISTS {snap}")
                conn.execute(f'DROP TABLE IF EXISTS "{_dtype_table_name(snap)}"')
            conn.execute("DELETE FROM dataset_undo_stack WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM dataset_notes WHERE dataset_id = ?", (dataset_id,))
            conn.execute(f"DROP TABLE IF EXISTS {table_name}__undo")
            conn.execute("DELETE FROM datasets_meta WHERE id = ? AND user_id = ?", (dataset_id, user_id))
            conn.execute("DELETE FROM dataset_snapshot_meta WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM dataset_audit_log WHERE dataset_id = ?", (dataset_id,))
            if DatasetStore._shares_table_exists(conn):
                conn.execute(
                    "DELETE FROM dataset_shares WHERE dataset_id = ?",
                    (dataset_id,),
                )
            if DatasetStore._saved_analyses_table_exists(conn):
                conn.execute(
                    "DELETE FROM saved_analyses WHERE dataset_id = ? AND user_id = ?",
                    (dataset_id, user_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    # ---------- Dataset notes ----------

    @staticmethod
    def get_note(dataset_id: str) -> str:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT note FROM dataset_notes WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
            return row[0] if row and row[0] else ""
        finally:
            conn.close()

    @staticmethod
    def save_note(dataset_id: str, note: str) -> None:
        conn = _get_connection()
        try:
            conn.execute(
                """
                INSERT INTO dataset_notes (dataset_id, note, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(dataset_id) DO UPDATE SET note = excluded.note, updated_at = CURRENT_TIMESTAMP
                """,
                (dataset_id, note),
            )
            conn.commit()
        finally:
            conn.close()

    # ---------- Undo stack (up to UNDO_STACK_LIMIT steps) ----------
    # These operate on dataset_id alone (no user_id check) because by the
    # time routes.py calls them, ownership has already been verified via
    # get()/get_dataset_or_404() earlier in the same request.

    @staticmethod
    @_serialized
    def save_snapshot(dataset_id: str, df: pd.DataFrame, action_label: str) -> None:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT table_name FROM datasets_meta WHERE id = ?", (dataset_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Dataset '{dataset_id}' not found")
            table_name = row[0]
            snapshot_table = f"{table_name}__undo_{uuid.uuid4().hex[:8]}"

            df.to_sql(snapshot_table, conn, index=False, if_exists="replace")
            _save_snapshot_dtypes(conn, snapshot_table, df)
            conn.execute(
                "INSERT INTO dataset_undo_stack (dataset_id, snapshot_table, action_label) VALUES (?, ?, ?)",
                (dataset_id, snapshot_table, action_label),
            )

            # Migrate away from the legacy single-snapshot format.
            conn.execute(f"DROP TABLE IF EXISTS {table_name}__undo")
            conn.execute("DELETE FROM dataset_snapshot_meta WHERE dataset_id = ?", (dataset_id,))

            entries = conn.execute(
                "SELECT id, snapshot_table FROM dataset_undo_stack WHERE dataset_id = ? ORDER BY id ASC",
                (dataset_id,),
            ).fetchall()
            while len(entries) > UNDO_STACK_LIMIT:
                oldest_id, oldest_table = entries.pop(0)
                conn.execute(f"DROP TABLE IF EXISTS {oldest_table}")
                conn.execute(f'DROP TABLE IF EXISTS "{_dtype_table_name(oldest_table)}"')
                conn.execute("DELETE FROM dataset_undo_stack WHERE id = ?", (oldest_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_undo_status(dataset_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT action_label, created_at FROM dataset_undo_stack WHERE dataset_id = ? ORDER BY id DESC",
                (dataset_id,),
            ).fetchall()
            if rows:
                return {
                    "action_label": rows[0][0],
                    "created_at": rows[0][1],
                    "steps_available": len(rows),
                }

            legacy = conn.execute(
                "SELECT action_label, created_at FROM dataset_snapshot_meta WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
            if legacy:
                return {"action_label": legacy[0], "created_at": legacy[1], "steps_available": 1}
            return None
        finally:
            conn.close()

    @staticmethod
    @_serialized
    def undo(dataset_id: str) -> pd.DataFrame:
        conn = _get_connection()
        try:
            row = conn.execute(
                "SELECT table_name FROM datasets_meta WHERE id = ?", (dataset_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Dataset '{dataset_id}' not found")
            table_name = row[0]

            stack_row = conn.execute(
                "SELECT id, snapshot_table, action_label FROM dataset_undo_stack "
                "WHERE dataset_id = ? ORDER BY id DESC LIMIT 1",
                (dataset_id,),
            ).fetchone()

            if stack_row:
                entry_id, snapshot_table, action_label = stack_row
            else:
                legacy = conn.execute(
                    "SELECT action_label FROM dataset_snapshot_meta WHERE dataset_id = ?",
                    (dataset_id,),
                ).fetchone()
                if not legacy:
                    raise ValueError("Nothing to undo.")
                entry_id = None
                snapshot_table = f"{table_name}__undo"
                action_label = legacy[0]

            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (snapshot_table,),
            ).fetchone()
            if not exists:
                raise ValueError("Nothing to undo.")

            df = pd.read_sql(f"SELECT * FROM {snapshot_table}", conn)
            df = _restore_snapshot_dtypes(conn, snapshot_table, df)
            df.to_sql(table_name, conn, index=False, if_exists="replace")
            conn.execute(f"DROP TABLE IF EXISTS {snapshot_table}")
            conn.execute(f'DROP TABLE IF EXISTS "{_dtype_table_name(snapshot_table)}"')

            if entry_id is not None:
                conn.execute("DELETE FROM dataset_undo_stack WHERE id = ?", (entry_id,))
            else:
                conn.execute("DELETE FROM dataset_snapshot_meta WHERE dataset_id = ?", (dataset_id,))

            conn.execute(
                "INSERT INTO dataset_audit_log (dataset_id, action, column_name, details) VALUES (?, ?, ?, ?)",
                (dataset_id, "undo", None, f"Undid: {action_label}"),
            )
            conn.commit()
            return df
        finally:
            conn.close()

    # ---------- Saved analyses (reproducible named snapshots) ----------

    @staticmethod
    def _ensure_saved_analyses_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_analyses (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                user_id TEXT,
                title TEXT,
                analysis_type TEXT,
                parameters_json TEXT,
                data_version TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_saved_analyses_dataset "
            "ON saved_analyses (dataset_id, user_id)"
        )

    @staticmethod
    def _saved_analyses_table_exists(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='saved_analyses'"
        ).fetchone() is not None

    @staticmethod
    @_serialized
    def save_analysis(
        dataset_id: str,
        user_id: str,
        title: str,
        analysis_type: str,
        parameters_json: str,
        data_version: str,
    ) -> str:
        analysis_id = str(uuid.uuid4())
        conn = _get_connection()
        try:
            DatasetStore._ensure_saved_analyses_table(conn)
            conn.execute(
                "INSERT INTO saved_analyses "
                "(id, dataset_id, user_id, title, analysis_type, parameters_json, data_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    analysis_id,
                    dataset_id,
                    user_id,
                    title,
                    analysis_type,
                    parameters_json,
                    data_version,
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
        return analysis_id

    @staticmethod
    def list_analyses(dataset_id: str, user_id: str) -> List[Dict[str, Any]]:
        conn = _get_connection()
        try:
            if not DatasetStore._saved_analyses_table_exists(conn):
                return []

            rows = conn.execute(
                "SELECT id, title, analysis_type, data_version, created_at FROM saved_analyses "
                "WHERE dataset_id = ? AND user_id = ? ORDER BY created_at DESC",
                (dataset_id, user_id),
            ).fetchall()

            return [
                {
                    "analysis_id": row[0],
                    "title": row[1],
                    "analysis_type": row[2],
                    "data_version": row[3],
                    "created_at": row[4],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def get_analysis(analysis_id: str, dataset_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_connection()
        try:
            if not DatasetStore._saved_analyses_table_exists(conn):
                return None

            row = conn.execute(
                "SELECT id, title, analysis_type, parameters_json, data_version, created_at FROM saved_analyses "
                "WHERE id = ? AND dataset_id = ? AND user_id = ?",
                (analysis_id, dataset_id, user_id),
            ).fetchone()

            if not row:
                return None

            return {
                "analysis_id": row[0],
                "title": row[1],
                "analysis_type": row[2],
                "parameters_json": row[3],
                "data_version": row[4],
                "created_at": row[5],
            }
        finally:
            conn.close()

    # ---------- Read-only dataset share links (only a SHA-256 hash of each token is stored) ----------

    _MAX_ACTIVE_SHARES_PER_DATASET = 25

    @staticmethod
    def _ensure_shares_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_shares (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                owner_user_id TEXT,
                token_hash TEXT UNIQUE,
                label TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                revoked_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dataset_shares_dataset "
            "ON dataset_shares (dataset_id, owner_user_id)"
        )

    @staticmethod
    def _shares_table_exists(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dataset_shares'"
        ).fetchone() is not None

    @staticmethod
    @_serialized
    def create_share(dataset_id: str, owner_user_id: str, label: str, expires_at: str) -> tuple:
        """Creates a share link. Returns (share_id, plaintext_token). The plaintext token is never stored."""
        import hashlib
        import secrets
        import datetime

        share_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()

        conn = _get_connection()
        try:
            DatasetStore._ensure_shares_table(conn)

            active_row = conn.execute(
                "SELECT COUNT(*) FROM dataset_shares "
                "WHERE dataset_id = ? AND owner_user_id = ? AND revoked_at IS NULL AND expires_at > ?",
                (dataset_id, owner_user_id, now),
            ).fetchone()

            active_count = int(active_row[0]) if active_row else 0
            if active_count >= DatasetStore._MAX_ACTIVE_SHARES_PER_DATASET:
                raise ValueError(
                    f"Active share link limit reached ({DatasetStore._MAX_ACTIVE_SHARES_PER_DATASET}). "
                    "Revoke an existing link first."
                )

            conn.execute(
                "INSERT INTO dataset_shares "
                "(id, dataset_id, owner_user_id, token_hash, label, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (share_id, dataset_id, owner_user_id, token_hash, label, expires_at),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

        return share_id, token

    @staticmethod
    def list_shares(dataset_id: str, owner_user_id: str) -> List[Dict[str, Any]]:
        """Lists only active shares (not revoked and not expired). Never returns token material."""
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()
        conn = _get_connection()
        try:
            if not DatasetStore._shares_table_exists(conn):
                return []

            rows = conn.execute(
                "SELECT id, label, created_at, expires_at FROM dataset_shares "
                "WHERE dataset_id = ? AND owner_user_id = ? AND revoked_at IS NULL AND expires_at > ? "
                "ORDER BY created_at DESC",
                (dataset_id, owner_user_id, now),
            ).fetchall()

            return [
                {
                    "share_id": row[0],
                    "label": row[1],
                    "created_at": row[2],
                    "expires_at": row[3],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    @_serialized
    def revoke_share(share_id: str, dataset_id: str, owner_user_id: str) -> bool:
        import datetime

        conn = _get_connection()
        try:
            if not DatasetStore._shares_table_exists(conn):
                return False

            cursor = conn.execute(
                "UPDATE dataset_shares SET revoked_at = ? "
                "WHERE id = ? AND dataset_id = ? AND owner_user_id = ? AND revoked_at IS NULL",
                (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(), share_id, dataset_id, owner_user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    @staticmethod
    def resolve_share(token: str) -> Optional[tuple]:
        """Returns (dataset_id, owner_user_id) only for a valid, unexpired, unrevoked token; otherwise None."""
        import datetime
        import hashlib

        if not token or len(token) > 200:
            return None

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = _get_connection()
        try:
            if not DatasetStore._shares_table_exists(conn):
                return None

            row = conn.execute(
                "SELECT dataset_id, owner_user_id, expires_at, revoked_at FROM dataset_shares "
                "WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()

            if not row:
                return None

            dataset_id, owner_user_id, expires_at, revoked_at = row

            if revoked_at is not None:
                return None

            if not expires_at:
                return None

            try:
                expires_dt = datetime.datetime.fromisoformat(expires_at)
            except (TypeError, ValueError):
                return None

            if expires_dt < datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None):
                return None

            return dataset_id, owner_user_id
        finally:
            conn.close()

    # ---------- Permanent audit log ----------

    @staticmethod
    def log_action(dataset_id: str, action: str, column: Optional[str], details: str = "") -> None:
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO dataset_audit_log (dataset_id, action, column_name, details) VALUES (?, ?, ?, ?)",
                (dataset_id, action, column, details),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_audit_log(dataset_id: str) -> List[Dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                """
                SELECT action, column_name, details, created_at
                FROM dataset_audit_log
                WHERE dataset_id = ?
                ORDER BY id DESC
                """,
                (dataset_id,),
            ).fetchall()
            return [
                {"action": r[0], "column": r[1], "details": r[2], "timestamp": r[3]}
                for r in rows
            ]
        finally:
            conn.close()