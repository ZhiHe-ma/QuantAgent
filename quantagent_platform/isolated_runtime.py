from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plugins import PluginError, RunContext


@dataclass(frozen=True)
class WorkerExecution:
    response: Any
    returncode: int
    stdout_sha256: str
    stderr_sha256: str


def read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    if max_bytes < 1:
        raise PluginError(f"{label} max_bytes must be positive")
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise PluginError(f"{label} exceeds {max_bytes} bytes")
        return path.read_bytes()
    except PluginError:
        raise
    except OSError as exc:
        raise PluginError(f"cannot read {label} {path}: {exc}") from exc


def minimal_worker_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return environment


def execute_json_worker(
    context: RunContext,
    *,
    display_name: str,
    file_prefix: str,
    python_executable: Path,
    worker_path: Path,
    request: dict[str, Any],
    timeout_seconds: float,
    max_response_bytes: int = 2 * 1024 * 1024,
    max_log_bytes: int = 64 * 1024,
) -> WorkerExecution:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", file_prefix):
        raise PluginError("worker file_prefix is invalid")
    if not 1 <= timeout_seconds <= 600:
        raise PluginError(f"{display_name} timeout_seconds must be between 1 and 600")
    request_path = Path(context.run_dir) / f"{file_prefix}-request.json"
    response_path = Path(context.run_dir) / f"{file_prefix}-response.json"
    stdout_path = Path(context.run_dir) / f"{file_prefix}.stdout.log"
    stderr_path = Path(context.run_dir) / f"{file_prefix}.stderr.log"
    try:
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
        )
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            completed = subprocess.run(
                [
                    str(python_executable),
                    str(worker_path),
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                cwd=context.run_dir,
                env=minimal_worker_environment(),
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise PluginError(f"{display_name} worker timed out after {timeout_seconds:g} seconds") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise PluginError(f"cannot start {display_name} worker: {exc}") from exc

    stdout = read_bounded(stdout_path, max_log_bytes, f"{display_name} worker stdout")
    stderr = read_bounded(stderr_path, max_log_bytes, f"{display_name} worker stderr")
    if not response_path.is_file():
        detail = stderr.decode("utf-8", errors="replace").strip()[:1000]
        raise PluginError(
            f"{display_name} worker produced no response (exit {completed.returncode}): {detail}"
        )
    raw_response = read_bounded(response_path, max_response_bytes, f"{display_name} worker response")
    try:
        response = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginError(f"cannot parse {display_name} worker response: {exc}") from exc
    return WorkerExecution(
        response=response,
        returncode=completed.returncode,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
    )
