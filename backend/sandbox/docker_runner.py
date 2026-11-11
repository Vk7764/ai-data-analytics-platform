# backend/sandbox/docker_runner.py
import os
import subprocess
import json
import threading
import uuid
from typing import Any
import pandas as pd

DOCKER_IMAGE = "analytics-sandbox"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# Concurrency cap: at most N sandbox containers run at once; extra requests wait briefly, then fail fast.
_SLOTS = threading.BoundedSemaphore(_int_env("SANDBOX_MAX_CONCURRENT", 4))
_QUEUE_WAIT_SECONDS = _int_env("SANDBOX_QUEUE_WAIT_SECONDS", 15)


def _kill_container(name: str) -> None:
    """Stops a timed-out container; killing the docker CLI process alone does not stop the container."""
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
    except Exception:
        pass


class DockerSandboxError(Exception):
    pass


def run_code_in_sandbox(code: str, df: pd.DataFrame, timeout_seconds: int = 30) -> Any:
    """
    Runs pandas code inside an isolated Docker container.
    The code must set a variable called `result`, which is returned.

    Security measures:
    - No network access inside the container (--network none)
    - Limited memory (--memory) and CPU (--cpus)
    - Runs as a temporary container that is removed after execution (--rm)
    - Dataset and code are piped via stdin/stdout JSON, avoiding host volume mounts.
    """
    payload = json.dumps({"code": code, "csv": df.to_csv(index=False)})

    container_name = f"analytics-sandbox-{uuid.uuid4().hex[:12]}"
    docker_cmd = [
        "docker", "run", "--rm", "-i",
        "--name", container_name,
        "--network", "none",
        "--user", "10001:10001",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--pids-limit", "64",
        "--memory", "256m",
        "--memory-swap", "256m",
        "--cpus", "0.5",
        "--ulimit", "nofile=256:256",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        DOCKER_IMAGE,
    ]

    if not _SLOTS.acquire(timeout=_QUEUE_WAIT_SECONDS):
        raise DockerSandboxError("The analysis sandbox is busy. Please try again in a moment.")
    try:
        try:
            result = subprocess.run(
                docker_cmd,
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            _kill_container(container_name)
            raise DockerSandboxError(f"Code execution timed out after {timeout_seconds} seconds.")
        except (FileNotFoundError, OSError) as e:
            raise DockerSandboxError(f"Docker is not available on this server: {e}")
    finally:
        _SLOTS.release()

    if result.returncode != 0:
        raise DockerSandboxError(f"Sandbox container failed: {result.stderr.strip()}")

    stdout_lines = result.stdout.strip().splitlines()
    if not stdout_lines:
        raise DockerSandboxError("Sandbox did not produce any output.")

    try:
        output = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        raise DockerSandboxError("Sandbox returned an unreadable response.")

    if not output.get("success"):
        raise DockerSandboxError(output.get("error", "Unknown sandbox error"))

    return output["result"]