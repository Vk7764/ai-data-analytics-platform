# backend/tests/test_runtime_sanity.py
# Runtime sanity check: verifies that critical backend modules and runtime packages import.
# Read-only: no data is modified, no external service or LLM provider is contacted.
# Missing OPTIONAL packages are reported as skips with a clear reason, never as crashes.
import importlib

import pytest

CRITICAL_MODULES = [
    "backend.main",
    "backend.api.routes",
    "backend.database.dataset_store",
    "backend.reports.generator",
    "backend.visualization.chart_image",
    "backend.data.profiler",
    "backend.data.cleaner",
    "backend.analytics.statistics",
]

# Packages the application needs at runtime. A missing one fails the check.
REQUIRED_PACKAGES = [
    "fastapi",
    "uvicorn",
    "pandas",
    "numpy",
    "matplotlib",
    "fpdf",
    "pptx",
    "openpyxl",
    "sqlite3",
    "pydantic",
]

# Packages that may be absent in some deployments. A missing one is reported as a skip.
OPTIONAL_PACKAGES = [
    "httpx",
    "requests",
    "jwt",
    "jose",
    "passlib",
    "bcrypt",
]


@pytest.mark.parametrize("module_name", CRITICAL_MODULES)
def test_critical_backend_module_imports(module_name):
    module = importlib.import_module(module_name)
    assert module is not None


@pytest.mark.parametrize("package_name", REQUIRED_PACKAGES)
def test_required_runtime_package_is_importable(package_name):
    importlib.import_module(package_name)


@pytest.mark.parametrize("package_name", OPTIONAL_PACKAGES)
def test_optional_runtime_package_is_reported(package_name):
    try:
        importlib.import_module(package_name)
    except ImportError as exc:
        pytest.skip(f"Optional package '{package_name}' is not installed: {exc}")