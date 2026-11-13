# backend/database/db_connector.py
import sqlite3
import re
import time
import pandas as pd
from typing import List, Dict, Any

MAX_QUERY_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 10


def get_connection_with_data(df: pd.DataFrame) -> sqlite3.Connection:
    """
    Creates a fresh in-memory SQLite database and loads the dataframe
    into a table called 'data'. A fresh connection per query keeps things simple/safe.
    """
    conn = sqlite3.connect(":memory:")
    df.to_sql("data", conn, index=False, if_exists="replace")
    lock_down_connection(conn)
    return conn


_BLOCKED_SQL_FUNCTIONS = {"randomblob", "zeroblob", "load_extension"}
_MAX_SQL_VALUE_LENGTH = 20_000_000  # bytes: caps any single string/blob a query can build


def _sql_authorizer(action, arg1, arg2, dbname, source):
    # 31 = SQLITE_FUNCTION, 19 = SQLITE_PRAGMA, 24 = SQLITE_ATTACH, 25 = SQLITE_DETACH
    if action == 31 and str(arg2 or "").lower() in _BLOCKED_SQL_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    if action in (19, 24, 25):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def lock_down_connection(conn: sqlite3.Connection) -> None:
    """Call AFTER the data table is loaded: read-only, no memory-bomb functions, bounded value size."""
    conn.execute("PRAGMA query_only = ON")
    try:
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SQL_VALUE_LENGTH)
    except (AttributeError, sqlite3.Error):
        pass  # Connection.setlimit needs Python 3.11+; the authorizer below still applies.
    conn.set_authorizer(_sql_authorizer)


def run_query(
    conn: sqlite3.Connection,
    sql: str,
    max_rows: int = MAX_QUERY_ROWS,
    timeout_seconds: int = QUERY_TIMEOUT_SECONDS,
) -> List[Dict[str, Any]]:
    # Abort long-running statements (for example unbounded recursive queries) and cap the result size.
    deadline = time.monotonic() + timeout_seconds
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
    try:
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            raise ValueError(f"Query exceeded the {timeout_seconds} second time limit.")
        raise
    finally:
        conn.set_progress_handler(None, 0)
    return [dict(zip(columns, row)) for row in rows]


# Keywords that are never allowed (they modify/delete data)
FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter",
    "create", "attach", "detach", "pragma", "replace", "vacuum"
]


def validate_select_only(sql: str) -> None:
    """
    Raises ValueError if the query is not a safe, single SELECT statement.
    """
    cleaned = sql.strip().rstrip(";").strip()
    lowered = cleaned.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT queries are allowed.")

    # String literals, quoted identifiers and comments are removed first, so keywords
    # or semicolons that appear only inside them are not flagged.
    scrubbed = re.sub(
        r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/",
        " ",
        lowered,
        flags=re.DOTALL,
    )

    for word in FORBIDDEN_KEYWORDS:
        # REPLACE(...) is a harmless string function; only a bare REPLACE keyword is blocked.
        pattern = r"\breplace\b(?!\s*\()" if word == "replace" else rf"\b{word}\b"
        if re.search(pattern, scrubbed):
            raise ValueError(f"Query contains a forbidden keyword: '{word}'")

    if ";" in scrubbed:
        raise ValueError("Multiple SQL statements are not allowed.")