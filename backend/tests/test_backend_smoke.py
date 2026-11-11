# backend/tests/test_backend_smoke.py
# Smoke tests for critical non-AI backend flows. Route functions are called directly with an explicit
# current_user, so no HTTP client dependency (httpx) is required. No LLM provider is contacted.
import asyncio
import io
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from backend.api import routes
from backend.api.routes import (
    CleanRequest,
    SavedAnalysisRequest,
    ShareCreateRequest,
    _execute_safe_select_sql,
    _preview_json_value,
)
from backend.database import dataset_store
from backend.database.dataset_store import DatasetStore
from backend.database.db_connector import validate_select_only
from backend.visualization.charts import ChartEngine


def _upload(user_id: str, csv_text: str, filename: str = "data.csv") -> str:
    upload = UploadFile(file=io.BytesIO(csv_text.encode("utf-8")), filename=filename)
    response = asyncio.run(routes.upload_dataset(file=upload, current_user=user_id, _rl=None))
    return response["dataset_id"]


def _sparse_csv(rows: int = 50) -> str:
    """One filled value followed by blanks: a fill_missing action changes rows - 1 cells."""
    lines = ["id,value", "1,10"]
    lines += [f"{i}," for i in range(2, rows + 1)]
    return "\n".join(lines) + "\n"


def _assert_raises_status(fn, status: int):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status


# ---------- 1. Dataset upload / list / get / delete ownership ----------

def test_dataset_upload_list_get_delete_respects_ownership(make_user):
    owner = make_user("owner")
    other = make_user("other")

    dataset_id = _upload(owner, "id,name\n1,a\n2,b\n")

    listed = routes.list_datasets(search=None, current_user=owner)["datasets"]
    assert any(d["dataset_id"] == dataset_id for d in listed)
    assert not any(d["dataset_id"] == dataset_id for d in routes.list_datasets(None, other)["datasets"])

    profile = routes.get_profile(dataset_id, owner)
    assert profile["profile"]["num_rows"] == 2

    _assert_raises_status(lambda: routes.get_profile(dataset_id, other), 404)
    _assert_raises_status(lambda: routes.delete_dataset(dataset_id, other), 404)

    routes.delete_dataset(dataset_id, owner)
    _assert_raises_status(lambda: routes.get_profile(dataset_id, owner), 404)


# ---------- 2. Clean preview is non-destructive and bounded ----------

def test_clean_preview_is_non_destructive_and_bounded(make_user):
    owner = make_user("owner")
    dataset_id = _upload(owner, _sparse_csv(50))
    before = DatasetStore.get(dataset_id, owner).copy()

    request = CleanRequest(action="fill_missing", column="value", strategy="mean")
    preview = routes.preview_clean_dataset(dataset_id, request, owner)

    assert preview["rows_before"] == 50
    assert preview["rows_after"] == 50
    assert preview["cells_changed"] == 49
    assert "value" in preview["columns_affected"]
    assert len(preview["sample_changes"]) == 20
    assert preview["sample_changes_truncated"] is True

    pd.testing.assert_frame_equal(DatasetStore.get(dataset_id, owner), before)
    assert DatasetStore.get_undo_status(dataset_id) is None


# ---------- 3. Clean-all preview ----------

def test_clean_all_preview_is_non_destructive(make_user):
    owner = make_user("owner")
    dataset_id = _upload(owner, "id,name,value\n1,a,10\n1,a,10\n2,b,\n")
    before = DatasetStore.get(dataset_id, owner).copy()

    preview = routes.preview_clean_all(dataset_id, owner)

    assert preview["rows_before"] == 3
    assert preview["rows_after"] == 2
    assert isinstance(preview["actions_applied"], list)
    assert isinstance(preview["warnings"], list)
    assert len(preview["sample_changes"]) <= 20

    pd.testing.assert_frame_equal(DatasetStore.get(dataset_id, owner), before)
    assert DatasetStore.get_undo_status(dataset_id) is None


def test_clean_all_preview_accepts_bare_dataframe_return(make_user, monkeypatch):
    owner = make_user("owner")
    dataset_id = _upload(owner, "id,name,value\n1,a,10\n2,b,20\n")
    before = DatasetStore.get(dataset_id, owner).copy()

    returned = pd.DataFrame({"id": [1], "name": ["a"], "value": [10.0]})
    monkeypatch.setattr(routes.DataCleaner, "auto_clean_all", lambda df: returned)

    preview = routes.preview_clean_all(dataset_id, owner)

    assert preview["rows_before"] == 2
    assert preview["rows_after"] == 1
    assert preview["actions_applied"] == []

    pd.testing.assert_frame_equal(DatasetStore.get(dataset_id, owner), before)


# ---------- 4. Saved analyses: ownership and stale flag ----------

def test_saved_analysis_create_list_load_and_stale_flag(make_user):
    owner = make_user("owner")
    other = make_user("other")
    dataset_id = _upload(owner, "id,value\n1,10\n2,20\n3,30\n")

    created = routes.create_saved_analysis(
        dataset_id,
        SavedAnalysisRequest(title="My KPIs", analysis_type="kpi", parameters={"x": 1}),
        owner,
    )
    analysis_id = created["analysis_id"]

    listed = routes.list_saved_analyses(dataset_id, owner)["analyses"]
    assert [a["analysis_id"] for a in listed] == [analysis_id]

    loaded = routes.load_saved_analysis(dataset_id, analysis_id, owner)
    assert loaded["analysis"]["parameters"] == {"x": 1}
    assert loaded["is_stale"] is False

    _assert_raises_status(lambda: routes.list_saved_analyses(dataset_id, other), 404)
    _assert_raises_status(lambda: routes.load_saved_analysis(dataset_id, analysis_id, other), 404)

    current = DatasetStore.get(dataset_id, owner)
    changed = current.copy().assign(value=[99, 98, 97])
    DatasetStore.update(dataset_id, owner, changed)

    stale = routes.load_saved_analysis(dataset_id, analysis_id, owner)
    assert stale["is_stale"] is True


# ---------- 5. Share links ----------

def test_share_create_list_revoke_and_public_view(make_user):
    owner = make_user("owner")
    other = make_user("other")
    dataset_id = _upload(owner, _sparse_csv(50))

    created = routes.create_dataset_share(
        dataset_id, ShareCreateRequest(label="Review", expires_in_days=7), owner
    )
    token = created["token"]
    share_id = created["share_id"]

    listed = routes.list_dataset_shares(dataset_id, owner)["shares"]
    assert [s["share_id"] for s in listed] == [share_id]
    assert all("token" not in s for s in listed)

    _assert_raises_status(lambda: routes.list_dataset_shares(dataset_id, other), 404)
    _assert_raises_status(lambda: routes.revoke_dataset_share(dataset_id, share_id, other), 404)

    public = routes.get_shared_dataset(token=token, _rl=None)
    public_json = json.dumps(public, allow_nan=False, default=str)

    assert set(public.keys()) == {"read_only", "filename", "profile", "preview"}
    assert len(public["preview"]) == 10
    assert "email" not in public_json
    assert "plan" not in public

    # Invalid token.
    _assert_raises_status(lambda: routes.get_shared_dataset(token="not-a-real-token", _rl=None), 404)

    # Expired token: the expiry is moved into the past directly in the test database.
    conn = sqlite3.connect(str(dataset_store.DB_PATH))
    conn.execute(
        "UPDATE dataset_shares SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00", share_id),
    )
    conn.commit()
    conn.close()

    _assert_raises_status(lambda: routes.get_shared_dataset(token=token, _rl=None), 404)
    assert routes.list_dataset_shares(dataset_id, owner)["shares"] == []

    # Revoked token: a fresh share is revoked explicitly.
    fresh = routes.create_dataset_share(dataset_id, ShareCreateRequest(label="Second", expires_in_days=7), owner)
    routes.revoke_dataset_share(dataset_id, fresh["share_id"], owner)
    _assert_raises_status(lambda: routes.get_shared_dataset(token=fresh["token"], _rl=None), 404)


# ---------- 6. Read-only SQL validation ----------

@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM data",
        "DROP TABLE data",
        "UPDATE data SET value = 1",
        "SELECT * FROM data; DROP TABLE data",
        "PRAGMA table_info(data)",
        "ATTACH DATABASE 'x.db' AS x",
    ],
)
def test_read_only_sql_rejects_non_select_and_dangerous_keywords(sql):
    df = pd.DataFrame({"name": ["a"], "value": [1]})
    with pytest.raises(ValueError):
        _execute_safe_select_sql(df, sql)
    with pytest.raises(ValueError):
        validate_select_only(sql)


def test_read_only_sql_allows_select_and_function_literals():
    df = pd.DataFrame({"name": ["abc"], "value": [1]})
    result, _ = _execute_safe_select_sql(df, "SELECT REPLACE(name, 'a', 'b') AS r FROM data")
    assert result["r"].iloc[0] == "bbc"

    validate_select_only("SELECT name FROM data")


# ---------- 7. JSON-safe serialization ----------

def test_dataframe_records_serialization_handles_missing_values():
    df = pd.DataFrame({"a": [float("nan"), 1.0]})
    records = routes.to_json_safe_records(df)

    assert records[0]["a"] is None
    assert records[1]["a"] == 1.0

    json.dumps(records, allow_nan=False)


def test_preview_value_serialization_handles_nan_inf_and_timestamps():
    assert _preview_json_value(None) is None
    assert _preview_json_value(float("nan")) is None
    assert _preview_json_value(np.float64("nan")) is None
    assert _preview_json_value(float("inf")) is None
    assert _preview_json_value(np.float64("inf")) is None
    assert _preview_json_value(pd.Timestamp("2024-01-02")) == "2024-01-02T00:00:00"
    assert _preview_json_value(np.int64(7)) == 7


def test_correlation_matrix_is_json_safe_for_constant_columns():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "c": [5.0, 5.0, 5.0, 5.0]})
    result = ChartEngine.correlation_matrix(df)

    json.dumps(result, allow_nan=False)

    columns = result.get("columns") or []
    matrix = result.get("matrix") or []

    if len(columns) >= 2 and matrix:
        flat = [value for row in matrix for value in row]
        assert all(value is None or isinstance(value, (int, float)) for value in flat)
        assert not any(isinstance(value, float) and value != value for value in flat)