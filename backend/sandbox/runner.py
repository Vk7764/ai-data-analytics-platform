# backend/sandbox/runner.py
"""
This script runs INSIDE the Docker sandbox container.
It reads generated pandas code and the dataset, executes the code
in a restricted namespace, and writes the result back as JSON.
"""
import sys
import io
import os
import json
import pandas as pd
import numpy as np

CODE_PATH = "/sandbox/code.py"
DATA_PATH = "/sandbox/data.csv"
RESULT_PATH = "/sandbox/result.json"

SAFE_BUILTINS = {
    "len": len, "sum": sum, "min": min, "max": max, "sorted": sorted,
    "round": round, "abs": abs, "range": range, "list": list,
    "dict": dict, "str": str, "int": int, "float": float, "bool": bool,
    "print": print,
}


def _run(code: str, df: pd.DataFrame):
    safe_globals = {"__builtins__": SAFE_BUILTINS, "pd": pd, "np": np}
    local_vars = {"df": df}

    exec(code, safe_globals, local_vars)

    if "result" not in local_vars:
        raise RuntimeError("Generated code did not set a 'result' variable.")

    result = local_vars["result"]

    if isinstance(result, pd.DataFrame):
        result = result.to_dict(orient="records")
    elif isinstance(result, pd.Series):
        result = result.to_dict()
    elif isinstance(result, (np.integer, np.floating)):
        result = result.item()

    return result


def main():
    if os.path.exists(CODE_PATH):
        # Legacy mode: code and data are mounted as files in /sandbox.
        try:
            with open(CODE_PATH, "r", encoding="utf-8") as f:
                code = f.read()
            df = pd.read_csv(DATA_PATH)
            output = {"success": True, "result": _run(code, df)}
        except Exception as e:
            output = {"success": False, "error": str(e)}

        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, default=str)
        return

    # Stdin mode: payload {"code": ..., "csv": ...} arrives on stdin,
    # so no host volume mount is needed (works under Docker-in-Docker).
    try:
        payload = json.loads(sys.stdin.read())
        df = pd.read_csv(io.StringIO(payload["csv"]))
        output = {"success": True, "result": _run(payload["code"], df)}
    except Exception as e:
        output = {"success": False, "error": str(e)}

    sys.stdout.write(json.dumps(output, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()