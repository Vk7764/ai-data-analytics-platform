# backend/sandbox/docker_runner.py
import os
import subprocess
import json
import threading
import time
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

_SANDBOX_CACHE_TTL_SECONDS = 60
_SANDBOX_CACHE = {"checked_at": None, "available": False}
_SANDBOX_CACHE_LOCK = threading.Lock()


def is_production() -> bool:
    return (os.environ.get("ENV") or "").strip().lower() == "production"


def unsafe_local_exec_allowed() -> bool:
    """Unsandboxed local execution is a development-only opt-in and is never honored in production."""
    return os.environ.get("ALLOW_UNSAFE_LOCAL_EXEC") == "1" and not is_production()


def is_sandbox_available() -> bool:
    """
    True when generated code can run: either the development-only local fallback is allowed,
    or the Docker daemon answers `docker info` within 3 seconds. The result is cached for 60 seconds.
    """
    if unsafe_local_exec_allowed():
        return True

    now = time.monotonic()
    with _SANDBOX_CACHE_LOCK:
        checked_at = _SANDBOX_CACHE["checked_at"]
        if checked_at is not None and now - checked_at < _SANDBOX_CACHE_TTL_SECONDS:
            return bool(_SANDBOX_CACHE["available"])

    available = False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
        available = result.returncode == 0
    except Exception:
        available = False

    with _SANDBOX_CACHE_LOCK:
        _SANDBOX_CACHE["checked_at"] = time.monotonic()
        _SANDBOX_CACHE["available"] = available
    return available


def _kill_container(name: str) -> None:
    """Stops a timed-out container; killing the docker CLI process alone does not stop the container."""
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
    except Exception:
        pass


class DockerSandboxError(Exception):
    pass


class DockerUnavailableError(DockerSandboxError):
    """Docker itself is missing or unreachable on this host. This is a permanent
    condition for the deployment (e.g. free hosting without docker.sock), unlike
    a busy or timed-out sandbox, which is transient."""
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
            raise DockerUnavailableError(f"Docker is not available on this server: {e}")
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