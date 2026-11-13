# backend/agents/python_agent.py
import logging
import os
import re
import math
import pandas as pd
import numpy as np
from typing import Any, Dict

from backend.agents.sql_agent import SQLAgent, _redact_pii_for_prompt  # reuse the same LLM fallback chain and PII helper
from backend.sandbox.docker_runner import is_sandbox_available, unsafe_local_exec_allowed

logger = logging.getLogger("app")


# Functions/modules the generated code is allowed to use
SAFE_BUILTINS = {
    "len": len,
    "sum": sum,
    "min": min,
    "max": max,
    "sorted": sorted,
    "round": round,
    "abs": abs,
    "range": range,
    "list": list,
    "dict": dict,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "print": print,
}

# Keywords that are never allowed in generated code (basic safety net)
FORBIDDEN_PATTERNS = [
    r"import\s+os", r"import\s+sys", r"import\s+subprocess", r"import\s+shutil",
    r"open\s*\(", r"exec\s*\(", r"eval\s*\(", r"__import__",
    r"\.system\s*\(", r"\.popen\s*\(", r"input\s*\(",
    r"globals\s*\(", r"locals\s*\(", r"__builtins__",
]


def _json_safe(value: Any) -> Any:
    """Recursively converts NaN/Infinity/NaT and numpy scalars into JSON-safe values (None for undefined numbers)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


class SandboxUnavailableError(RuntimeError):
    """Docker (the code sandbox) is not available on this deployment at all,
    e.g. free hosting without Docker. This is not the user's fault and will
    not fix itself on retry."""
    pass


class PythonAgent:
    """
    Converts a natural language analysis question into pandas code,
    then executes it in a restricted environment against the dataset.
    """

    @staticmethod
    def build_prompt(question: str, schema_info: str) -> str:
        # Only the free-text question is redacted; schema_info holds column names and types, which must stay intact.
        question = _redact_pii_for_prompt(question)
        return f"""You are a data analyst. Convert the user's question into Python pandas code.

The dataframe is already loaded in a variable called `df`.
Schema:
{schema_info}

Rules:
- Use ONLY the variable `df` (already loaded), pandas (as pd), and numpy (as np).
- Store your final answer in a variable called `result`. Do NOT use print statements — just assign to `result`.
- `result` should be a simple value, dict, list, or a small DataFrame — never a raw pandas Series unless converted with .to_dict().
- The question may be in Hindi, English, or a mix of both (Hinglish). Interpret words like "har" (meaning "each/every"), "kitna/kitne" (meaning "how many"), "sabse zyada" (meaning "maximum"), "sabse kam" (meaning "minimum") based on their common Hindi meaning, not as literal column values.
- Do NOT read/write files, do NOT import os/sys/subprocess, do NOT use exec/eval.
- Return ONLY the raw Python code. No explanation. No markdown code fences.

Question: {question}

Python code:"""

    @staticmethod
    def _extract_code(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```python\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"```$", "", text.strip())
        return text.strip()

    @staticmethod
    def _validate_code(code: str) -> None:
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, code, flags=re.IGNORECASE):
                raise ValueError(f"Generated code contains a forbidden pattern: '{pattern}'")

    @staticmethod
    def generate_code(question: str, schema_info: str) -> str:
        # Checked BEFORE any LLM call so no AI quota or provider time is spent when code cannot run.
        if not is_sandbox_available():
            raise SandboxUnavailableError(
                "Python code analysis is not available on this deployment because the "
                "secure code sandbox (Docker) is not available here. SQL queries, "
                "insights, cleaning, charts and reports keep working."
            )
        prompt = PythonAgent.build_prompt(question, schema_info)
        # Reuse the same multi-provider fallback chain used by SQLAgent
        providers = SQLAgent.get_provider_chain()
        for provider_fn, name in providers:
            raw_output = provider_fn(prompt)
            if raw_output:
                logger.info(f"[PythonAgent] Code generated using '{name}' provider.")
                return PythonAgent._extract_code(raw_output)

        raise RuntimeError("All LLM providers failed. Check if Ollama is running.")

    @staticmethod
    def execute_code(code: str, df: pd.DataFrame) -> Any:
        """
        Executes the generated code inside an isolated Docker sandbox
        container for security. This is deliberately STRICT: if Docker is
        unavailable, this raises an error instead of silently falling back
        to unsandboxed local execution. On a shared multi-tenant server,
        running untrusted, LLM-generated code outside a sandbox — even
        temporarily — could let one user's session affect another's, so
        "the feature is briefly unavailable" is a much safer failure mode
        than "the feature quietly becomes insecure".
        """
        PythonAgent._validate_code(code)

        # The sandbox is mandatory. Unsandboxed local execution requires an explicit opt-in (development only).
        # ALLOW_UNSAFE_LOCAL_EXEC is ignored when ENV=production.
        strict = not unsafe_local_exec_allowed()

        try:
            from backend.sandbox.docker_runner import (
                run_code_in_sandbox,
                DockerSandboxError,
                DockerUnavailableError,
            )
        except ImportError as e:
            if strict:
                raise SandboxUnavailableError(
                    "Python code analysis is not available on this deployment "
                    "(sandbox not configured). All other features keep working."
                )
            logger.warning(f"[PythonAgent] Docker sandbox unavailable ({e}); falling back to restricted local execution.")
            return PythonAgent._execute_code_local(code, df)

        try:
            return _json_safe(run_code_in_sandbox(code, df))
        except DockerUnavailableError as e:
            if strict:
                logger.warning(f"[PythonAgent] Docker sandbox not available on this host: {e}")
                raise SandboxUnavailableError(
                    "Python code analysis is not available on this deployment because the "
                    "secure code sandbox (Docker) is not available here. SQL queries, "
                    "insights, cleaning, charts and reports keep working."
                )
            logger.warning(f"[PythonAgent] Docker sandbox unavailable ({e}); falling back to restricted local execution.")
            return PythonAgent._execute_code_local(code, df)
        except DockerSandboxError as e:
            if strict:
                logger.warning(f"[PythonAgent] Docker sandbox failed: {e}")
                raise RuntimeError(
                    "The Python Analysis feature is temporarily unavailable "
                    "(sandbox not running). Please try again in a moment, or ask "
                    "your question as a direct data query instead."
                )
            logger.warning(f"[PythonAgent] Docker sandbox unavailable ({e}); falling back to restricted local execution.")
            return PythonAgent._execute_code_local(code, df)
    @staticmethod
    def _execute_code_local(code: str, df: pd.DataFrame) -> Any:
        """
        Fallback: executes code in a restricted local namespace (no Docker isolation).
        """
        safe_globals = {
            "__builtins__": SAFE_BUILTINS,
            "pd": pd,
            "np": np,
        }
        local_vars = {"df": df.copy()}

        try:
            exec(code, safe_globals, local_vars)
        except Exception as e:
            raise RuntimeError(f"Code execution failed: {e}")

        if "result" not in local_vars:
            raise RuntimeError("Generated code did not set a 'result' variable.")

        result = local_vars["result"]

        if isinstance(result, pd.DataFrame):
            result = result.to_dict(orient="records")
        elif isinstance(result, pd.Series):
            result = result.to_dict()
        elif isinstance(result, (np.integer, np.floating)):
            result = result.item()
        return _json_safe(result)