# backend/api/routes.py
import os
import re
import threading
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from backend.data.loader import DataLoader
from backend.data.profiler import DataProfiler
from backend.data.cleaner import DataCleaner
from backend.agents.sql_agent import SQLAgent
from backend.agents.python_agent import PythonAgent
from backend.agents.insight_agent import InsightAgent
from backend.agents.cleaning_agent import CleaningAgent
from backend.agents.report_agent import ReportAgent
from backend.agents.orchestrator import Orchestrator
from backend.database.db_connector import get_connection_with_data, run_query, validate_select_only
from backend.database.dataset_store import DatasetStore
from backend.analytics.anomaly import AnomalyDetector
from backend.analytics.statistics import VarianceAnalyzer
from backend.analytics.forecasting import Forecaster
from backend.reports.generator import ReportGenerator, cleanup_old_reports
from backend.auth.dependencies import require_auth, require_premium
from backend.utils.rate_limiter import (
    rate_limit,
    llm_limiter,
    login_limiter,
    upload_limiter,
    export_limiter,
    report_limiter,
    sql_limiter,
    share_view_limiter,
    write_limiter,
    security_limiter,
)
from backend.auth.account_deletion import purge_report_files, send_deletion_email, confirm_deletion
from fastapi.responses import Response
from backend.visualization.chart_image import ChartImageExporter
from backend.visualization.charts import ChartEngine, TIME_GRANULARITY_LEVELS
from backend.auth.user_store import UserStore

from backend.scheduling.schedule_store import ScheduleStore
from backend.scheduling.runner import execute_schedule, failure_reason

from backend.auth.verification import send_verification_email, email_failure_message

from backend.utils.ai_gate import (
    AICache, QuotaExceeded, cached_ai_call, quota_or_http_429, refund_quota, get_usage_info,
    get_data_version,
)

router = APIRouter()

MAX_UPLOAD_SIZE_MB = 500
MAX_NOTE_LENGTH = 1000
VALID_AGGREGATIONS = {"sum", "mean", "median", "count", "min", "max"}


def to_json_safe_records(df: pd.DataFrame, n: int = None) -> list:
    subset = df.head(n) if n else df
    return subset.astype(object).where(pd.notnull(subset), None).to_dict(orient="records")


def get_dataset_or_404(dataset_id: str, user_id: str) -> pd.DataFrame:
    df = DatasetStore.get(dataset_id, user_id)
    if df is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return df


def _safe_upload_filename(raw_name: Any) -> str:
    name = str(raw_name or "").strip()
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "", name)
    name = os.path.basename(name).strip(" .")

    if not name:
        return "dataset.csv"

    if len(name) <= 120:
        return name

    ext_match = re.search(r"\.[A-Za-z0-9]{1,10}$", name)
    ext = ext_match.group(0) if ext_match else ""
    base = name[: ext_match.start()] if ext_match else name

    max_base_len = max(1, 120 - len(ext))
    base = base[:max_base_len].rstrip(" .")

    if not base:
        base = "dataset"

    return f"{base}{ext}"


_DATASET_WRITE_LOCKS: dict = {}
_DATASET_LOCKS_GUARD = threading.Lock()


def dataset_write_lock(dataset_id: str):
    """
    Serializes read-modify-write operations (clean, clean-all, undo) per dataset, so two concurrent
    edits cannot read the same data and overwrite each other's result.
    """
    with _DATASET_LOCKS_GUARD:
        lock = _DATASET_WRITE_LOCKS.setdefault(dataset_id, threading.Lock())
    if not lock.acquire(timeout=60):
        raise HTTPException(
            status_code=409,
            detail="This dataset is being modified by another request. Please try again in a moment.",
        )
    try:
        yield
    finally:
        lock.release()


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...), current_user: str = Depends(require_auth), _rl=Depends(rate_limit(upload_limiter))):
    """
    Upload a .csv, .xlsx, .json, or .sql file. Returns a dataset_id (UUID)
    scoped to the logged-in user, plus an automatic profile of the data.

    A generous 500MB size cap exists purely as a crash-safety net (an
    accidental multi-GB upload could exhaust server memory for everyone
    currently using the app) — it will never affect a genuine large
    business dataset.
    """
    file.file.seek(0, 2)
    size_mb = file.file.tell() / (1024 * 1024)
    file.file.seek(0)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.0f}MB). Maximum allowed is {MAX_UPLOAD_SIZE_MB}MB.",
        )

    try:
        df = await DataLoader.load(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset could not be loaded.") from e

    if not isinstance(df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Dataset could not be loaded.")

    safe_filename = _safe_upload_filename(file.filename)

    # Heavy blocking work runs in the thread pool so a large upload does not freeze other requests.
    dataset_id = await run_in_threadpool(DatasetStore.create, df, safe_filename, current_user)
    profile = await run_in_threadpool(DataProfiler.profile, df)

    if not isinstance(profile, dict):
        raise HTTPException(status_code=500, detail="Dataset profile could not be generated.")

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "dataset_id": dataset_id,
        "filename": safe_filename,
        "profile": profile,
        "preview": preview,
    }


@router.get("/datasets")
def list_datasets(search: Optional[str] = None, current_user: str = Depends(require_auth)):
    """Lists datasets uploaded by the logged-in user only, optionally filtered by name."""
    try:
        datasets = DatasetStore.list_all(current_user, search=search)
    except Exception:
        datasets = []

    if not isinstance(datasets, list):
        datasets = []

    safe_datasets = []
    for dataset in datasets:
        if (
            isinstance(dataset, dict)
            and isinstance(dataset.get("dataset_id"), str)
            and dataset.get("dataset_id")
        ):
            safe_datasets.append(dataset)

    return {"datasets": safe_datasets}


@router.delete("/dataset/{dataset_id}")
def delete_dataset(dataset_id: str, current_user: str = Depends(require_auth)):
    deleted = DatasetStore.delete(dataset_id, current_user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        AICache.delete_for_dataset(dataset_id)
    except Exception:
        pass

    try:
        Orchestrator.reset_conversation(dataset_id)
    except Exception:
        pass

    try:
        ScheduleStore.delete_for_dataset(dataset_id, current_user)
    except Exception:
        pass

    try:
        purge_report_files(dataset_id)
    except Exception:
        pass

    return {"dataset_id": dataset_id, "message": "Dataset deleted."}


@router.get("/dataset/{dataset_id}/profile")
def get_profile(dataset_id: str, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        profile = DataProfiler.profile(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset profile could not be generated.") from e

    if not isinstance(profile, dict):
        raise HTTPException(status_code=500, detail="Dataset profile returned an unexpected result.")

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "profile": profile,
        "preview": preview,
    }


@router.get("/dataset/{dataset_id}/issues")
def get_issues(dataset_id: str, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        issues = DataCleaner.detect_issues(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Data quality issues could not be detected.") from e

    if not isinstance(issues, dict):
        raise HTTPException(status_code=500, detail="Data quality issues returned an unexpected result.")

    list_keys = (
        "key_duplicates",
        "missing_values",
        "outliers",
        "negative_values",
        "inconsistent_values",
        "fuzzy_category_issues",
        "date_format_issues",
        "numeric_format_issues",
        "email_format_issues",
    )

    for key in list_keys:
        if not isinstance(issues.get(key), list):
            issues[key] = []

    duplicate_rows = issues.get("duplicate_rows")

    if isinstance(duplicate_rows, dict):
        try:
            duplicate_rows["count"] = int(duplicate_rows.get("count", 0))
        except (TypeError, ValueError, OverflowError):
            duplicate_rows["count"] = 0

        duplicate_rows["message"] = str(duplicate_rows.get("message") or "")
    elif isinstance(duplicate_rows, int):
        issues["duplicate_rows"] = {
            "count": duplicate_rows,
            "message": f"{duplicate_rows} duplicate row(s) detected." if duplicate_rows else "No duplicate rows detected.",
        }
    else:
        issues["duplicate_rows"] = {
            "count": 0,
            "message": "No duplicate rows detected.",
        }

    return {"dataset_id": dataset_id, "issues": issues}


class CleanRequest(BaseModel):
    action: str
    column: Optional[str] = None
    strategy: str = "mean"
    new_name: Optional[str] = None
    second_column: Optional[str] = None
    operator: str = "+"
    filter_value: Optional[str] = None
    sample_count: Optional[int] = None
    replace_value: Optional[str] = None
    row_index: Optional[int] = None
    expected_old_value: Optional[str] = None


def _describe_action(request: "CleanRequest") -> str:
    labels = {
        "remove_duplicates": "Removed duplicate rows",
        "fill_missing": f"Filled missing values in '{request.column}' ({request.strategy})",
        "drop_missing": f"Dropped rows with missing '{request.column}'",
        "normalize_text": f"Normalized inconsistent text in '{request.column}'",
        "normalize_text_aggressive": f"Merged fuzzy-duplicate categories in '{request.column}'",
        "normalize_date_format": f"Standardized date format in '{request.column}'",
        "clean_numeric_format": f"Converted '{request.column}' to numeric",
        "resolve_key_duplicates": f"Removed key-based duplicate records by '{request.column}'",
        "mark_negative_as_missing": f"Marked invalid negative values as missing in '{request.column}'",
        "clip_outliers": f"Capped outliers in '{request.column}' to expected range",
        "drop_column": f"Dropped column '{request.column}'",
        "filter_rows": f"Filtered rows where '{request.column}' {request.operator} '{request.filter_value}'",
        "auto_clean_safe": "Auto-cleaned duplicates, whitespace, and numeric missing values (median)",
        "sort_dataset": f"Sorted dataset by '{request.column}' ({'ascending' if request.operator != 'desc' else 'descending'})",
        "sample_rows": f"Sampled {request.sample_count} random rows",
        "find_and_replace": f"Replaced '{request.filter_value}' with '{request.replace_value}' in '{request.column}'",
        "update_cell": f"Edited cell in '{request.column}' (row {(request.row_index or 0) + 1})",
        "rename_column": f"Renamed '{request.column}' to '{request.new_name}'",
        "add_calculated_column": f"Added calculated column '{request.new_name}' ({request.column} {request.operator} {request.second_column})",
        "lowercase_column": f"Lowercased values in '{request.column}'",
        "flag_invalid_email_as_missing": f"Flagged malformed emails as missing in '{request.column}'",
    }
    return labels.get(request.action, request.action)


CLEAN_ACTIONS = {
    "remove_duplicates": lambda df, req: DataCleaner.remove_duplicates(df),
    "fill_missing": lambda df, req: DataCleaner.fill_missing(df, req.column, req.strategy),
    "drop_missing": lambda df, req: DataCleaner.drop_missing(df, req.column),
    "normalize_text": lambda df, req: DataCleaner.normalize_text(df, req.column),
    "normalize_text_aggressive": lambda df, req: DataCleaner.normalize_text_aggressive(df, req.column),
    "normalize_date_format": lambda df, req: DataCleaner.normalize_date_format(df, req.column),
    "clean_numeric_format": lambda df, req: DataCleaner.clean_numeric_format(df, req.column),
    "resolve_key_duplicates": lambda df, req: DataCleaner.resolve_key_duplicates(df, req.column),
    "mark_negative_as_missing": lambda df, req: DataCleaner.mark_negative_as_missing(df, req.column),
    "clip_outliers": lambda df, req: DataCleaner.clip_outliers(df, req.column),
    "drop_column": lambda df, req: DataCleaner.drop_column(df, req.column),
    "filter_rows": lambda df, req: DataCleaner.filter_rows(df, req.column, req.operator, req.filter_value or ""),
    "auto_clean_safe": lambda df, req: DataCleaner.auto_clean_safe(df),
    "sort_dataset": lambda df, req: DataCleaner.sort_dataset(df, req.column, ascending=(req.operator != "desc")),
    "sample_rows": lambda df, req: DataCleaner.sample_rows(df, int(req.sample_count or 100)),
    "find_and_replace": lambda df, req: DataCleaner.find_and_replace(
        df, req.column, req.filter_value or "", req.replace_value or ""
    ),
    "update_cell": lambda df, req: DataCleaner.update_cell(
        df, req.row_index, req.column, req.replace_value, req.expected_old_value
    ),
    "rename_column": lambda df, req: DataCleaner.rename_column(df, req.column, req.new_name or ""),
    "add_calculated_column": lambda df, req: DataCleaner.add_calculated_column(
        df, req.new_name or "", req.column, req.operator, req.second_column or ""
    ),
    "lowercase_column": lambda df, req: DataCleaner.lowercase_column(df, req.column),
    "flag_invalid_email_as_missing": lambda df, req: DataCleaner.flag_invalid_email_as_missing(df, req.column),
}

ACTIONS_REQUIRING_COLUMN = set(CLEAN_ACTIONS.keys()) - {"remove_duplicates", "auto_clean_safe", "sample_rows"}


@router.post("/dataset/{dataset_id}/clean")
def clean_dataset(dataset_id: str, request: CleanRequest, current_user: str = Depends(require_auth), _wl=Depends(dataset_write_lock)):
    df = get_dataset_or_404(dataset_id, current_user)

    if request.action not in CLEAN_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")
    if request.action in ACTIONS_REQUIRING_COLUMN and not request.column:
        raise HTTPException(status_code=400, detail=f"column is required for {request.action}")

    if request.action == "sample_rows":
        requested_sample = request.sample_count if request.sample_count is not None else 100
        if not 1 <= requested_sample < len(df):
            raise HTTPException(
                status_code=400,
                detail=f"Sample count must be between 1 and {len(df) - 1}.",
            )

    action_label = _describe_action(request)
    original_df = df.copy()

    try:
        cleaned_df = CLEAN_ACTIONS[request.action](df, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Cleaning action failed.") from e

    if not isinstance(cleaned_df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Cleaning action returned an unexpected result.")

    df = cleaned_df

    try:
        DatasetStore.update(dataset_id, current_user, df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset update failed.") from e

    try:
        DatasetStore.save_snapshot(dataset_id, original_df, action_label)
    except Exception:
        pass

    try:
        DatasetStore.log_action(dataset_id, request.action, request.column, details=action_label)
    except Exception:
        pass

    try:
        profile = DataProfiler.profile(df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "dataset_id": str(dataset_id),
        "message": f"Action '{request.action}' applied successfully.",
        "profile": profile,
        "preview": preview,
    }


def _preview_json_value(value: Any) -> Any:
    """JSON-safe preview value: missing and non-finite numbers become null; numpy/timestamp values become plain types."""
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float):
        if value != value or value == float("inf") or value == float("-inf"):
            return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


PREVIEW_MAX_SAMPLE_CHANGES = 20


@router.post("/dataset/{dataset_id}/clean/preview")
def preview_clean_dataset(dataset_id: str, request: CleanRequest, current_user: str = Depends(require_auth)):
    """
    Non-destructive preview of a cleaning action. The same operation runs on an in-memory copy and its
    effect is summarized. Nothing is saved, no undo snapshot is created, and the dataset is not modified.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    if request.action not in CLEAN_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")
    if request.action in ACTIONS_REQUIRING_COLUMN and not request.column:
        raise HTTPException(status_code=400, detail=f"column is required for {request.action}")
    if request.action == "sample_rows":
        requested_sample = request.sample_count if request.sample_count is not None else 100
        if not 1 <= requested_sample < len(df):
            raise HTTPException(
                status_code=400,
                detail=f"Sample count must be between 1 and {len(df) - 1}.",
            )

    try:
        after = CLEAN_ACTIONS[request.action](df.copy(), request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Cleaning preview failed.") from e

    if not isinstance(after, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Cleaning preview returned an unexpected result.")

    warnings: List[str] = []
    rows_before = int(len(df))
    rows_after = int(len(after))

    if rows_after < rows_before:
        warnings.append(f"{rows_before - rows_after} row(s) would be removed.")
    elif rows_after > rows_before:
        warnings.append(f"{rows_after - rows_before} row(s) would be added.")

    columns_added = [c for c in after.columns if c not in df.columns]
    columns_removed = [c for c in df.columns if c not in after.columns]
    if columns_added:
        warnings.append(f"Column(s) would be added: {', '.join(map(str, columns_added))}.")
    if columns_removed:
        warnings.append(f"Column(s) would be removed: {', '.join(map(str, columns_removed))}.")

    common_columns = [c for c in df.columns if c in after.columns]
    rows_aligned = rows_before == rows_after
    has_duplicate_columns = bool(df.columns.duplicated().any() or after.columns.duplicated().any())

    if not rows_aligned:
        warnings.append("Row count changes, so cell-level changes are not shown row by row.")
    if has_duplicate_columns:
        warnings.append("Duplicate column names are present, so cell-level changes are not shown.")

    cells_changed = 0
    columns_with_changes: List[str] = []
    sample_changes: List[Dict[str, Any]] = []
    identifier_column = df.columns[0] if len(df.columns) > 0 else None
    if identifier_column is not None and identifier_column not in df.columns:
        identifier_column = None

    if rows_aligned and not has_duplicate_columns:
        old_frame = df.reset_index(drop=True)
        new_frame = after.reset_index(drop=True)
        for col in common_columns:
            old_series = old_frame[col].astype(object)
            new_series = new_frame[col].astype(object)
            both_missing = old_series.isna() & new_series.isna()
            changed = ~(both_missing | (old_series == new_series))
            changed_count = int(changed.sum())
            if changed_count == 0:
                continue
            cells_changed += changed_count
            columns_with_changes.append(str(col))
            for idx, flag in enumerate(changed.tolist()):
                if not flag or len(sample_changes) >= PREVIEW_MAX_SAMPLE_CHANGES:
                    continue
                try:
                    identifier = (
                        _preview_json_value(old_frame[identifier_column].iloc[idx])
                        if identifier_column is not None and identifier_column in old_frame.columns
                        else idx
                    )
                except Exception:
                    identifier = idx
                sample_changes.append({
                    "column": str(col),
                    "row_index": idx,
                    "identifier": identifier,
                    "old_value": _preview_json_value(old_series.iloc[idx]),
                    "new_value": _preview_json_value(new_series.iloc[idx]),
                })

    sample_truncated = cells_changed > len(sample_changes)
    columns_affected = sorted(set(columns_with_changes) | {str(c) for c in columns_added} | {str(c) for c in columns_removed})

    describe_action = globals().get("_describe_action")
    action_label = describe_action(request) if callable(describe_action) else request.action

    safe_sample_changes = []
    for change in sample_changes if isinstance(sample_changes, list) else []:
        if not isinstance(change, dict):
            continue

        safe_change = dict(change)
        safe_change["column"] = str(safe_change.get("column") or "")
        safe_change["row_index"] = _safe_int(safe_change.get("row_index"), 0)
        safe_change["identifier"] = safe_change.get("identifier")
        safe_change["old_value"] = safe_change.get("old_value")
        safe_change["new_value"] = safe_change.get("new_value")
        safe_sample_changes.append(safe_change)

    safe_warnings = []
    for warning in warnings if isinstance(warnings, list) else []:
        if warning is not None:
            safe_warnings.append(str(warning))

    safe_columns_affected = []
    for col in columns_affected if isinstance(columns_affected, list) else []:
        if col is not None:
            safe_columns_affected.append(str(col))

    return {
        "dataset_id": str(dataset_id),
        "action": str(request.action),
        "action_label": str(action_label or request.action),
        "rows_before": _safe_int(rows_before),
        "rows_after": _safe_int(rows_after),
        "cells_changed": _safe_int(cells_changed),
        "columns_affected": safe_columns_affected,
        "warnings": safe_warnings,
        "sample_changes": safe_sample_changes,
        "sample_changes_truncated": bool(sample_truncated),
    }


def _summarize_cleaning_effect(df: pd.DataFrame, after: pd.DataFrame) -> Dict[str, Any]:
    """
    Summarizes the effect of a cleaning result without modifying either frame. Cell-level comparison is
    skipped (with a warning) when the row count changes or when column names are duplicated.
    """
    warnings: List[str] = []
    rows_before = int(len(df))
    rows_after = int(len(after))

    if rows_after < rows_before:
        warnings.append(f"{rows_before - rows_after} row(s) would be removed.")
    elif rows_after > rows_before:
        warnings.append(f"{rows_after - rows_before} row(s) would be added.")

    columns_added = [c for c in after.columns if c not in df.columns]
    columns_removed = [c for c in df.columns if c not in after.columns]
    if columns_added:
        warnings.append(f"Column(s) would be added: {', '.join(map(str, columns_added))}.")
    if columns_removed:
        warnings.append(f"Column(s) would be removed: {', '.join(map(str, columns_removed))}.")

    cells_changed = 0
    columns_with_changes: List[str] = []
    sample_changes: List[Dict[str, Any]] = []

    duplicate_names = bool(df.columns.duplicated().any() or after.columns.duplicated().any())
    rows_aligned = rows_before == rows_after

    if duplicate_names:
        warnings.append("Duplicate column names are present, so cell-level changes are not shown row by row.")
    elif not rows_aligned:
        warnings.append("Row count changes, so cell-level changes are not shown row by row.")
    else:
        old_frame = df.reset_index(drop=True)
        new_frame = after.reset_index(drop=True)
        identifier_column = old_frame.columns[0] if len(old_frame.columns) > 0 else None
        if identifier_column is not None and identifier_column not in old_frame.columns:
            identifier_column = None
        common_columns = [c for c in old_frame.columns if c in new_frame.columns]

        for col in common_columns:
            old_series = old_frame[col].astype(object)
            new_series = new_frame[col].astype(object)
            both_missing = old_series.isna() & new_series.isna()
            changed = ~(both_missing | (old_series == new_series))
            changed_count = int(changed.sum())
            if changed_count == 0:
                continue
            cells_changed += changed_count
            columns_with_changes.append(str(col))
            for idx, flag in enumerate(changed.tolist()):
                if not flag or len(sample_changes) >= PREVIEW_MAX_SAMPLE_CHANGES:
                    continue
                identifier = (
                    _preview_json_value(old_frame[identifier_column].iloc[idx])
                    if identifier_column is not None
                    else idx
                )
                sample_changes.append({
                    "column": str(col),
                    "row_index": idx,
                    "identifier": identifier,
                    "old_value": _preview_json_value(old_series.iloc[idx]),
                    "new_value": _preview_json_value(new_series.iloc[idx]),
                })

    columns_affected = sorted(
        set(columns_with_changes) | {str(c) for c in columns_added} | {str(c) for c in columns_removed}
    )

    return {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "cells_changed": cells_changed,
        "columns_affected": columns_affected,
        "warnings": warnings,
        "sample_changes": sample_changes,
        "sample_changes_truncated": cells_changed > len(sample_changes),
    }


def _normalize_actions_applied(actions_applied: Any) -> List[str]:
    """Makes clean-all action metadata JSON-safe without changing the cleaning result."""
    if actions_applied is None:
        return []
    if isinstance(actions_applied, str):
        return [actions_applied]
    try:
        return [str(a) for a in actions_applied]
    except TypeError:
        return [str(actions_applied)]


def _safe_int(value: Any, default: int = 0) -> int:
    """Converts a value to int safely, used for response normalization."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_finite_number(value: Any):
    """Converts numeric values to finite floats, returning None for NaN/Inf/non-numeric values."""
    if value is None or isinstance(value, bool):
        return None

    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if num != num or num == float("inf") or num == float("-inf"):
        return None

    return num


def _make_json_safe(value: Any, _depth: int = 0) -> Any:
    """
    Recursively converts common analytics/AI response values into JSON-safe Python types.
    This helps endpoints return stable responses even when a model, numpy, pandas, or
    user-generated Python analysis produces unusual object types.
    """
    if _depth > 6:
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if value != value or value == float("inf") or value == float("-inf"):
                return None
            return value
        try:
            return str(value)
        except Exception:
            return None

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if value != value or value == float("inf") or value == float("-inf"):
            return None
        return value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return str(value)
            except Exception:
                return None

    if isinstance(value, pd.Timestamp):
        try:
            return value.isoformat()
        except Exception:
            try:
                return str(value)
            except Exception:
                return None

    if hasattr(value, "item") and not isinstance(value, (dict, list, tuple, set, str, bytes)):
        try:
            return _make_json_safe(value.item(), _depth + 1)
        except Exception:
            pass

    if isinstance(value, dict):
        safe_dict = {}
        for key, item in value.items():
            try:
                safe_key = str(key)
            except Exception:
                safe_key = "<invalid_key>"
            safe_dict[safe_key] = _make_json_safe(item, _depth + 1)
        return safe_dict

    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item, _depth + 1) for item in value]

    try:
        return str(value)
    except Exception:
        return None


def _safe_text(value: Any, max_length: int = 5000):
    """
    Converts AI/report/shared text-like values into a bounded JSON-safe string.
    Lists/tuples/sets are joined with newlines so report sections remain readable.
    """
    if value is None:
        return None

    if isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            safe_item = _make_json_safe(item)
            if safe_item is None:
                continue
            if isinstance(safe_item, str):
                parts.append(safe_item)
            else:
                try:
                    parts.append(str(safe_item))
                except Exception:
                    continue
        text = "\n".join(parts)
    else:
        safe_value = _make_json_safe(value)
        if safe_value is None:
            return None
        if isinstance(safe_value, str):
            text = safe_value
        else:
            try:
                text = str(safe_value)
            except Exception:
                return None

    if max_length and len(text) > max_length:
        return text[:max_length] + "…"

    return text


@router.post("/dataset/{dataset_id}/clean-all/preview")
def preview_clean_all(dataset_id: str, current_user: str = Depends(require_auth)):
    """
    Non-destructive preview of the clean-all sequence. The same operations run on an in-memory copy.
    Nothing is saved, no undo snapshot is created, and the dataset is not modified.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        raw_result = DataCleaner.auto_clean_all(df.copy())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Clean-all preview failed.") from e

    if isinstance(raw_result, tuple):
        if not raw_result:
            raise HTTPException(status_code=500, detail="Clean-all preview returned no result.")
        after = raw_result[0]
        actions_applied = raw_result[1] if len(raw_result) > 1 else None
    else:
        after = raw_result
        actions_applied = None

    if not isinstance(after, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Clean-all preview returned an unexpected result.")

    summary = _summarize_cleaning_effect(df, after)
    if not isinstance(summary, dict):
        summary = {}

    for key in ("rows_before", "rows_after", "cells_changed"):
        try:
            summary[key] = int(summary.get(key, 0))
        except (TypeError, ValueError, OverflowError):
            summary[key] = 0

    for key in ("columns_affected", "warnings", "sample_changes"):
        if not isinstance(summary.get(key), list):
            summary[key] = []

    summary["sample_changes_truncated"] = bool(summary.get("sample_changes_truncated", False))

    return {
        "dataset_id": dataset_id,
        "actions_applied": _normalize_actions_applied(actions_applied),
        **summary,
    }


@router.post("/dataset/{dataset_id}/clean-all")
def clean_all(dataset_id: str, current_user: str = Depends(require_auth), _wl=Depends(dataset_write_lock)):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        raw_result = DataCleaner.auto_clean_all(df)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Auto-clean failed.") from e

    if isinstance(raw_result, tuple):
        if not raw_result:
            raise HTTPException(status_code=500, detail="Clean-all returned no result.")
        cleaned_df = raw_result[0]
        actions_applied = raw_result[1] if len(raw_result) > 1 else None
    else:
        cleaned_df = raw_result
        actions_applied = None

    if not isinstance(cleaned_df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Clean-all returned an unexpected result.")

    if actions_applied is None:
        actions_applied = []
    elif not isinstance(actions_applied, list):
        actions_applied = [str(actions_applied)]
    else:
        actions_applied = [str(action) for action in actions_applied]

    try:
        DatasetStore.update(dataset_id, current_user, cleaned_df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset update failed.") from e

    try:
        DatasetStore.save_snapshot(dataset_id, df, "Auto-clean all")
    except Exception:
        pass

    try:
        DatasetStore.log_action(
            dataset_id,
            "clean_all",
            None,
            details="; ".join(actions_applied) if actions_applied else "No changes needed",
        )
    except Exception:
        pass

    try:
        profile = DataProfiler.profile(cleaned_df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    try:
        preview = to_json_safe_records(cleaned_df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "dataset_id": str(dataset_id),
        "message": "Auto-clean completed.",
        "actions_applied": actions_applied,
        "profile": profile,
        "preview": preview,
    }


@router.get("/dataset/{dataset_id}/undo-status")
def get_undo_status(dataset_id: str, current_user: str = Depends(require_auth)):
    get_dataset_or_404(dataset_id, current_user)  # ownership check

    try:
        status = DatasetStore.get_undo_status(dataset_id)
    except Exception:
        status = None

    if status is not None and not isinstance(status, dict):
        status = None

    if isinstance(status, dict):
        status = dict(status)
        status["action_label"] = str(status.get("action_label") or "Last action")

        try:
            steps = int(status.get("steps_available", 1))
        except (TypeError, ValueError, OverflowError):
            steps = 1

        status["steps_available"] = max(1, steps)

    return {
        "dataset_id": dataset_id,
        "undo_available": status is not None,
        "pending_undo": status,
    }


@router.post("/dataset/{dataset_id}/undo")
def undo_last_action(dataset_id: str, current_user: str = Depends(require_auth), _wl=Depends(dataset_write_lock)):
    get_dataset_or_404(dataset_id, current_user)  # ownership check
    try:
        df = DatasetStore.undo(dataset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Undo failed.") from e

    if not isinstance(df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Undo returned an unexpected result.")

    try:
        profile = DataProfiler.profile(df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "dataset_id": str(dataset_id),
        "message": "Last action undone.",
        "profile": profile,
        "preview": preview,
    }


class SavedAnalysisRequest(BaseModel):
    title: str
    analysis_type: str
    parameters: Optional[Dict[str, Any]] = None


SAVED_ANALYSIS_TYPES = (
    "kpi",
    "chart",
    "time_series",
    "pivot",
    "forecast",
    "anomaly",
    "root_cause",
    "sql_query",
    "clean_preview",
    "quality_report",
    "metric_catalog",
    "narrative_summary",
    "cleaning_plan",
)
SAVED_ANALYSIS_MAX_PARAM_CHARS = 20000


@router.get("/dataset/{dataset_id}/saved-analyses")
def list_saved_analyses(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    analysis_type: Optional[str] = None,
):
    """
    Lists the current user's saved analyses for a dataset.
    Optionally filters by analysis_type. Read-only.
    """
    get_dataset_or_404(dataset_id, current_user)

    try:
        analyses = DatasetStore.list_analyses(dataset_id, current_user)
    except Exception:
        analyses = []

    if not isinstance(analyses, list):
        analyses = []

    requested_type = _safe_text(analysis_type, 50)
    requested_type = requested_type.strip() if requested_type else None

    safe_analyses = []
    for analysis in analyses:
        if not isinstance(analysis, dict):
            continue

        if requested_type:
            item_type = _safe_text(analysis.get("analysis_type"), 50)
            item_type = item_type.strip() if item_type else None

            if item_type != requested_type:
                continue

        safe_analyses.append(analysis)

    return {"dataset_id": dataset_id, "analyses": safe_analyses}


@router.post("/dataset/{dataset_id}/saved-analyses")
def create_saved_analysis(
    dataset_id: str,
    request: SavedAnalysisRequest,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(write_limiter)),
):
    """Saves a named snapshot of an analysis configuration. Does not modify the dataset."""
    import json

    df = get_dataset_or_404(dataset_id, current_user)

    title = _safe_text(request.title, 120) or ""
    title = title.strip()

    if not 1 <= len(title) <= 120:
        raise HTTPException(status_code=400, detail="Title must be between 1 and 120 characters.")

    analysis_type = _safe_text(request.analysis_type, 50) or ""

    if analysis_type not in SAVED_ANALYSIS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"analysis_type must be one of: {', '.join(SAVED_ANALYSIS_TYPES)}.",
        )

    parameters = request.parameters if isinstance(request.parameters, dict) else {}

    try:
        parameters_json = json.dumps(parameters, default=str, sort_keys=True)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="The analysis parameters could not be serialized.") from e

    if len(parameters_json) > SAVED_ANALYSIS_MAX_PARAM_CHARS:
        raise HTTPException(status_code=400, detail="The analysis parameters are too large to save.")

    try:
        analysis_id = DatasetStore.save_analysis(
            dataset_id,
            current_user,
            title,
            analysis_type,
            parameters_json,
            get_data_version(df),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Analysis could not be saved.") from e

    if not isinstance(analysis_id, str) or not analysis_id:
        raise HTTPException(status_code=500, detail="Analysis save returned an invalid analysis id.")

    return {
        "dataset_id": dataset_id,
        "analysis_id": analysis_id,
        "message": "Analysis saved.",
    }


@router.get("/dataset/{dataset_id}/saved-analyses/{analysis_id}")
def load_saved_analysis(
    dataset_id: str,
    analysis_id: str,
    current_user: str = Depends(require_auth),
):
    """
    Loads a saved analysis configuration. Read-only: the dataset is never changed. The response reports
    whether the data has changed since the analysis was saved, so the user can decide how to proceed.
    """
    import json

    df = get_dataset_or_404(dataset_id, current_user)
    try:
        record = DatasetStore.get_analysis(analysis_id, dataset_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Saved analysis could not be loaded.") from e

    if record is None:
        raise HTTPException(status_code=404, detail="Saved analysis not found")

    if not isinstance(record, dict):
        raise HTTPException(status_code=500, detail="Saved analysis returned an unexpected result.")

    try:
        parameters = json.loads(record.pop("parameters_json") or "{}")
    except (TypeError, ValueError):
        parameters = {}

    if not isinstance(parameters, dict):
        parameters = {}

    record["parameters"] = parameters

    current_version = get_data_version(df)

    return {
        "dataset_id": dataset_id,
        "analysis": record,
        "current_data_version": current_version,
        "is_stale": record.get("data_version") != current_version,
    }


class ShareCreateRequest(BaseModel):
    label: Optional[str] = None
    expires_in_days: int = 30


@router.post("/dataset/{dataset_id}/shares")
def create_dataset_share(
    dataset_id: str,
    request: ShareCreateRequest,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(security_limiter)),
):
    """Owner-only: creates a read-only share link. The plaintext token is returned once and never stored."""
    import datetime

    get_dataset_or_404(dataset_id, current_user)

    try:
        days = int(request.expires_in_days)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=400, detail="expires_in_days must be an integer between 1 and 90.")

    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="expires_in_days must be an integer between 1 and 90.")

    label = str(request.label or "").strip()[:120] or "Read-only link"
    expires_at = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(days=days)).isoformat()

    try:
        share_id, token = DatasetStore.create_share(dataset_id, current_user, label, expires_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Share link could not be created.") from e

    if not isinstance(share_id, str) or not share_id:
        raise HTTPException(status_code=500, detail="Share link creation returned an invalid share id.")

    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=500, detail="Share link creation returned an invalid token.")

    return {
        "share_id": share_id,
        "token": token,
        "share_path": f"/shared/{token}",
        "share_api_path": f"/api/shared/{token}",
        "label": label,
        "expires_at": expires_at,
        "message": "Share link created. Copy it now; it cannot be shown again.",
    }


@router.get("/dataset/{dataset_id}/shares")
def list_dataset_shares(dataset_id: str, current_user: str = Depends(require_auth)):
    """Owner-only: lists active share links. Token material is never returned."""
    get_dataset_or_404(dataset_id, current_user)

    try:
        shares = DatasetStore.list_shares(dataset_id, current_user)
    except Exception:
        shares = []

    if not isinstance(shares, list):
        shares = []

    safe_shares = []
    for share in shares:
        if (
            isinstance(share, dict)
            and isinstance(share.get("share_id"), str)
            and share.get("share_id")
        ):
            safe_shares.append(share)

    return {"dataset_id": dataset_id, "shares": safe_shares}


@router.delete("/dataset/{dataset_id}/shares/{share_id}")
def revoke_dataset_share(dataset_id: str, share_id: str, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(security_limiter))):
    """Owner-only: revokes a share link immediately."""
    get_dataset_or_404(dataset_id, current_user)

    try:
        revoked = DatasetStore.revoke_share(share_id, dataset_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Share link could not be revoked.") from e

    if not revoked:
        raise HTTPException(status_code=404, detail="Share link not found or already revoked")

    return {"share_id": share_id, "message": "Share link revoked."}


@router.get("/shared/{token}")
def get_shared_dataset(token: str, _rl=Depends(rate_limit(share_view_limiter))):
    """
    Public, read-only view of a shared dataset: a bounded preview and a profile summary only.
    No AI features, no quota use, no writes, and no owner account data (email, plan, branding) is returned.
    """
    try:
        resolved = DatasetStore.resolve_share(token)
    except Exception:
        resolved = None

    if not isinstance(resolved, (tuple, list)) or len(resolved) < 2:
        raise HTTPException(status_code=404, detail="This share link is invalid, expired, or revoked.")

    dataset_id = resolved[0]
    owner_user_id = resolved[1]

    try:
        df = DatasetStore.get(dataset_id, owner_user_id)
    except Exception:
        df = None

    if df is None:
        raise HTTPException(status_code=404, detail="This share link is invalid, expired, or revoked.")

    profile = DataProfiler.profile(df)

    safe_profile = {}
    for key in (
        "num_rows",
        "num_columns",
        "numeric_columns",
        "categorical_columns",
        "date_columns",
        "duplicate_rows",
        "health_score",
    ):
        if key in profile:
            safe_profile[key] = profile[key]

    columns_safe = []
    for col in profile.get("columns", []) or []:
        if not isinstance(col, dict):
            continue

        name = _safe_text(col.get("name"), 200)
        inferred_type = _safe_text(col.get("inferred_type"), 100)

        missing_values = _safe_int(col.get("missing_values"), 0)

        missing_percent = _safe_finite_number(col.get("missing_percent"))
        if missing_percent is None:
            missing_percent = 0.0

        unique_values = _safe_int(col.get("unique_values"), 0)

        columns_safe.append(
            {
                "name": name if name is not None else "",
                "inferred_type": inferred_type if inferred_type is not None else "",
                "missing_values": missing_values,
                "missing_percent": missing_percent,
                "unique_values": unique_values,
            }
        )

    safe_profile["columns"] = columns_safe

    filename = DatasetStore.get_filename(dataset_id, owner_user_id) or "Shared dataset"
    if not isinstance(filename, str):
        filename = str(filename)

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    preview = preview[:10]

    return {
        "read_only": True,
        "filename": filename,
        "profile": safe_profile,
        "preview": preview,
    }


@router.get("/dataset/{dataset_id}/audit-log")
def get_audit_log(dataset_id: str, current_user: str = Depends(require_auth)):
    get_dataset_or_404(dataset_id, current_user)  # ownership check

    try:
        log = DatasetStore.get_audit_log(dataset_id)
    except Exception:
        log = []

    if not isinstance(log, list):
        log = []

    safe_log = []
    for entry in log:
        if not isinstance(entry, dict):
            continue

        safe_entry = dict(entry)

        safe_entry.setdefault("action", "")
        safe_entry["action"] = str(safe_entry.get("action") or "")

        if safe_entry.get("column") is not None:
            safe_entry["column"] = str(safe_entry.get("column"))

        safe_entry.setdefault("details", "")
        safe_entry["details"] = str(safe_entry.get("details") or "")

        timestamp = safe_entry.get("timestamp") or safe_entry.get("created_at") or ""
        safe_entry["timestamp"] = str(timestamp)

        safe_log.append(safe_entry)

    return {"dataset_id": dataset_id, "log": safe_log}


@router.post("/dataset/{dataset_id}/duplicate")
def duplicate_dataset(dataset_id: str, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(upload_limiter))):
    try:
        result = DatasetStore.duplicate(dataset_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset could not be duplicated.") from e

    if result is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Dataset duplicate returned an unexpected result.")

    safe_result = dict(result)

    safe_result.setdefault("dataset_id", "")
    safe_result["dataset_id"] = str(safe_result.get("dataset_id") or "")

    safe_result.setdefault("filename", "Duplicated dataset")
    if safe_result.get("filename") is None:
        safe_result["filename"] = "Duplicated dataset"
    else:
        safe_result["filename"] = str(safe_result.get("filename"))

    for key in ("rows", "columns"):
        if key in safe_result:
            safe_result[key] = _safe_int(safe_result.get(key), 0)

    if not safe_result["dataset_id"]:
        raise HTTPException(
            status_code=500,
            detail="Dataset duplicate returned an invalid dataset id.",
        )

    return safe_result


@router.get("/dataset/{dataset_id}/column/{column_name}/summary")
def get_column_summary(dataset_id: str, column_name: str, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)
    if column_name not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{column_name}' not found in dataset")

    series = df[column_name].dropna()
    total = len(df)

    if pd.api.types.is_numeric_dtype(df[column_name]) and not series.empty:
        try:
            return {
                "column": column_name,
                "kind": "numeric",
                "count": int(len(series)),
                "mean": _preview_json_value(round(float(series.mean()), 2)),
                "std": _preview_json_value(round(float(series.std()), 2)) if len(series) > 1 else 0.0,
                "min": _preview_json_value(round(float(series.min()), 2)),
                "q25": _preview_json_value(round(float(series.quantile(0.25)), 2)),
                "median": _preview_json_value(round(float(series.median()), 2)),
                "q75": _preview_json_value(round(float(series.quantile(0.75)), 2)),
                "max": _preview_json_value(round(float(series.max()), 2)),
            }
        except Exception:
            pass

    try:
        vc = series.astype(str).value_counts().head(10)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Column summary could not be generated.") from e

    top_values = []
    try:
        vc_items = vc.items()
    except AttributeError:
        vc_items = []

    for k, v in vc_items:
        try:
            count = int(v)
        except (TypeError, ValueError, OverflowError):
            count = 0

        percent = round((count / total) * 100, 1) if total else 0.0

        top_values.append({
            "value": str(k),
            "count": count,
            "percent": _preview_json_value(percent),
        })

    return {
        "column": column_name,
        "kind": "categorical",
        "count": int(len(series)),
        "top_values": top_values,
    }


class RawSQLRequest(BaseModel):
    sql: str
    new_dataset_name: Optional[str] = None


def _execute_safe_select_sql(df: pd.DataFrame, raw_sql: str) -> Tuple[pd.DataFrame, str]:
    import re
    import sqlite3

    clean_sql = (raw_sql or "").strip().rstrip(";").strip()
    if not clean_sql:
        raise ValueError("SQL query cannot be empty.")
    # String literals, quoted identifiers and comments are removed first, so keywords
    # or semicolons that appear only inside them are not flagged.
    scrubbed_sql = re.sub(
        r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/",
        " ",
        clean_sql,
        flags=re.DOTALL,
    )
    if ";" in scrubbed_sql:
        raise ValueError("Only a single SELECT statement is allowed.")
    if not re.match(r"^(SELECT|WITH)\b", clean_sql, flags=re.IGNORECASE):
        raise ValueError("Only read-only SELECT or WITH queries are allowed.")
    # REPLACE(...) is a harmless string function; only a bare REPLACE keyword is blocked.
    forbidden = re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM)\b|\bREPLACE\b(?!\s*\()",
        scrubbed_sql,
        flags=re.IGNORECASE,
    )
    if forbidden:
        raise ValueError(f"Keyword '{forbidden.group(0).strip().upper()}' is not allowed in read-only SQL mode.")

    import time

    max_rows = 100000
    timeout_seconds = 10

    conn = sqlite3.connect(":memory:")
    try:
        df.to_sql("data", conn, index=False, if_exists="replace")
        deadline = time.monotonic() + timeout_seconds
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        cursor = conn.execute(clean_sql)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        fetched = cursor.fetchmany(max_rows + 1)
        conn.set_progress_handler(None, 0)
        if len(fetched) > max_rows:
            raise ValueError(f"Query returned more than {max_rows} rows. Add a LIMIT clause or a filter.")
        return pd.DataFrame(fetched, columns=columns), clean_sql
    except ValueError:
        raise
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            raise ValueError(f"Query exceeded the {timeout_seconds} second time limit.")
        raise ValueError(f"SQL error: {e}")
    except Exception as e:
        raise ValueError(f"SQL error: {e}")
    finally:
        conn.close()


@router.post("/dataset/{dataset_id}/sql")
def run_custom_sql(dataset_id: str, request: RawSQLRequest, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(sql_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    try:
        result_df, clean_sql = _execute_safe_select_sql(df, request.sql)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not isinstance(result_df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="SQL query returned an unexpected result.")

    preview_df = result_df.head(500)

    try:
        results = to_json_safe_records(preview_df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="SQL results could not be serialized.") from e

    if not isinstance(results, list):
        results = []

    columns = []
    if hasattr(result_df, "columns"):
        columns = [str(c) for c in result_df.columns]

    try:
        total_rows = int(len(result_df))
    except Exception:
        total_rows = len(results) if isinstance(results, list) else 0

    return {
        "dataset_id": dataset_id,
        "generated_sql": clean_sql,
        "total_rows": total_rows,
        "columns": columns,
        "results": results,
    }


@router.post("/dataset/{dataset_id}/sql/save-as-dataset")
def save_sql_as_dataset(
    dataset_id: str,
    request: RawSQLRequest,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(upload_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)
    try:
        result_df, _ = _execute_safe_select_sql(df, request.sql)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not isinstance(result_df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="SQL query returned an unexpected result.")

    if result_df.empty:
        raise HTTPException(status_code=400, detail="Query returned 0 rows; cannot save an empty dataset.")

    if len(result_df.columns) == 0:
        raise HTTPException(status_code=400, detail="Query returned no columns; cannot save an empty dataset.")

    import re

    base_name = str(DatasetStore.get_filename(dataset_id, current_user) or "dataset")
    custom_name = str(request.new_dataset_name or "").strip()
    raw_target = custom_name if custom_name else f"SQL View of {base_name}"

    # Remove control characters and path separators, then keep only the basename.
    raw_target = re.sub(r"[\x00-\x1f\x7f/\\]", "", raw_target)
    raw_target = os.path.basename(raw_target).strip(" .")

    if not raw_target:
        raw_target = "SQL View"

    if not raw_target.lower().endswith(".csv"):
        raw_target = f"{raw_target}.csv"

    # Keep dataset names aligned with the rename endpoint limit.
    if len(raw_target) > 120:
        base = raw_target[:-4][:116].rstrip(" .")
        if not base:
            base = "SQL View"
        raw_target = f"{base}.csv"

    target_name = raw_target

    new_id = DatasetStore.create(result_df, target_name, current_user)
    if not new_id:
        raise HTTPException(status_code=500, detail="Could not save the SQL result as a dataset.")

    return {
        "dataset_id": new_id,
        "filename": target_name,
        "rows": int(len(result_df)),
        "columns": int(len(result_df.columns)),
    }


class NoteRequest(BaseModel):
    note: str


@router.get("/dataset/{dataset_id}/note")
def get_dataset_note(dataset_id: str, current_user: str = Depends(require_auth)):
    get_dataset_or_404(dataset_id, current_user)

    try:
        note = DatasetStore.get_note(dataset_id)
    except Exception:
        note = ""

    if note is None:
        note = ""
    elif not isinstance(note, str):
        note = str(note)

    return {"dataset_id": dataset_id, "note": note}


@router.put("/dataset/{dataset_id}/note")
def save_dataset_note(dataset_id: str, request: NoteRequest, current_user: str = Depends(require_auth)):
    get_dataset_or_404(dataset_id, current_user)

    saved = str(request.note or "").strip()[:MAX_NOTE_LENGTH]

    try:
        DatasetStore.save_note(dataset_id, saved)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Note could not be saved.") from e

    return {"dataset_id": dataset_id, "note": saved}


class RenameDatasetRequest(BaseModel):
    filename: str


@router.patch("/dataset/{dataset_id}")
def rename_dataset(dataset_id: str, request: RenameDatasetRequest, current_user: str = Depends(require_auth)):
    import re

    raw_name = (request.filename or "").strip()

    # Keep a recognized trailing file extension untouched; sanitize only the basename before it.
    extension = ""
    extension_match = re.search(r"\.(csv|xlsx|json|sql)$", raw_name, flags=re.IGNORECASE)
    if extension_match:
        extension = extension_match.group(0)
        raw_name = raw_name[:extension_match.start()]

    base_name = re.sub(r"[\x00-\x1f\x7f]", "", raw_name)
    base_name = re.sub(r"[/\\~$%&*?<>|\"`;:'.]", "", base_name)
    base_name = re.sub(r"([_\-])\1+", r"\1", base_name)
    base_name = os.path.basename(base_name)
    base_name = base_name.strip(" .-")

    if not base_name:
        raise HTTPException(
            status_code=400,
            detail="Dataset name must contain letters, numbers, spaces, underscores or hyphens.",
        )

    clean_name = f"{base_name}{extension}"
    if not 1 <= len(clean_name) <= 120:
        raise HTTPException(status_code=400, detail="Dataset name must be between 1 and 120 characters.")
    try:
        renamed = DatasetStore.rename(dataset_id, current_user, clean_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Dataset could not be renamed.") from e

    if not renamed:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return {"dataset_id": str(dataset_id), "filename": str(clean_name)}


def _attach_safe_methodology(
    result: Any,
    dataset_id: str,
    df: pd.DataFrame,
    endpoint_name: str = "Analysis",
) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{endpoint_name} returned an unexpected result.",
        )

    methodology = result.get("methodology")
    if not isinstance(methodology, dict):
        methodology = {}

    methodology.update(
        {
            "dataset_id": dataset_id,
            "data_version": get_data_version(df),
        }
    )

    result["methodology"] = methodology
    return result


def _schema_info_for_prompt(df: pd.DataFrame, dataset_id: str = "") -> str:
    """
    Builds a richer schema prompt for AI SQL / Python agents.
    Uses deterministic metric-catalog signals so the model sees measures,
    dimensions, time columns, and candidate keys, not only raw column names.
    """
    try:
        profile = DataProfiler.profile(df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    raw_columns = profile.get("columns")
    if not isinstance(raw_columns, list):
        raw_columns = []

    lines = []

    for col in raw_columns[:100]:
        if not isinstance(col, dict):
            continue

        name = _safe_text(col.get("name"), 100)
        if not name:
            continue

        inferred = _safe_text(col.get("inferred_type"), 50) or "unknown"
        lines.append(f"- {name} ({inferred})")

    try:
        catalog = _metric_catalog_for_df(df, dataset_id or "")
    except Exception:
        catalog = {}

    def _catalog_names(value, limit=30):
        names = []

        if not isinstance(value, list):
            return names

        for item in value:
            if isinstance(item, dict):
                name = item.get("name")
            else:
                name = item

            safe = _safe_text(name, 100)

            if safe and safe not in names:
                names.append(safe)

            if len(names) >= limit:
                break

        return names

    if isinstance(catalog, dict):
        measure_names = _catalog_names(catalog.get("measures"))
        dimension_names = _catalog_names(catalog.get("dimensions"))
        time_names = _catalog_names(catalog.get("time_columns"))
        key_names = _catalog_names(catalog.get("candidate_keys"))

        if measure_names:
            lines.append(
                "Candidate measures (numeric business values, not IDs): "
                + ", ".join(measure_names)
            )

        if dimension_names:
            lines.append("Candidate dimensions: " + ", ".join(dimension_names))

        if time_names:
            lines.append("Time columns: " + ", ".join(time_names))

        if key_names:
            lines.append("Candidate unique keys: " + ", ".join(key_names))

    return "\n".join(lines) if lines else "- no usable columns detected"


class QueryRequest(BaseModel):
    question: str


@router.post("/dataset/{dataset_id}/query")
def query_dataset(dataset_id: str, request: QueryRequest, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(llm_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    quota_or_http_429(current_user)
    schema_info = _schema_info_for_prompt(df, dataset_id)

    try:
        sql = SQLAgent.generate_sql(request.question, schema_info)
    except RuntimeError as e:
        refund_quota(current_user)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        refund_quota(current_user)
        raise HTTPException(status_code=500, detail="SQL generation failed. Please try again.") from e

    if not isinstance(sql, str):
        refund_quota(current_user)
        raise HTTPException(status_code=500, detail="SQL generation returned an invalid query.")

    try:
        validate_select_only(sql)
    except ValueError as e:
        refund_quota(current_user)
        raise HTTPException(status_code=400, detail=f"Query rejected: {e} | Generated SQL: {sql}")

    conn = get_connection_with_data(df)
    try:
        results = run_query(conn, sql)
    except Exception as e:
        refund_quota(current_user)
        raise HTTPException(status_code=400, detail=f"Query execution failed: {e} | SQL: {sql}")
    finally:
        conn.close()

    if not isinstance(results, list):
        results = []

    safe_results = []
    for row in results:
        if isinstance(row, dict):
            safe_results.append({str(key): _make_json_safe(value) for key, value in row.items()})
        elif isinstance(row, (list, tuple)):
            safe_results.append(_make_json_safe(list(row)))
        else:
            safe_results.append({"value": _make_json_safe(row)})

    return {
        "dataset_id": str(dataset_id),
        "question": str(request.question or ""),
        "generated_sql": str(sql or ""),
        "results": safe_results,
    }


class AnalysisRequest(BaseModel):
    question: str


@router.post("/dataset/{dataset_id}/analyze")
def analyze_dataset(dataset_id: str, request: AnalysisRequest, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(llm_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    quota_or_http_429(current_user)
    schema_info = _schema_info_for_prompt(df, dataset_id)

    try:
        code = PythonAgent.generate_code(request.question, schema_info)
    except RuntimeError as e:
        refund_quota(current_user)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        refund_quota(current_user)
        raise HTTPException(status_code=500, detail="Code generation failed. Please try again.") from e

    if not isinstance(code, str):
        refund_quota(current_user)
        raise HTTPException(status_code=500, detail="Code generation returned invalid code.")

    try:
        result = PythonAgent.execute_code(code, df)
    except (ValueError, RuntimeError) as e:
        refund_quota(current_user)
        raise HTTPException(status_code=400, detail=f"{e} | Generated code: {code}")
    except Exception as e:
        refund_quota(current_user)
        raise HTTPException(status_code=400, detail=f"Python analysis failed: {e} | Generated code: {code}") from e

    if not isinstance(code, str):
        try:
            code = str(code)
        except Exception:
            code = ""

    if isinstance(result, pd.DataFrame):
        result = to_json_safe_records(result)
    elif isinstance(result, pd.Series):
        result = to_json_safe_records(result.to_frame())
    elif hasattr(result, "item") and not isinstance(result, (str, bytes, dict, list, tuple, set)):
        try:
            result = result.item()
        except (TypeError, ValueError):
            pass

    result = _make_json_safe(result)

    return {
        "dataset_id": str(dataset_id),
        "question": str(request.question or ""),
        "generated_code": code,
        "result": result,
    }


@router.get("/dataset/{dataset_id}/rows")
def get_rows(
    dataset_id: str,
    offset: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = "asc",
    current_user: str = Depends(require_auth),
):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        limit = int(limit)
    except (TypeError, ValueError, OverflowError):
        limit = 20

    try:
        offset = int(offset)
    except (TypeError, ValueError, OverflowError):
        offset = 0

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    working = df
    search_term = ""
    if search is not None:
        search_term = str(search).strip()[:200]

    if search_term:
        mask = df.fillna("").astype(str).apply(
            lambda col: col.str.contains(search_term, case=False, na=False, regex=False)
        ).any(axis=1)
        working = df[mask]

    if sort_by and isinstance(sort_by, str) and sort_by in working.columns:
        sort_direction = str(sort_dir or "asc").strip().lower()
        ascending = sort_direction != "desc"
        try:
            working = working.sort_values(by=sort_by, ascending=ascending, na_position="last")
        except TypeError:
            try:
                working = working.sort_values(
                    by=sort_by, ascending=ascending, na_position="last",
                    key=lambda s: s.astype(str),
                )
            except Exception:
                pass
        except Exception:
            pass

    sliced = working.iloc[offset:offset + limit]
    records = to_json_safe_records(sliced)

    if not isinstance(records, list):
        records = []

    for rec, orig_idx in zip(records, sliced.index):
        if not isinstance(rec, dict):
            continue
        try:
            rec["_row_id"] = int(orig_idx)
        except (TypeError, ValueError, OverflowError):
            rec["_row_id"] = None

    return {
        "dataset_id": dataset_id,
        "total_rows": int(len(working)),
        "offset": offset,
        "limit": limit,
        "rows": records,
    }


@router.get("/dataset/{dataset_id}/pivot")
def get_pivot(
    dataset_id: str,
    group_by: str,
    value_column: str,
    agg: str = "sum",
    split_by: Optional[str] = None,
    current_user: str = Depends(require_auth),
):
    df = get_dataset_or_404(dataset_id, current_user)

    if not isinstance(group_by, str) or not group_by.strip():
        raise HTTPException(status_code=400, detail="group_by is required.")
    if not isinstance(value_column, str) or not value_column.strip():
        raise HTTPException(status_code=400, detail="value_column is required.")

    group_by = group_by.strip()
    value_column = value_column.strip()

    if group_by not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{group_by}' not found in dataset")
    if value_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{value_column}' not found in dataset")

    agg = str(agg or "sum").strip().lower()
    if agg not in VALID_AGGREGATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"agg must be one of: {', '.join(sorted(VALID_AGGREGATIONS))}.",
        )

    split_by_value = None
    if isinstance(split_by, str):
        cleaned_split = split_by.strip()
        if cleaned_split:
            if cleaned_split not in df.columns:
                raise HTTPException(status_code=400, detail=f"Column '{cleaned_split}' not found in dataset")
            split_by_value = cleaned_split

    try:
        result = ChartEngine.pivot_summary(df, group_by, value_column, agg, split_by_value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Pivot could not be generated.") from e

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Pivot returned an unexpected result.")

    raw_columns = result.get("columns")
    raw_rows = result.get("rows")

    if not isinstance(raw_columns, list):
        raw_columns = []
    if not isinstance(raw_rows, list):
        raw_rows = []

    columns = [str(col) for col in raw_columns if col is not None]

    rows = []
    for row in raw_rows:
        if isinstance(row, dict):
            rows.append(row)

    result["columns"] = columns
    result["rows"] = rows

    return {"dataset_id": dataset_id, **result}


@router.get("/dataset/{dataset_id}/chart")
def get_chart(dataset_id: str, x_column: Optional[str] = None, y_column: Optional[str] = None, agg: str = "sum", current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    if x_column is not None:
        x_column = str(x_column).strip() or None
    if y_column is not None:
        y_column = str(y_column).strip() or None

    if x_column and x_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{x_column}' not found in dataset")
    if y_column and y_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{y_column}' not found in dataset")

    agg = str(agg or "sum").strip().lower()
    if agg not in VALID_AGGREGATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"agg must be one of: {', '.join(sorted(VALID_AGGREGATIONS))}.",
        )

    try:
        chart = ChartEngine.suggest_chart(df, x_column, y_column, agg=agg)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Chart could not be generated.") from e

    if not isinstance(chart, dict):
        raise HTTPException(status_code=500, detail="Chart returned an unexpected result.")

    chart.setdefault("chart_type", "table")
    chart.setdefault("x_column", None)
    chart.setdefault("y_column", None)
    chart.setdefault("agg", agg)

    raw_data = chart.get("data")
    if not isinstance(raw_data, list):
        raw_data = []

    chart["data"] = [item for item in raw_data if isinstance(item, dict)]

    return {"dataset_id": dataset_id, **chart}


@router.get("/dataset/{dataset_id}/chart/histogram")
def get_histogram(dataset_id: str, column: str, bins: int = 10, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)
    if column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{column}' not found in dataset")

    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 2 or bins > 100:
        raise HTTPException(status_code=400, detail="bins must be an integer between 2 and 100.")

    source_df = df

    if not pd.api.types.is_numeric_dtype(df[column]):
        try:
            converted = pd.to_numeric(df[column], errors="coerce")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Column '{column}' is not numeric.") from e

        if converted.dropna().empty:
            raise HTTPException(status_code=400, detail=f"Column '{column}' does not contain numeric values.")

        source_df = df.copy()
        source_df[column] = converted

    try:
        chart = ChartEngine.histogram(source_df, column, bins)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Histogram could not be generated.") from e

    if not isinstance(chart, dict):
        raise HTTPException(status_code=500, detail="Histogram returned an unexpected result.")

    chart.setdefault("chart_type", "histogram")
    chart.setdefault("column", column)

    raw_data = chart.get("data")
    if not isinstance(raw_data, list):
        raw_data = []

    chart["data"] = [item for item in raw_data if isinstance(item, dict)]

    return {"dataset_id": dataset_id, **chart}


@router.get("/dataset/{dataset_id}/kpis")
def get_kpis(dataset_id: str, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        methodology = ChartEngine.kpi_methodology(df)
    except Exception:
        methodology = {}

    if not isinstance(methodology, dict):
        methodology = {}

    methodology.update({"dataset_id": dataset_id, "data_version": get_data_version(df)})

    try:
        kpis = ChartEngine.kpi_cards(df)
    except Exception:
        kpis = []

    if not isinstance(kpis, list):
        kpis = []

    return {"dataset_id": dataset_id, "kpis": kpis, "methodology": methodology}


@router.get("/dataset/{dataset_id}/correlation")
def get_correlation(dataset_id: str, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        result = ChartEngine.correlation_matrix(df)
    except Exception:
        result = {}

    if not isinstance(result, dict):
        result = {}

    columns = result.get("columns")
    matrix = result.get("matrix")

    if not isinstance(columns, list):
        columns = []
    if not isinstance(matrix, list):
        matrix = []

    def _sanitize_correlation_row(row_values):
        return [_safe_finite_number(value) for value in row_values]

    sanitized_matrix = []
    column_count = len(columns)

    for row in matrix:
        if isinstance(row, list):
            if len(row) < column_count:
                row = row + [None] * (column_count - len(row))
            elif len(row) > column_count:
                row = row[:column_count]
            sanitized_matrix.append(_sanitize_correlation_row(row))
        elif isinstance(row, dict):
            sanitized_matrix.append(_sanitize_correlation_row([row.get(col) for col in columns]))
        else:
            sanitized_matrix.append([None] * column_count)

    if len(sanitized_matrix) < column_count:
        sanitized_matrix.extend(
            [[None] * column_count for _ in range(column_count - len(sanitized_matrix))]
        )
    elif len(sanitized_matrix) > column_count:
        sanitized_matrix = sanitized_matrix[:column_count]

    safe_result = dict(result)
    safe_result["columns"] = columns
    safe_result["matrix"] = sanitized_matrix

    return {"dataset_id": dataset_id, **safe_result}


@router.get("/compare")
def compare_datasets(dataset_id_a: str, dataset_id_b: str, current_user: str = Depends(require_auth)):
    df_a = get_dataset_or_404(dataset_id_a, current_user)
    df_b = get_dataset_or_404(dataset_id_b, current_user)

    try:
        profile_a = DataProfiler.profile(df_a)
    except Exception:
        profile_a = {}
    if not isinstance(profile_a, dict):
        profile_a = {}

    try:
        kpis_a = ChartEngine.kpi_cards(df_a)
    except Exception:
        kpis_a = []
    if not isinstance(kpis_a, list):
        kpis_a = []

    try:
        profile_b = DataProfiler.profile(df_b)
    except Exception:
        profile_b = {}
    if not isinstance(profile_b, dict):
        profile_b = {}

    try:
        kpis_b = ChartEngine.kpi_cards(df_b)
    except Exception:
        kpis_b = []
    if not isinstance(kpis_b, list):
        kpis_b = []

    filename_a = DatasetStore.get_filename(dataset_id_a, current_user) or "Dataset A"
    if not isinstance(filename_a, str):
        filename_a = str(filename_a)

    filename_b = DatasetStore.get_filename(dataset_id_b, current_user) or "Dataset B"
    if not isinstance(filename_b, str):
        filename_b = str(filename_b)

    return {
        "a": {
            "dataset_id": dataset_id_a,
            "filename": filename_a,
            "profile": profile_a,
            "kpis": kpis_a,
        },
        "b": {
            "dataset_id": dataset_id_b,
            "filename": filename_b,
            "profile": profile_b,
            "kpis": kpis_b,
        },
    }


class InsightRequest(BaseModel):
    focus_question: Optional[str] = None


@router.post("/dataset/{dataset_id}/insights")
def get_insights(dataset_id: str, request: InsightRequest = InsightRequest(), current_user: str = Depends(require_auth), _rl=Depends(rate_limit(llm_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    try:
        result = cached_ai_call(
            dataset_id, current_user, "insight", {"q": request.focus_question}, df,
            lambda: InsightAgent.generate_insight(df, request.focus_question),
        )
    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        result = {"insight": None}

    if not isinstance(result, dict):
        result = {"insight": None}

    safe_result = {}
    for key, value in result.items():
        if key == "insight":
            if value is None:
                safe_result[key] = None
            elif isinstance(value, str):
                safe_result[key] = value
            else:
                try:
                    safe_result[key] = str(value)
                except Exception:
                    safe_result[key] = None
        else:
            safe_result[key] = _make_json_safe(value)

    return {"dataset_id": str(dataset_id), **safe_result}


@router.get("/dataset/{dataset_id}/cleaning-advice")
def get_cleaning_advice(dataset_id: str, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(llm_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    try:
        result = cached_ai_call(
            dataset_id, current_user, "cleaning_advice", {}, df,
            lambda: CleaningAgent.advise(df),
        )
    except QuotaExceeded as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        result = {"advice": None}

    if not isinstance(result, dict):
        result = {"advice": None}

    safe_result = {}
    for key, value in result.items():
        if key == "advice":
            if value is None:
                safe_result[key] = None
            elif isinstance(value, str):
                safe_result[key] = value
            else:
                try:
                    safe_result[key] = str(value)
                except Exception:
                    safe_result[key] = None
        else:
            safe_result[key] = _make_json_safe(value)

    return {"dataset_id": str(dataset_id), **safe_result}


@router.get("/dataset/{dataset_id}/anomalies")
def get_anomalies(
    dataset_id: str,
    explain: bool = True,
    method: str = "zscore",
    threshold: float = 2.5,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(llm_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)

    method = str(method or "zscore").strip().lower()
    if method not in ("zscore", "iqr"):
        raise HTTPException(status_code=400, detail="method must be 'zscore' or 'iqr'.")

    try:
        threshold = float(threshold)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=400, detail="threshold must be a number between 0.1 and 10.")

    if not (0.1 <= threshold <= 10.0):
        raise HTTPException(status_code=400, detail="threshold must be a number between 0.1 and 10.")

    try:
        anomalies = AnomalyDetector.detect(df, z_threshold=threshold, method=method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Anomaly detection failed.") from e

    if not isinstance(anomalies, dict):
        raise HTTPException(status_code=500, detail="Anomaly detection returned an unexpected result.")

    try:
        anomaly_methodology = AnomalyDetector.describe_methodology(df, method=method, z_threshold=threshold)
    except Exception:
        anomaly_methodology = {}

    if not isinstance(anomaly_methodology, dict):
        anomaly_methodology = {}

    anomaly_methodology.update({"dataset_id": dataset_id, "data_version": get_data_version(df)})

    anomalies = _make_json_safe(anomalies)
    if not isinstance(anomalies, dict):
        anomalies = {}

    numeric_outliers = anomalies.get("numeric_outliers")
    category_anomalies = anomalies.get("category_anomalies")

    if not isinstance(numeric_outliers, list):
        numeric_outliers = []
    if not isinstance(category_anomalies, list):
        category_anomalies = []

    anomalies["numeric_outliers"] = numeric_outliers
    anomalies["category_anomalies"] = category_anomalies

    response = {
        "dataset_id": str(dataset_id),
        "anomalies": anomalies,
        "methodology": _make_json_safe(anomaly_methodology),
    }

    if explain and (numeric_outliers or category_anomalies):
        try:
            result = cached_ai_call(
                dataset_id, current_user, "anomaly_explanation", {"method": method, "threshold": threshold}, df,
                lambda: InsightAgent.explain_anomalies(anomalies),
            )
            explanation = result.get("explanation") if isinstance(result, dict) else None
            if explanation is None:
                response["explanation"] = None
            elif isinstance(explanation, str):
                response["explanation"] = explanation
            else:
                try:
                    response["explanation"] = str(explanation)
                except Exception:
                    response["explanation"] = None
        except QuotaExceeded as e:
            response["explanation"] = f"(AI explanation unavailable: {e})"
        except RuntimeError as e:
            response["explanation"] = f"(Explanation unavailable: {e})"

    return response


@router.get("/dataset/{dataset_id}/root-cause")
def get_root_cause(
    dataset_id: str,
    metric_column: str,
    dimension_columns: Optional[str] = None,
    exclude_columns: Optional[str] = None,
    question: Optional[str] = None,
    explain: bool = True,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(llm_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)
    if metric_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{metric_column}' not found in dataset")

    dims = [d.strip() for d in dimension_columns.split(",") if d.strip()] if dimension_columns else None
    excluded_dims = [d.strip() for d in exclude_columns.split(",") if d.strip()] if exclude_columns else None

    try:
        breakdown = VarianceAnalyzer.analyze_dimensions(
            df, metric_column, dims or None, exclude_columns=excluded_dims
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not isinstance(breakdown, list):
        breakdown = []

    safe_breakdown = []
    for item in breakdown:
        if isinstance(item, dict):
            safe_breakdown.append(_make_json_safe(item))

    breakdown = safe_breakdown

    try:
        root_cause_methodology = VarianceAnalyzer.describe_methodology(
            df, metric_column, dims or None, excluded_dims or None
        )
    except Exception:
        root_cause_methodology = {}

    response = {
        "dataset_id": str(dataset_id),
        "metric_column": str(metric_column or ""),
        "breakdown": breakdown,
        "methodology": root_cause_methodology,
    }

    response = _attach_safe_methodology(response, dataset_id, df, endpoint_name="Root cause")
    response["methodology"] = _make_json_safe(response.get("methodology"))

    if explain and breakdown:
        try:
            result = cached_ai_call(
                dataset_id, current_user, "root_cause",
                {"metric": metric_column, "dims": dimension_columns, "ex": exclude_columns, "q": question}, df,
                lambda: InsightAgent.explain_root_cause(metric_column, breakdown, question),
            )
            explanation = result.get("explanation") if isinstance(result, dict) else None
            if explanation is None:
                response["explanation"] = None
            elif isinstance(explanation, str):
                response["explanation"] = explanation
            else:
                try:
                    response["explanation"] = str(explanation)
                except Exception:
                    response["explanation"] = None
        except QuotaExceeded as e:
            response["explanation"] = f"(AI explanation unavailable: {e})"
        except RuntimeError as e:
            response["explanation"] = f"(Explanation unavailable: {e})"

    return response


@router.get("/dataset/{dataset_id}/forecast")
def get_forecast(dataset_id: str, date_column: str, value_column: str, periods: int = 3, current_user: str = Depends(require_auth)):
    df = get_dataset_or_404(dataset_id, current_user)

    date_column = str(date_column or "").strip()
    value_column = str(value_column or "").strip()

    if not date_column:
        raise HTTPException(status_code=400, detail="date_column is required.")
    if not value_column:
        raise HTTPException(status_code=400, detail="value_column is required.")

    if date_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{date_column}' not found in dataset")
    if value_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{value_column}' not found in dataset")

    try:
        periods = int(periods)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(status_code=400, detail="periods must be an integer between 1 and 120.")

    if periods < 1 or periods > 120:
        raise HTTPException(status_code=400, detail="periods must be an integer between 1 and 120.")

    try:
        result = Forecaster.forecast(df, date_column, value_column, periods)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Forecast could not be generated.") from e

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Forecast returned an unexpected result.")

    methodology = result.get("methodology")
    if not isinstance(methodology, dict):
        methodology = {}

    methodology.update({"dataset_id": dataset_id, "data_version": get_data_version(df)})
    result["methodology"] = methodology

    return {"dataset_id": dataset_id, **result}


class ChatRequest(BaseModel):
    message: str


@router.post("/dataset/{dataset_id}/chat")
def chat_with_data(dataset_id: str, request: ChatRequest, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(llm_limiter))):
    df = get_dataset_or_404(dataset_id, current_user)
    quota_or_http_429(current_user)

    try:
        result = Orchestrator.handle_message(dataset_id, df, request.message)
    except Exception:
        refund_quota(current_user)
        result = {
            "action": "insight",
            "reply": "Sorry, something went wrong. Please try again.",
            "result": {"error": "orchestrator_exception"},
        }

    if not isinstance(result, dict):
        result = {
            "action": "insight",
            "reply": "Sorry, something went wrong. Please try again.",
            "result": {"error": "invalid_response"},
        }

    response = {"dataset_id": str(dataset_id), **result}
    response.setdefault("action", None)
    response.setdefault("reply", "Sorry, something went wrong. Please try again.")
    response.setdefault("result", None)

    action = response.get("action")
    if action is not None and not isinstance(action, str):
        try:
            response["action"] = str(action)
        except Exception:
            response["action"] = None

    reply = response.get("reply")
    if reply is None:
        response["reply"] = "Sorry, something went wrong. Please try again."
    elif not isinstance(reply, str):
        try:
            response["reply"] = str(reply)
        except Exception:
            response["reply"] = "Sorry, something went wrong. Please try again."

    response["result"] = _make_json_safe(response.get("result"))

    # A failed answer shouldn't cost the user one of their daily requests.
    if isinstance(response.get("result"), dict) and "error" in response["result"]:
        refund_quota(current_user)

    return response


@router.post("/dataset/{dataset_id}/chat/reset")
def reset_chat(dataset_id: str, current_user: str = Depends(require_auth), _rl=Depends(rate_limit(write_limiter))):
    get_dataset_or_404(dataset_id, current_user)  # ownership check
    Orchestrator.reset_conversation(dataset_id)
    return {"dataset_id": dataset_id, "message": "Conversation history cleared."}


def _safe_report_file_response(file_path: Any, media_type: str, fallback_name: str) -> FileResponse:
    if not isinstance(file_path, str) or not file_path:
        raise HTTPException(status_code=500, detail="Report generation returned an invalid file path.")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=500, detail="Report file could not be found.")

    filename = os.path.basename(file_path) or fallback_name
    return FileResponse(path=file_path, filename=filename, media_type=media_type)


@router.get("/dataset/{dataset_id}/report")
def get_report(
    dataset_id: str,
    format: str = "pdf",
    include_ai_sections: bool = True,
    include_deterministic_summary: bool = True,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(report_limiter)),
):
    """
    Generates a downloadable report (PDF, Excel, or PPTX). PDF/PPTX reports
    automatically include the user's embedded chart and custom branding
    (logo, accent color) if their plan is premium and they've set any up.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    # Sweep expired report files before generating a new one (files still streaming are far younger than the window).
    try:
        cleanup_old_reports()
    except Exception:
        pass

    if format not in ("pdf", "excel", "xlsx", "pptx", "json", "sql", "csv"):
        raise HTTPException(status_code=400, detail="format must be 'pdf', 'excel', 'xlsx', 'pptx', 'json', 'sql', or 'csv'")

    if format == "csv":
        file_path = ReportGenerator.generate_csv(df, dataset_id)
        return _safe_report_file_response(file_path, "text/csv", "report.csv")

    if format in ("excel", "xlsx"):
        file_path = ReportGenerator.generate_excel(df, dataset_id)
        return _safe_report_file_response(
            file_path,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "report.xlsx",
        )

    if format == "json":
        if UserStore.get_plan(current_user) != "premium":
            raise HTTPException(status_code=403, detail="JSON export requires a Premium plan.")
        file_path = ReportGenerator.generate_json(df, dataset_id)
        return _safe_report_file_response(file_path, "application/json", "report.json")

    if format == "sql":
        if UserStore.get_plan(current_user) != "premium":
            raise HTTPException(status_code=403, detail="SQL export requires a Premium plan.")
        file_path = ReportGenerator.generate_sql_script(df, dataset_id)
        return _safe_report_file_response(file_path, "application/sql", "report.sql")

    is_premium = UserStore.get_plan(current_user) == "premium"

    executive_summary = None
    anomaly_summary = None
    chart_image_bytes = None
    logo_bytes = None
    accent_color = None
    recommendations = None
    forecast_summary = None

    profile_info = DataProfiler.profile(df)
    if not isinstance(profile_info, dict):
        profile_info = {}

    date_cols = profile_info.get("date_columns") or []
    metric_cols = [
        c
        for c in (profile_info.get("numeric_columns") or [])
        if not ChartEngine.is_identifier_name(c)
    ]
    if date_cols and metric_cols:
        try:
            fc = Forecaster.forecast(df, date_cols[0], metric_cols[0], periods=3)

            if isinstance(fc, dict):
                forecast_points = fc.get("forecast")
                if not isinstance(forecast_points, list):
                    forecast_points = []

                forecast_lines = []
                for p in forecast_points:
                    if not isinstance(p, dict):
                        continue
                    forecast_lines.append(
                        f"{p.get('date')}: {p.get('predicted_value')} "
                        f"(range {p.get('lower_bound')} to {p.get('upper_bound')})"
                    )

                forecast_summary = (
                    f"Trend for '{metric_cols[0]}' over '{date_cols[0]}' is {fc.get('trend_direction', 'unknown')}. "
                    "Next forecasted values: "
                    + ", ".join(forecast_lines)
                )
            else:
                forecast_summary = None
        except Exception:
            forecast_summary = None

    if include_ai_sections and format in ("pdf", "pptx"):
        try:
            recommendation_result = cached_ai_call(
                dataset_id, current_user, "report_recommendations", {}, df,
                lambda: ReportAgent.generate_recommendations(df),
            )
            recommendations = (
                recommendation_result.get("recommendations")
                if isinstance(recommendation_result, dict)
                else None
            )
        except (QuotaExceeded, RuntimeError):
            recommendations = None
        except Exception:
            recommendations = None

        try:
            insight_result = cached_ai_call(
                dataset_id, current_user, "insight", {"q": None}, df,
                lambda: InsightAgent.generate_insight(df),
            )
            executive_summary = (
                insight_result.get("insight")
                if isinstance(insight_result, dict)
                else None
            )
        except (QuotaExceeded, RuntimeError):
            executive_summary = None
        except Exception:
            executive_summary = None

        try:
            anomalies = AnomalyDetector.detect(df, z_threshold=2.5, method="zscore")
            if not isinstance(anomalies, dict):
                anomalies = {}

            numeric_outliers = anomalies.get("numeric_outliers") or []
            category_anomalies = anomalies.get("category_anomalies") or []

            if numeric_outliers or category_anomalies:
                anomaly_result = cached_ai_call(
                    dataset_id, current_user, "anomaly_explanation", {}, df,
                    lambda: InsightAgent.explain_anomalies(anomalies),
                )
                anomaly_summary = (
                    anomaly_result.get("explanation")
                    if isinstance(anomaly_result, dict)
                    else None
                )
        except (QuotaExceeded, RuntimeError):
            anomaly_summary = None
        except Exception:
            anomaly_summary = None

    deterministic_executive_summary = False
    deterministic_quality = None

    if include_deterministic_summary and not executive_summary:
        try:
            narrative = _narrative_summary_for_df(df, dataset_id)
            if isinstance(narrative, dict):
                executive_summary = narrative.get("summary")

                quality_payload = narrative.get("quality")
                if isinstance(quality_payload, dict):
                    deterministic_quality = quality_payload

                deterministic_executive_summary = True
        except Exception:
            executive_summary = None

    executive_summary = _safe_text(executive_summary, 5000)

    if deterministic_executive_summary and executive_summary:
        quality_lines = []

        if isinstance(deterministic_quality, dict):
            rows = _safe_int(deterministic_quality.get("row_count"), 0)
            cols = _safe_int(deterministic_quality.get("column_count"), 0)
            health = _safe_finite_number(deterministic_quality.get("health_score"))
            completeness = _safe_finite_number(deterministic_quality.get("completeness_percent"))
            missing = _safe_int(deterministic_quality.get("missing_cells"), 0)
            duplicates = _safe_int(deterministic_quality.get("duplicate_rows"), 0)
            issues = _safe_int(deterministic_quality.get("total_issue_count"), 0)

            quality_lines.append(f"Rows: {rows}, Columns: {cols}")

            if health is not None:
                quality_lines.append(f"Health score: {health:.2f}/100")

            if completeness is not None:
                quality_lines.append(f"Completeness: {completeness:.2f}%")

            quality_lines.append(f"Missing cells: {missing}")
            quality_lines.append(f"Duplicate rows: {duplicates}")
            quality_lines.append(f"Detected issue count: {issues}")

            primary_keys = deterministic_quality.get("primary_key_candidates")
            if isinstance(primary_keys, list) and primary_keys:
                quality_lines.append(
                    "Primary key candidates: "
                    + ", ".join(str(x) for x in primary_keys[:5])
                )

            freshness = deterministic_quality.get("freshness")
            if isinstance(freshness, dict) and freshness.get("latest_date"):
                quality_lines.append(
                    f"Latest date: {freshness.get('latest_date')} "
                    f"in column '{freshness.get('latest_date_column')}'"
                )

        suffix = ""
        if quality_lines:
            suffix = "\n\nDeterministic quality snapshot:\n" + "\n".join(quality_lines)

        executive_summary = _safe_text(
            "Deterministic summary (rule-based, not AI-generated):\n"
            + executive_summary
            + suffix,
            8000,
        )
    recommendations = _safe_text(recommendations, 10000)
    anomaly_summary = _safe_text(anomaly_summary, 5000)
    forecast_summary = _safe_text(forecast_summary, 5000)

    if is_premium:
        try:
            chart_image_bytes = ChartImageExporter.render(df)
        except Exception:
            chart_image_bytes = None

        if chart_image_bytes is not None and not isinstance(chart_image_bytes, (bytes, bytearray)):
            chart_image_bytes = None
        elif isinstance(chart_image_bytes, bytearray):
            chart_image_bytes = bytes(chart_image_bytes)

        branding = UserStore.get_branding(current_user)
        if not isinstance(branding, dict):
            branding = {}

        logo_bytes = branding.get("logo_bytes")
        if logo_bytes is not None and not isinstance(logo_bytes, (bytes, bytearray)):
            logo_bytes = None
        elif isinstance(logo_bytes, bytearray):
            logo_bytes = bytes(logo_bytes)

        accent_color = branding.get("accent_color")
        if accent_color is not None:
            accent_color = str(accent_color).strip()
            if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", accent_color):
                accent_color = None

    if format == "pptx":
        file_path = ReportGenerator.generate_pptx(
            df, dataset_id,
            executive_summary=executive_summary,
            recommendations=recommendations,
            anomaly_summary=anomaly_summary,
            forecast_summary=forecast_summary,
            chart_image_bytes=chart_image_bytes,
            logo_bytes=logo_bytes,
            accent_color=accent_color,
            display_name=DatasetStore.get_filename(dataset_id, current_user),
        )
        return _safe_report_file_response(
            file_path,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "report.pptx",
        )

    file_path = ReportGenerator.generate_pdf(
        df, dataset_id,
        display_name=DatasetStore.get_filename(dataset_id, current_user),
        executive_summary=executive_summary,
        anomaly_summary=anomaly_summary,
        chart_image_bytes=chart_image_bytes,
        logo_bytes=logo_bytes,
        accent_color=accent_color,
        recommendations=recommendations,
        forecast_summary=forecast_summary,
    )
    return _safe_report_file_response(file_path, "application/pdf", "report.pdf")
@router.get("/dataset/{dataset_id}/chat/history")
def get_chat_history(dataset_id: str, current_user: str = Depends(require_auth)):
    """Returns the full persisted chat history for this dataset, for the frontend to load on page open."""
    get_dataset_or_404(dataset_id, current_user)  # ownership check

    history = Orchestrator.get_full_history(dataset_id)
    if not isinstance(history, list):
        history = []

    safe_history = []
    for turn in history:
        if isinstance(turn, dict):
            safe_history.append(
                {
                    "role": turn.get("role", "assistant"),
                    "content": turn.get("content", ""),
                    "action": turn.get("action"),
                    "result": turn.get("result"),
                }
            )

    return {"dataset_id": dataset_id, "history": safe_history}

# ---------- Premium: High-Resolution Chart Export ----------

@router.get("/dataset/{dataset_id}/chart/export")
def export_chart_image(
    dataset_id: str,
    x_column: Optional[str] = None,
    y_column: Optional[str] = None,
    date_column: Optional[str] = None,
    value_column: Optional[str] = None,
    format: str = "png",
    granularity: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    agg: str = "sum",
    ma_window: int = 0,
    current_user: str = Depends(require_premium),
    _rl=Depends(rate_limit(export_limiter)),
):
    """
    Premium feature: downloads a print-quality chart image (PNG, SVG, or
    PDF — PDF is vector, so it stays sharp at any zoom/print size) of
    either the auto-suggested chart, or, when granularity is given, the
    exact drilled-down time-series view the user is currently looking at
    (which uses date_column/value_column instead of x_column/y_column).
    """
    if format not in ("png", "svg", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'png', 'svg', or 'pdf'")

    df = get_dataset_or_404(dataset_id, current_user)

    note = DatasetStore.get_note(dataset_id)
    if note is None:
        note = ""
    elif not isinstance(note, str):
        note = str(note)

    try:
        if granularity:
            if not date_column or not value_column:
                raise HTTPException(status_code=400, detail="date_column and value_column are required for a time series export")
            try:
                ma_window = int(ma_window)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="ma_window must be an integer.")
            if ma_window < 0 or ma_window > 365:
                raise HTTPException(status_code=400, detail="ma_window must be between 0 and 365.")

            safe_note = note.strip()[:500] or None
            image_bytes = ChartImageExporter.render_timeseries(
                df, date_column, value_column, granularity, start, end, fmt=format,
                note=safe_note, ma_window=ma_window,
            )
        else:
            image_bytes = ChartImageExporter.render(df, x_column, y_column, fmt=format, agg=agg)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Chart export failed. Please try again.") from e

    if not isinstance(image_bytes, (bytes, bytearray)):
        raise HTTPException(status_code=500, detail="Chart export returned an unexpected result.")

    if isinstance(image_bytes, bytearray):
        image_bytes = bytes(image_bytes)

    media_types = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}
    return Response(
        content=image_bytes,
        media_type=media_types[format],
        headers={"Content-Disposition": f"attachment; filename=chart.{format}"},
    )

# ---------- Premium: Time Series Explorer (drill-down zoom) ----------

@router.get("/dataset/{dataset_id}/chart/timeseries")
def get_timeseries_chart(
    dataset_id: str,
    date_column: str,
    value_column: str,
    granularity: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    current_user: str = Depends(require_premium),
):
    """
    Premium feature: a drill-down-ready time series (year -> month -> week
    -> day -> hour) for charting on the frontend, with click-to-zoom.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    if date_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{date_column}' not found in dataset")
    if value_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{value_column}' not found in dataset")
    if granularity and granularity not in TIME_GRANULARITY_LEVELS:
        raise HTTPException(status_code=400, detail=f"granularity must be one of {TIME_GRANULARITY_LEVELS}")

    try:
        result = ChartEngine.time_series_chart(df, date_column, value_column, granularity, start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Time series could not be generated.") from e

    _attach_safe_methodology(result, dataset_id, df, endpoint_name="Time series")

    return {"dataset_id": dataset_id, **result}

# ---------- Premium: Custom Branding ----------

class BrandingRequest(BaseModel):
    accent_color: Optional[str] = None  # hex like "#2B4C7E"


@router.post("/branding/logo")
async def upload_logo(file: UploadFile = File(...), current_user: str = Depends(require_premium)):
    """Premium feature: uploads a company/college logo to be embedded in PDF reports."""
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo must be under 2MB.")

    import io
    from PIL import Image

    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format
            image.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid image.")
    if image_format not in ("PNG", "JPEG"):
        raise HTTPException(status_code=400, detail="Logo must be a PNG or JPEG image.")

    UserStore.set_branding(current_user, logo_bytes=content)
    return {"message": "Logo uploaded."}


@router.post("/branding/color")
def set_brand_color(request: BrandingRequest, current_user: str = Depends(require_premium)):
    """Premium feature: sets a brand accent color (hex) for PDF report headings."""
    UserStore.set_branding(current_user, accent_color=request.accent_color)
    return {"message": "Brand color updated."}


@router.get("/branding")
def get_branding_info(current_user: str = Depends(require_auth)):
    """Returns whether a logo/color is set (not the raw bytes) — the frontend uses this to show current branding state."""
    try:
        branding = UserStore.get_branding(current_user)
    except Exception:
        branding = {}

    if not isinstance(branding, dict):
        branding = {}

    logo_bytes = branding.get("logo_bytes")
    accent_color = branding.get("accent_color")

    if accent_color is not None and not isinstance(accent_color, str):
        accent_color = str(accent_color)

    return {
        "has_logo": logo_bytes is not None,
        "accent_color": accent_color,
    }

# ---------- Premium: Scheduled & Automated Exports ----------

class ScheduleRequest(BaseModel):
    dataset_id: str
    format: str
    frequency: str  # "weekly" | "monthly"
    destination_type: str  # "email" | "webhook"
    destination: str


@router.post("/schedules")
def create_schedule(request: ScheduleRequest, current_user: str = Depends(require_premium)):
    get_dataset_or_404(request.dataset_id, current_user)  # ownership check

    allowed_formats = {"pdf", "excel", "xlsx", "pptx", "csv", "json", "sql"}
    allowed_frequencies = {"weekly", "monthly"}
    allowed_destination_types = {"email", "webhook"}

    request_format = str(request.format or "").strip().lower()
    frequency = str(request.frequency or "").strip().lower()
    destination_type = str(request.destination_type or "").strip().lower()
    destination = str(request.destination or "").strip()

    if request_format not in allowed_formats:
        raise HTTPException(
            status_code=400,
            detail=f"format must be one of: {', '.join(sorted(allowed_formats))}.",
        )

    if frequency not in allowed_frequencies:
        raise HTTPException(
            status_code=400,
            detail=f"frequency must be one of: {', '.join(sorted(allowed_frequencies))}.",
        )

    if destination_type not in allowed_destination_types:
        raise HTTPException(
            status_code=400,
            detail=f"destination_type must be one of: {', '.join(sorted(allowed_destination_types))}.",
        )

    if not destination:
        raise HTTPException(status_code=400, detail="destination is required.")

    if destination_type == "email":
        try:
            account = UserStore.get_user(current_user)
        except Exception as e:
            raise HTTPException(status_code=500, detail="Could not verify account email. Please try again.") from e

        if not isinstance(account, dict) or not account:
            raise HTTPException(status_code=404, detail="User not found")

        if not account.get("email_verified"):
            raise HTTPException(
                status_code=400,
                detail="Verify your email address before scheduling email exports.",
            )

        account_email = str(account.get("email") or "").strip().lower()
        if not account_email:
            raise HTTPException(status_code=400, detail="Account email is missing. Please contact support.")

        if destination.lower() != account_email:
            raise HTTPException(
                status_code=400,
                detail="Scheduled reports can only be emailed to your own account email address.",
            )

    try:
        schedule_id = ScheduleStore.create(
            current_user,
            request.dataset_id,
            request_format,
            frequency,
            destination_type,
            destination,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Schedule could not be created.") from e

    if not isinstance(schedule_id, str) or not schedule_id:
        raise HTTPException(status_code=500, detail="Schedule creation returned an invalid schedule id.")

    return {"schedule_id": schedule_id, "message": "Schedule created."}


@router.get("/schedules")
def list_schedules(current_user: str = Depends(require_premium)):
    try:
        schedules = ScheduleStore.list_for_user(current_user)
    except Exception:
        schedules = []

    if not isinstance(schedules, list):
        schedules = []

    safe_schedules = []
    for schedule in schedules:
        if (
            isinstance(schedule, dict)
            and isinstance(schedule.get("schedule_id"), str)
            and schedule.get("schedule_id")
        ):
            safe_schedules.append(schedule)

    return {"schedules": safe_schedules}


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, current_user: str = Depends(require_premium)):
    try:
        deleted = ScheduleStore.delete(schedule_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Schedule could not be deleted.") from e

    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return {"message": "Schedule deleted."}


@router.post("/schedules/{schedule_id}/run-now")
def run_schedule_now(schedule_id: str, current_user: str = Depends(require_premium), _rl=Depends(rate_limit(report_limiter))):
    """Manually triggers a schedule immediately, for testing without waiting for the real interval."""
    schedule = ScheduleStore.get(schedule_id, current_user)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not isinstance(schedule, dict):
        raise HTTPException(status_code=500, detail="Schedule returned an unexpected result.")

    try:
        success = execute_schedule(schedule)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Could not deliver the report. Check the destination and try again.",
        ) from e

    error_reason = None
    if not success:
        try:
            error_reason = failure_reason(schedule)
        except Exception:
            error_reason = "unknown error"

    try:
        ScheduleStore.mark_run(
            schedule_id,
            schedule.get("frequency"),
            success=bool(success),
            error=error_reason,
        )
    except Exception:
        pass

    if not success:
        raise HTTPException(status_code=500, detail="Could not deliver the report. Check the destination and try again.")

    return {"message": "Report sent."}

# ---------- Demo Dataset ----------

SAMPLE_DATASET_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_dataset.csv")


@router.post("/demo/load")
def load_demo_dataset(current_user: str = Depends(require_auth), _rl=Depends(rate_limit(upload_limiter))):
    """
    Loads a pre-built sample dataset (sales data) into the logged-in user's
    account, so new users can explore every feature immediately without
    needing to find or prepare their own file first.
    """
    if not os.path.exists(SAMPLE_DATASET_PATH):
        raise HTTPException(status_code=500, detail="Sample dataset is not available.")

    try:
        df = pd.read_csv(SAMPLE_DATASET_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Sample dataset could not be read.") from e

    if not isinstance(df, pd.DataFrame):
        raise HTTPException(status_code=500, detail="Sample dataset could not be read.")

    try:
        dataset_id = DatasetStore.create(df, "sample_sales_data.csv", current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Sample dataset could not be saved.") from e

    if not dataset_id:
        raise HTTPException(status_code=500, detail="Sample dataset could not be saved.")

    try:
        profile = DataProfiler.profile(df)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Sample dataset profile could not be generated.") from e

    if not isinstance(profile, dict):
        raise HTTPException(status_code=500, detail="Sample dataset profile returned an unexpected result.")

    try:
        preview = to_json_safe_records(df, 10)
    except Exception:
        preview = []

    if not isinstance(preview, list):
        preview = []

    return {
        "dataset_id": dataset_id,
        "filename": "sample_sales_data.csv",
        "profile": profile,
        "preview": preview,
    }

def _count_issue_value(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return _safe_int(value.get("count"), 0)
    if isinstance(value, int):
        return value
    return 0


def _quality_report_for_df(df: pd.DataFrame, dataset_id: str) -> Dict[str, Any]:
    row_count = _safe_int(len(df), 0)
    col_count = _safe_int(len(df.columns), 0)
    total_cells = row_count * col_count

    try:
        missing_cells = int(df.isna().sum().sum())
    except Exception:
        missing_cells = 0

    completeness_percent = (
        100.0
        if total_cells <= 0
        else round(((total_cells - missing_cells) / total_cells) * 100, 2)
    )

    try:
        duplicate_rows = int(df.duplicated().sum())
    except Exception:
        duplicate_rows = 0

    duplicate_row_percent = (
        round((duplicate_rows / row_count) * 100, 2)
        if row_count > 0
        else 0.0
    )

    try:
        issues = DataCleaner.detect_issues(df)
    except Exception:
        issues = {}

    if not isinstance(issues, dict):
        issues = {}

    issue_keys = (
        "duplicate_rows",
        "key_duplicates",
        "missing_values",
        "outliers",
        "negative_values",
        "inconsistent_values",
        "fuzzy_category_issues",
        "date_format_issues",
        "numeric_format_issues",
        "email_format_issues",
    )

    issue_counts = {
        key: _count_issue_value(issues.get(key))
        for key in issue_keys
    }

    total_issue_count = sum(issue_counts.values())

    columns_report = []
    unique_ratios = []
    primary_key_candidates = []

    for idx, col in enumerate(df.columns):
        col_name = str(col)
        series = df[col]

        try:
            non_null = int(series.notna().sum())
        except Exception:
            non_null = 0

        try:
            unique = int(series.nunique(dropna=True))
        except Exception:
            unique = 0

        try:
            missing = int(series.isna().sum())
        except Exception:
            missing = max(0, row_count - non_null)

        unique_ratio = round(unique / non_null, 4) if non_null > 0 else 0.0
        unique_ratios.append(unique_ratio)

        completeness_pct = (
            round((non_null / row_count) * 100, 2)
            if row_count > 0
            else 0.0
        )

        if pd.api.types.is_numeric_dtype(series):
            kind = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            kind = "datetime"
        else:
            kind = "text"

        flags = []

        if missing > 0:
            flags.append("missing_values")

        if kind == "numeric":
            try:
                numeric_series = pd.to_numeric(series, errors="coerce").dropna()
                if not numeric_series.empty and bool((numeric_series < 0).any()):
                    flags.append("negative_values")
            except Exception:
                pass

        if issue_counts.get("email_format_issues", 0) > 0 and "email" in col_name.lower():
            flags.append("email_format_issues")

        if issue_counts.get("date_format_issues", 0) > 0 and kind == "text":
            flags.append("possible_date_format_issue")

        if row_count > 0 and non_null == row_count and unique == row_count:
            primary_key_candidates.append(col_name)

        columns_report.append(
            {
                "name": col_name,
                "kind": kind,
                "missing_values": missing,
                "missing_percent": round(
                    (missing / row_count) * 100, 2
                ) if row_count > 0 else 0.0,
                "non_null_values": non_null,
                "unique_values": unique,
                "unique_ratio": unique_ratio,
                "completeness_percent": completeness_pct,
                "flags": flags,
            }
        )

    avg_unique_ratio = (
        round(sum(unique_ratios) / len(unique_ratios), 4)
        if unique_ratios
        else 0.0
    )

    issue_penalty = min(
        100.0,
        round((total_issue_count / max(row_count, 1)) * 100, 2),
    )

    health_score = max(
        0.0,
        min(
            100.0,
            round(
                completeness_percent * 0.45
                + (100.0 - duplicate_row_percent) * 0.20
                + avg_unique_ratio * 100.0 * 0.15
                + (100.0 - issue_penalty) * 0.20,
                2,
            ),
        ),
    )

    freshness = None
    profile_health_score = None
    profile_date_columns = []

    try:
        profile = DataProfiler.profile(df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    profile_health_score = _safe_finite_number(profile.get("health_score"))

    raw_date_columns = profile.get("date_columns") or []
    if isinstance(raw_date_columns, list):
        profile_date_columns = [str(c) for c in raw_date_columns[:20] if c is not None]

    date_columns = profile_date_columns
    latest = None

    for col in date_columns[:5]:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
        except Exception:
            continue

        if parsed.empty:
            continue

        try:
            max_date = parsed.max()
        except Exception:
            continue

        if max_date is None or pd.isna(max_date):
            continue

        try:
            if getattr(max_date, "tz", None) is not None:
                max_date_naive = max_date.tz_localize(None)
            else:
                max_date_naive = max_date
        except Exception:
            max_date_naive = max_date

        if latest is None or max_date_naive > latest["max_date"]:
            latest = {
                "column": str(col),
                "max_date": max_date_naive,
            }

    if latest:
        try:
            days_since_latest = max(
                0,
                int((pd.Timestamp.now() - pd.Timestamp(latest["max_date"])).days),
            )
        except Exception:
            days_since_latest = None

        freshness = {
            "latest_date_column": latest["column"],
            "latest_date": latest["max_date"].isoformat(),
            "days_since_latest": days_since_latest,
        }

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "row_count": row_count,
            "column_count": col_count,
            "total_cells": total_cells,
            "missing_cells": missing_cells,
            "completeness_percent": completeness_percent,
            "duplicate_rows": duplicate_rows,
            "duplicate_row_percent": duplicate_row_percent,
            "primary_key_candidates": primary_key_candidates[:20],
            "issue_counts": issue_counts,
            "total_issue_count": total_issue_count,
            "average_unique_ratio": avg_unique_ratio,
            "health_score": health_score,
            "profile_health_score": profile_health_score,
            "date_columns": profile_date_columns,
            "freshness": freshness,
            "columns": columns_report[:200],
            "columns_truncated": len(columns_report) > 200,
            "generated_by": "deterministic-quality-engine",
            "ai_generated": False,
        }
    )


def _metric_catalog_for_df(df: pd.DataFrame, dataset_id: str) -> Dict[str, Any]:
    try:
        profile = DataProfiler.profile(df)
    except Exception:
        profile = {}

    if not isinstance(profile, dict):
        profile = {}

    numeric_columns = profile.get("numeric_columns") or []
    categorical_columns = profile.get("categorical_columns") or []
    date_columns = profile.get("date_columns") or []
    profile_columns = profile.get("columns") or []

    measures = []
    for col in numeric_columns:
        col_name = str(col)
        try:
            if ChartEngine.is_identifier_name(col_name):
                continue
        except Exception:
            pass

        measures.append(
            {
                "name": col_name,
                "role": "measure",
                "recommended_aggregations": [
                    "sum",
                    "mean",
                    "median",
                    "min",
                    "max",
                    "count",
                ],
                "default_aggregation": "sum",
            }
        )

    dimensions = []

    for col in categorical_columns:
        dimensions.append(
            {
                "name": str(col),
                "role": "categorical",
                "is_time_based": False,
            }
        )

    for col in date_columns:
        dimensions.append(
            {
                "name": str(col),
                "role": "time",
                "is_time_based": True,
            }
        )

    time_columns = [
        {
            "name": str(col),
            "supported_grains": [
                "year",
                "quarter",
                "month",
                "week",
                "day",
                "hour",
            ],
        }
        for col in date_columns
    ]

    candidate_keys = []
    num_rows = _safe_int(profile.get("num_rows"), len(df))

    if isinstance(profile_columns, list):
        for col in profile_columns:
            if not isinstance(col, dict):
                continue

            name = str(col.get("name") or "")
            missing = _safe_int(col.get("missing_values"), 0)
            unique = _safe_int(col.get("unique_values"), 0)

            if name and num_rows > 0 and missing == 0 and unique == num_rows:
                candidate_keys.append(name)

    column_count = _safe_int(profile.get("num_columns"), len(df.columns))

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "row_count": num_rows,
            "column_count": column_count,
            "measures": measures[:100],
            "dimensions": dimensions[:100],
            "time_columns": time_columns[:50],
            "candidate_keys": candidate_keys[:20],
            "generated_by": "deterministic-metric-catalog",
            "ai_generated": False,
        }
    )


def _narrative_summary_for_df(df: pd.DataFrame, dataset_id: str) -> Dict[str, Any]:
    quality = _quality_report_for_df(df, dataset_id)
    catalog = _metric_catalog_for_df(df, dataset_id)

    bullets = []

    bullets.append(
        "Dataset has {rows} rows and {cols} columns. Data health score is {score}/100.".format(
            rows=quality.get("row_count", 0),
            cols=quality.get("column_count", 0),
            score=quality.get("health_score", 0),
        )
    )

    if quality.get("missing_cells", 0) > 0:
        top_missing = sorted(
            quality.get("columns", []) or [],
            key=lambda c: _safe_int(c.get("missing_values"), 0),
            reverse=True,
        )[:3]

        names = ", ".join(
            str(c.get("name"))
            for c in top_missing
            if isinstance(c, dict) and c.get("name")
        )

        if names:
            bullets.append(f"Largest gaps are missing values in: {names}.")

    if quality.get("duplicate_rows", 0) > 0:
        bullets.append(
            "{dup} duplicate row(s) detected ({percent}%).".format(
                dup=quality.get("duplicate_rows", 0),
                percent=quality.get("duplicate_row_percent", 0),
            )
        )

    if quality.get("primary_key_candidates"):
        bullets.append(
            "Possible unique key columns: "
            + ", ".join(str(x) for x in quality.get("primary_key_candidates", [])[:3])
            + "."
        )

    measures = catalog.get("measures", []) or []
    if measures:
        bullets.append(
            "Candidate business measures include: "
            + ", ".join(str(m.get("name")) for m in measures[:5] if isinstance(m, dict))
            + "."
        )

    dimensions = catalog.get("dimensions", []) or []
    if dimensions:
        bullets.append(
            "Useful slicing dimensions include: "
            + ", ".join(str(d.get("name")) for d in dimensions[:5] if isinstance(d, dict))
            + "."
        )

    freshness = quality.get("freshness")
    if isinstance(freshness, dict) and freshness.get("latest_date"):
        bullets.append(
            "Latest observed date is {date} in column '{col}'.".format(
                date=freshness.get("latest_date"),
                col=freshness.get("latest_date_column"),
            )
        )

        days = freshness.get("days_since_latest")
        if isinstance(days, int):
            bullets.append(f"That is {days} day(s) old relative to server time.")

    issue_counts = quality.get("issue_counts", {}) or {}
    active_issues = [
        str(key)
        for key, value in issue_counts.items()
        if _safe_int(value, 0) > 0
    ]

    if active_issues:
        bullets.append(
            "Detected quality issue types: "
            + ", ".join(active_issues[:6])
            + "."
        )
    else:
        bullets.append(
            "No major structural quality issues were detected by the deterministic checker."
        )

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "summary": "\n".join(bullets),
            "bullets": bullets,
            "quality": quality,
            "metric_catalog": catalog,
            "generated_by": "deterministic-narrative-engine",
            "ai_generated": False,
            "disclaimer": "This summary is generated by deterministic rules and does not use AI quota.",
        }
    )


@router.get("/dataset/{dataset_id}/quality-report")
def get_quality_report(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(export_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        report = _quality_report_for_df(df, dataset_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Quality report could not be generated.",
        ) from e

    return report


@router.get("/dataset/{dataset_id}/metric-catalog")
def get_metric_catalog(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(sql_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        catalog = _metric_catalog_for_df(df, dataset_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Metric catalog could not be generated.",
        ) from e

    return catalog


@router.get("/dataset/{dataset_id}/narrative-summary")
def get_narrative_summary(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(export_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        narrative = _narrative_summary_for_df(df, dataset_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Narrative summary could not be generated.",
        ) from e

    return narrative


@router.get("/dataset/{dataset_id}/intelligence")
def get_dataset_intelligence(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(export_limiter)),
):
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        quality = _quality_report_for_df(df, dataset_id)
    except Exception:
        quality = {
            "dataset_id": str(dataset_id),
            "error": "Quality report could not be generated.",
            "ai_generated": False,
        }

    try:
        catalog = _metric_catalog_for_df(df, dataset_id)
    except Exception:
        catalog = {
            "dataset_id": str(dataset_id),
            "error": "Metric catalog could not be generated.",
            "ai_generated": False,
        }

    try:
        narrative = _narrative_summary_for_df(df, dataset_id)
    except Exception:
        narrative = {
            "dataset_id": str(dataset_id),
            "error": "Narrative summary could not be generated.",
            "ai_generated": False,
        }

    try:
        cleaning_plan = _cleaning_plan_for_df(df, dataset_id)
    except Exception:
        cleaning_plan = {
            "dataset_id": str(dataset_id),
            "error": "Cleaning plan could not be generated.",
            "ai_generated": False,
        }

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "data_version": get_data_version(df),
            "quality": quality,
            "catalog": catalog,
            "narrative": narrative,
            "cleaning_plan": cleaning_plan,
            "generated_by": "deterministic-intelligence-combined",
            "ai_generated": False,
        }
    )


@router.get("/dataset/{dataset_id}/quality-summary")
def get_quality_summary(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(export_limiter)),
):
    """
    Compact deterministic quality summary for dashboards/cleaning panels.
    Uses no AI quota.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        quality = _quality_report_for_df(df, dataset_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Quality summary could not be generated.",
        ) from e

    if not isinstance(quality, dict):
        quality = {}

    raw_columns = quality.get("columns")
    if not isinstance(raw_columns, list):
        raw_columns = []

    safe_columns = [c for c in raw_columns if isinstance(c, dict)]

    worst_missing = sorted(
        safe_columns,
        key=lambda c: _safe_int(c.get("missing_values"), 0),
        reverse=True,
    )[:10]

    issue_counts = quality.get("issue_counts")
    if not isinstance(issue_counts, dict):
        issue_counts = {}

    active_issues = {
        str(key): _safe_int(value, 0)
        for key, value in issue_counts.items()
        if _safe_int(value, 0) > 0
    }

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "data_version": get_data_version(df),
            "row_count": quality.get("row_count", 0),
            "column_count": quality.get("column_count", 0),
            "health_score": quality.get("health_score", 0),
            "profile_health_score": quality.get("profile_health_score"),
            "completeness_percent": quality.get("completeness_percent", 0),
            "missing_cells": quality.get("missing_cells", 0),
            "duplicate_rows": quality.get("duplicate_rows", 0),
            "duplicate_row_percent": quality.get("duplicate_row_percent", 0),
            "total_issue_count": quality.get("total_issue_count", 0),
            "primary_key_candidates": quality.get("primary_key_candidates", [])[:10],
            "date_columns": quality.get("date_columns", [])[:10],
            "freshness": quality.get("freshness"),
            "active_issue_counts": active_issues,
            "worst_missing_columns": [
                {
                    "name": c.get("name"),
                    "missing_values": c.get("missing_values", 0),
                    "missing_percent": c.get("missing_percent", 0),
                    "unique_values": c.get("unique_values", 0),
                    "kind": c.get("kind"),
                }
                for c in worst_missing
            ],
            "generated_by": "deterministic-quality-summary",
            "ai_generated": False,
        }
    )


def _first_string_from_mapping(mapping: Any, keys: tuple) -> Optional[str]:
    if not isinstance(mapping, dict):
        return None

    for key in keys:
        value = mapping.get(key)
        text = _safe_text(value, 200)
        if text:
            return text

    return None


def _issue_column_name(entry: Any) -> Optional[str]:
    if isinstance(entry, dict):
        return _first_string_from_mapping(
            entry,
            ("column", "name", "field", "column_name", "col"),
        )

    if isinstance(entry, str):
        name = entry.strip()
        return name or None

    return None


def _issue_entries(issues: Any, key: str) -> list:
    if not isinstance(issues, dict):
        return []

    value = issues.get(key)

    if isinstance(value, list):
        return value

    if isinstance(value, dict):
        return [value]

    if value is None:
        return []

    return [value]


def _entry_number(entry: Any, keys: tuple, default: int = 0) -> int:
    if isinstance(entry, dict):
        for key in keys:
            if key in entry:
                return _safe_int(entry.get(key), default)

    return default


def _cleaning_plan_for_df(df: pd.DataFrame, dataset_id: str) -> Dict[str, Any]:
    try:
        issues = DataCleaner.detect_issues(df)
    except Exception:
        issues = {}

    if not isinstance(issues, dict):
        issues = {}

    plan: List[Dict[str, Any]] = []

    def _preview_request_for_action(action: str, column: Optional[str]) -> Dict[str, Any]:
        request: Dict[str, Any] = {"action": action}

        if column:
            request["column"] = column

        if action == "fill_missing":
            request["strategy"] = "median"
        elif action == "sort_dataset":
            request["operator"] = "asc"
        elif action == "filter_rows":
            request["operator"] = "="
            request["filter_value"] = ""
        elif action == "add_calculated_column":
            request["operator"] = "+"

        return request

    def add_action(action: str, column: Optional[str], reason: str, risk: str = "review") -> None:
        if action not in CLEAN_ACTIONS:
            return

        if action in ACTIONS_REQUIRING_COLUMN and not column:
            return

        for item in plan:
            if item.get("action") == action and item.get("column") == column:
                return

        plan.append(
            {
                "action": action,
                "column": column,
                "reason": _safe_text(reason, 500) or "Recommended by deterministic checker.",
                "risk": risk,
                "preview_supported": True,
                "applies_automatically": False,
                "preview_request": _preview_request_for_action(action, column),
            }
        )

    duplicate_rows = issues.get("duplicate_rows")
    duplicate_count = 0

    if isinstance(duplicate_rows, dict):
        duplicate_count = _safe_int(duplicate_rows.get("count"), 0)
    elif isinstance(duplicate_rows, int):
        duplicate_count = duplicate_rows

    if duplicate_count > 0:
        add_action(
            "remove_duplicates",
            None,
            f"{duplicate_count} duplicate row(s) detected.",
            "safe",
        )

    for entry in _issue_entries(issues, "key_duplicates"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "duplicate_count", "duplicates"), 0)

        reason = (
            f"Key duplicates detected on '{column}'."
            if column
            else "Key duplicates detected."
        )

        if count > 0:
            reason = f"{count} key duplicate(s). {reason}"

        add_action("resolve_key_duplicates", column, reason, "review")

    for entry in _issue_entries(issues, "missing_values"):
        column = _issue_column_name(entry)
        missing = _entry_number(entry, ("missing_values", "missing", "count"), 0)

        if not column:
            continue

        reason = f"Missing values detected in '{column}'."

        if missing > 0:
            reason = f"{missing} missing value(s). {reason}"

        add_action(
            "fill_missing",
            column,
            reason + " Median fill is usually safer for numeric columns.",
            "review",
        )

        add_action(
            "drop_missing",
            column,
            reason + " Drop rows only if missingness is negligible for your analysis.",
            "review",
        )

    for entry in _issue_entries(issues, "outliers"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "outlier_count", "outliers"), 0)

        reason = (
            f"Outliers detected in '{column}'."
            if column
            else "Outliers detected."
        )

        if count > 0:
            reason = f"{count} outlier(s). {reason}"

        add_action("clip_outliers", column, reason, "review")

    for entry in _issue_entries(issues, "negative_values"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "negative_count", "negatives"), 0)

        reason = (
            f"Invalid negative values detected in '{column}'."
            if column
            else "Invalid negative values detected."
        )

        if count > 0:
            reason = f"{count} negative value(s). {reason}"

        add_action("mark_negative_as_missing", column, reason, "review")

    for entry in _issue_entries(issues, "inconsistent_values"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "inconsistent_count"), 0)

        reason = (
            f"Inconsistent text/category values detected in '{column}'."
            if column
            else "Inconsistent text/category values detected."
        )

        if count > 0:
            reason = f"{count} inconsistent value group(s). {reason}"

        add_action("normalize_text", column, reason, "safe")

    for entry in _issue_entries(issues, "fuzzy_category_issues"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "fuzzy_count"), 0)

        reason = (
            f"Fuzzy duplicate categories detected in '{column}'."
            if column
            else "Fuzzy duplicate categories detected."
        )

        if count > 0:
            reason = f"{count} fuzzy category group(s). {reason}"

        add_action("normalize_text_aggressive", column, reason, "review")

    for entry in _issue_entries(issues, "date_format_issues"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "date_count"), 0)

        reason = (
            f"Inconsistent date formats detected in '{column}'."
            if column
            else "Inconsistent date formats detected."
        )

        if count > 0:
            reason = f"{count} date format issue group(s). {reason}"

        add_action("normalize_date_format", column, reason, "safe")

    for entry in _issue_entries(issues, "numeric_format_issues"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "numeric_count"), 0)

        reason = (
            f"Numeric formatting issues detected in '{column}'."
            if column
            else "Numeric formatting issues detected."
        )

        if count > 0:
            reason = f"{count} numeric format issue group(s). {reason}"

        add_action("clean_numeric_format", column, reason, "safe")

    for entry in _issue_entries(issues, "email_format_issues"):
        column = _issue_column_name(entry)
        count = _entry_number(entry, ("count", "email_count"), 0)

        reason = (
            f"Malformed email values detected in '{column}'."
            if column
            else "Malformed email values detected."
        )

        if count > 0:
            reason = f"{count} email format issue group(s). {reason}"

        add_action("flag_invalid_email_as_missing", column, reason, "safe")

    try:
        quality = _quality_report_for_df(df, dataset_id)
    except Exception:
        quality = {}

    if not isinstance(quality, dict):
        quality = {}

    issue_counts = quality.get("issue_counts")
    if not isinstance(issue_counts, dict):
        issue_counts = {}

    active_issue_count = sum(
        _safe_int(value, 0)
        for value in issue_counts.values()
    )

    safe_actions = [item for item in plan if item.get("risk") == "safe"]
    review_actions = [item for item in plan if item.get("risk") != "safe"]

    capped_plan = plan[:50]

    return _make_json_safe(
        {
            "dataset_id": str(dataset_id),
            "data_version": get_data_version(df),
            "row_count": quality.get("row_count", _safe_int(len(df), 0)),
            "column_count": quality.get("column_count", _safe_int(len(df.columns), 0)),
            "health_score": quality.get("health_score", 0),
            "total_issue_count": active_issue_count,
            "safe_action_count": len(safe_actions),
            "review_action_count": len(review_actions),
            "plan": capped_plan,
            "plan_truncated": len(plan) > len(capped_plan),
            "generated_by": "deterministic-cleaning-plan",
            "ai_generated": False,
            "disclaimer": "This plan is rule-based. Review preview before applying destructive actions.",
        }
    )


@router.get("/dataset/{dataset_id}/cleaning-plan")
def get_cleaning_plan(
    dataset_id: str,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(export_limiter)),
):
    """
    Deterministic cleaning plan based on detected data quality issues.
    Uses no AI quota and does not modify the dataset.
    """
    df = get_dataset_or_404(dataset_id, current_user)

    try:
        plan = _cleaning_plan_for_df(df, dataset_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Cleaning plan could not be generated.",
        ) from e

    return plan


@router.get("/health")
def health_check():
    """
    Lightweight production health endpoint.
    Does not require auth and does not touch user data.
    """
    return {
        "status": "ok",
        "service": "data-analytics-api",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ai_generated": False,
    }


@router.get("/usage")
def get_ai_usage(current_user: str = Depends(require_auth)):
    """Today's AI request count and the user's daily limit, for the usage badge in the header."""
    try:
        usage = get_usage_info(current_user)
    except Exception:
        usage = {}

    if not isinstance(usage, dict):
        usage = {}

    usage.setdefault("used", 0)
    usage.setdefault("limit", 0)

    for key in ("used", "limit"):
        try:
            usage[key] = int(usage[key])
        except (TypeError, ValueError, OverflowError):
            usage[key] = 0

    return usage

# ---------- Account deletion (email confirmation + password) ----------

@router.post("/account/delete/request")
def request_account_deletion(
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(login_limiter)),
):
    """
    Step 1 of deleting an account: emails a confirmation link to the
    account's own email address. Nothing is deleted yet.
    """
    try:
        user = UserStore.get_user(current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Account deletion request failed. Please try again.") from e

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not isinstance(user, dict):
        raise HTTPException(status_code=500, detail="Account deletion request returned an unexpected result.")

    email = str(user.get("email") or "").strip()
    email_verified = bool(user.get("email_verified"))

    if not email_verified:
        raise HTTPException(
            status_code=400,
            detail="Please verify your email address first, so the confirmation link goes to an inbox you control. "
                   "Use 'Resend email' next to your email address, or correct the address if it has a typo.",
        )

    if not email:
        raise HTTPException(status_code=400, detail="Account email is missing. Please contact support.")

    try:
        sent = bool(send_deletion_email(current_user, email))
    except Exception:
        sent = False

    if not sent:
        try:
            failure_detail = email_failure_message()
        except Exception:
            failure_detail = "Email service is unavailable. Please try again later."
        raise HTTPException(status_code=503, detail=failure_detail)

    return {"message": f"We sent a confirmation link to {email}. It expires in 30 minutes. Your account stays active until you confirm."}


class ConfirmDeletionRequest(BaseModel):
    token: str
    password: str


@router.post("/account/delete/confirm")
def confirm_account_deletion(request: ConfirmDeletionRequest, _rl=Depends(rate_limit(login_limiter))):
    """
    Step 2 (public, opened from the emailed link): the link proves access
    to the account's inbox and the password proves it's the owner. Only
    when both are right is the account permanently deleted.
    A wrong password returns 403 (never 401, which would log the user out).
    """
    token = str(request.token or "")
    password = str(request.password or "")

    try:
        result = confirm_deletion(token, password)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Account deletion confirmation failed. Please request a new link.",
        ) from e

    if not isinstance(result, (tuple, list)) or len(result) < 2:
        raise HTTPException(
            status_code=500,
            detail="Account deletion confirmation returned an unexpected result.",
        )

    status = result[0]
    attempts_left = result[1]

    if status == "deleted":
        return {"message": "Your account and all its data have been permanently deleted."}
    if status == "wrong_password":
        try:
            attempts = int(attempts_left)
        except (TypeError, ValueError, OverflowError):
            attempts = 0
        if attempts < 0:
            attempts = 0
        raise HTTPException(status_code=403, detail=f"Invalid password. {attempts} attempt(s) left.")
    if status == "too_many_attempts":
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts. For your security, this link no longer works. Please request a new one from your Account page.",
        )
    raise HTTPException(
        status_code=400,
        detail="This confirmation link is invalid or has expired. Please request a new one from your Account page.",
    )

# ---------- Account page ----------

class ProfileUpdateRequest(BaseModel):
    full_name: str = ""
    organization: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeEmailRequest(BaseModel):
    new_email: str
    password: str


@router.get("/account")
def get_account(current_user: str = Depends(require_auth)):
    """Everything the Account page shows: profile, plan, verification status, and usage."""
    try:
        user = UserStore.get_user(current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Account could not be loaded.") from e

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not isinstance(user, dict):
        raise HTTPException(status_code=500, detail="Account returned an unexpected result.")

    try:
        datasets = DatasetStore.list_all(current_user)
        datasets_count = len(datasets) if isinstance(datasets, list) else 0
    except Exception:
        datasets_count = 0

    try:
        ai_usage = get_usage_info(current_user)
    except Exception:
        ai_usage = {}

    if not isinstance(ai_usage, dict):
        ai_usage = {}

    ai_usage.setdefault("used", 0)
    ai_usage.setdefault("limit", 0)

    for key in ("used", "limit"):
        try:
            ai_usage[key] = int(ai_usage[key])
        except (TypeError, ValueError, OverflowError):
            ai_usage[key] = 0

    return {
        **user,
        "datasets_count": int(datasets_count),
        "ai_usage": ai_usage,
    }


@router.put("/account/profile")
def update_profile(request: ProfileUpdateRequest, current_user: str = Depends(require_auth)):
    full_name = str(request.full_name or "").strip()[:100]
    organization = str(request.organization or "").strip()[:100]
    try:
        UserStore.update_profile(current_user, full_name, organization)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Profile could not be saved.") from e

    return {"message": "Profile saved.", "full_name": full_name, "organization": organization}


# Wrong-password errors below use 403, not 401: the frontend logs users out on
# any 401, and a mistyped password must not do that.

@router.post("/account/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(login_limiter)),
):
    current_password = str(request.current_password or "")
    new_password = str(request.new_password or "")

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    try:
        changed = UserStore.change_password(current_user, current_password, new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Password change failed. Please try again.") from e

    if not changed:
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    return {"message": "Password changed."}


@router.post("/account/change-email")
def change_email(
    request: ChangeEmailRequest,
    current_user: str = Depends(require_auth),
    _rl=Depends(rate_limit(login_limiter)),
):
    new_email = str(request.new_email or "").strip().lower()
    password = str(request.password or "")

    if not new_email or "@" not in new_email or "." not in new_email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    try:
        UserStore.change_email(current_user, new_email, password)
    except ValueError as e:
        message = str(e)
        status = 403 if "password" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Email change failed. Please try again.") from e

    try:
        verification_sent = bool(send_verification_email(current_user, new_email))
    except Exception:
        verification_sent = False

    if verification_sent:
        return {"message": "Email updated. We sent a verification link to your new address."}

    try:
        failure_note = email_failure_message()
    except Exception:
        failure_note = "Email service is unavailable."

    return {"message": f"Email updated, but the verification email could not be sent. Use 'Resend' in the Overview section. {failure_note}"}