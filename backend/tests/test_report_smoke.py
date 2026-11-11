# backend/tests/test_report_smoke.py
# Deterministic report smoke tests. No AI provider is contacted: every AI/optional input is None.
# All output goes to a temporary directory via monkeypatched OUTPUT_DIR, so real report output is untouched.
import json
import os
import time

import pandas as pd
import pytest

from backend.api import routes
from backend.database.dataset_store import DatasetStore
from backend.reports import generator
from backend.reports.generator import ReportGenerator, cleanup_old_reports
from backend.visualization.charts import ChartEngine


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """Redirects every generated report file into a temporary directory."""
    out = tmp_path / "reports"
    out.mkdir()
    monkeypatch.setattr(generator, "OUTPUT_DIR", str(out))
    return out


@pytest.fixture
def small_df():
    """A small frame containing missing values in several dtypes."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["alpha", None, "gamma"],
        "value": [1.5, float("nan"), 3.0],
    })


# ---------- 1. PDF ----------

def test_generate_pdf_without_optional_sections(report_dir, small_df):
    path = ReportGenerator.generate_pdf(
        small_df,
        "dataset-pdf-smoke",
        executive_summary=None,
        recommendations=None,
        anomaly_summary=None,
        forecast_summary=None,
        chart_image_bytes=None,
        logo_bytes=None,
        accent_color=None,
    )

    assert os.path.isfile(path)
    assert os.path.dirname(path) == str(report_dir)

    with open(path, "rb") as f:
        assert f.read(5) == b"%PDF-"


# ---------- 2. PPTX ----------

def test_generate_pptx_without_optional_inputs(report_dir, small_df):
    path = ReportGenerator.generate_pptx(
        small_df,
        "dataset-pptx-smoke",
        executive_summary=None,
        recommendations=None,
        anomaly_summary=None,
        forecast_summary=None,
        chart_image_bytes=None,
        logo_bytes=None,
        accent_color=None,
    )

    assert os.path.isfile(path)
    assert path.endswith("_report.pptx")

    with open(path, "rb") as f:
        assert f.read(2) == b"PK"  # PPTX is a ZIP container


# ---------- 3. Excel ----------

def test_generate_excel_creates_xlsx(report_dir, small_df):
    pytest.importorskip(
        "openpyxl",
        reason="Excel generation requires openpyxl; skip this test if it is not installed.",
    )

    path = ReportGenerator.generate_excel(small_df, "dataset-xlsx-smoke")

    assert os.path.isfile(path)
    assert path.endswith("_report.xlsx")

    sheets = pd.read_excel(path, sheet_name=None)
    assert "Cleaned_Data" in sheets
    assert len(sheets["Cleaned_Data"]) == 3


# ---------- 4. CSV / JSON / SQL with NaN values ----------

def test_generate_csv_json_sql_handle_nan_safely(report_dir, small_df):
    csv_path = ReportGenerator.generate_csv(small_df, "dataset-multi-smoke")
    json_path = ReportGenerator.generate_json(small_df, "dataset-multi-smoke")
    sql_path = ReportGenerator.generate_sql_script(small_df, "dataset-multi-smoke")

    for path in (csv_path, json_path, sql_path):
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 0

    assert pd.read_csv(csv_path).shape == (3, 3)

    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    assert len(records) == 3
    assert records[1]["value"] is None

    with open(sql_path, "r", encoding="utf-8") as f:
        script = f.read()

    assert "CREATE TABLE data" in script
    assert "NULL" in script


def test_generate_sql_script_keeps_column_names_unique(report_dir):
    df = pd.DataFrame([[1, 2, 3]], columns=["a-b", "a_b", "a b"])
    path = ReportGenerator.generate_sql_script(df, "dataset-sql-dupes")

    with open(path, "r", encoding="utf-8") as f:
        script = f.read()

    assert '"a_b"' in script
    assert '"a_b_2"' in script
    assert '"a_b_3"' in script


# ---------- 5. Retention cleanup ----------

def _write_file(directory, name: str, age_seconds: int) -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(b"x")

    past = time.time() - age_seconds
    os.utime(path, (past, past))
    return path


def test_cleanup_removes_only_expired_report_files(report_dir):
    old_report = _write_file(report_dir, "old_report.pdf", age_seconds=7200)
    old_csv = _write_file(report_dir, "old_data.csv", age_seconds=7200)
    fresh_report = _write_file(report_dir, "fresh_report.pdf", age_seconds=10)
    old_unrelated = _write_file(report_dir, "notes.txt", age_seconds=7200)

    removed = cleanup_old_reports()

    assert removed == 2
    assert not os.path.exists(old_report)
    assert not os.path.exists(old_csv)
    assert os.path.exists(fresh_report)
    assert os.path.exists(old_unrelated)  # Non-report extensions are never touched.


def test_cleanup_never_raises_for_missing_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "OUTPUT_DIR", str(tmp_path / "does-not-exist"))
    assert cleanup_old_reports() == 0


# ---------- 6. Methodology helper resilience ----------

@pytest.fixture
def dataset_id_for_kpis(make_user):
    owner = make_user("kpi-owner")
    df = pd.DataFrame({"id": [1, 2, 3], "value": [10.0, 20.0, 30.0]})
    dataset_id = DatasetStore.create(df, "kpi.csv", owner)
    return owner, dataset_id


def test_kpis_endpoint_tolerates_partial_methodology(monkeypatch, dataset_id_for_kpis):
    owner, dataset_id = dataset_id_for_kpis
    monkeypatch.setattr(ChartEngine, "kpi_methodology", staticmethod(lambda df: {"scope": "partial"}))

    response = routes.get_kpis(dataset_id, owner)

    assert response["methodology"]["scope"] == "partial"
    assert response["methodology"]["dataset_id"] == dataset_id
    assert "data_version" in response["methodology"]
    assert isinstance(response["kpis"], list)


def test_kpis_endpoint_tolerates_empty_methodology(monkeypatch, dataset_id_for_kpis):
    owner, dataset_id = dataset_id_for_kpis
    monkeypatch.setattr(ChartEngine, "kpi_methodology", staticmethod(lambda df: {}))

    response = routes.get_kpis(dataset_id, owner)

    assert response["methodology"]["dataset_id"] == dataset_id


def test_kpis_endpoint_tolerates_none_methodology(monkeypatch, dataset_id_for_kpis):
    owner, dataset_id = dataset_id_for_kpis
    monkeypatch.setattr(ChartEngine, "kpi_methodology", staticmethod(lambda df: None))

    response = routes.get_kpis(dataset_id, owner)

    assert response["methodology"]["dataset_id"] == dataset_id