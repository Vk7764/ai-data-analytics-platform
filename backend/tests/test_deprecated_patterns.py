# backend/tests/test_deprecated_patterns.py
# Regression guard for deprecated patterns removed during maintenance.
# Reads only local source files. Does not modify files or contact network.
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
MAIN_PY = BACKEND_DIR / "main.py"

FORBIDDEN_PATTERNS = {
    "utcnow()": re.compile(r"\butcnow\(\)"),
    "fpdf ln=True": re.compile(r"\bln=True\b"),
    "FastAPI on_event": re.compile(r"@app\.on_event"),
}


def _production_python_files():
    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.relative_to(BACKEND_DIR).parts:
            continue
        yield path


def test_no_deprecated_patterns_in_backend_production_code():
    offenders = []

    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()

        for label, pattern in FORBIDDEN_PATTERNS.items():
            for match in pattern.finditer(text):
                line_no = text[:match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line_no}: {label}")

    assert not offenders, "Deprecated patterns found:\n" + "\n".join(offenders)


def test_main_uses_lifespan_and_not_on_event():
    text = MAIN_PY.read_text(encoding="utf-8")

    assert "from contextlib import asynccontextmanager" in text, (
        "backend/main.py must import asynccontextmanager"
    )
    assert "async def lifespan(app: FastAPI):" in text, (
        "backend/main.py must define lifespan"
    )
    assert "lifespan=lifespan" in text, (
        "backend/main.py must pass lifespan to FastAPI"
    )
    assert "@app.on_event" not in text, (
        "backend/main.py must not use deprecated @app.on_event"
    )