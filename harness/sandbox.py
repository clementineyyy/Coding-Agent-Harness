from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

TRUNCATED_MARKER = "[...truncated]"


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool


class Sandbox(ABC):
    network_enabled: bool

    @abstractmethod
    def run(self, command: str, timeout: int) -> SandboxResult:
        """执行命令并返回结果。"""

    @abstractmethod
    def cancel(self, call_id: str) -> None:
        """记录已取消的调用；幂等。"""

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) > self.max_output_bytes:
            return text[: self.max_output_bytes] + TRUNCATED_MARKER, True
        return text, False


class LocalSandbox(Sandbox):
    """宿主直接子进程（非隔离），隔离由护栏承担第一道防线。"""

    def __init__(self, network_enabled: bool = False, max_output_bytes: int = 51200):
        self.network_enabled = network_enabled
        self.max_output_bytes = max_output_bytes
        self.cancelled: set[str] = set()

    def run(self, command: str, timeout: int) -> SandboxResult:
        start = time.monotonic()
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or "", exc.stderr or ""
            stderr = f"{stderr}\ntimeout: command exceeded {timeout}s".strip()
            exit_code = -1
        stdout, stdout_truncated = self._truncate(stdout)
        stderr, stderr_truncated = self._truncate(stderr)
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - start) * 1000),
            truncated=stdout_truncated or stderr_truncated,
        )

    def cancel(self, call_id: str) -> None:
        self.cancelled.add(call_id)


class DockerUnavailableError(RuntimeError):
    """docker CLI 缺失或 daemon 未运行。"""


class DockerSandbox(Sandbox):
    """真实容器沙箱：docker run --rm --network=none -v workspace:/workspace。"""

    def __init__(
        self,
        workspace: Path,
        image: str = "python:3.11-slim",
        network_enabled: bool = False,
        max_output_bytes: int = 51200,
    ):
        self.workspace = Path(workspace)
        self.image = image
        self.network_enabled = network_enabled
        self.max_output_bytes = max_output_bytes
        self.cancelled: set[str] = set()

    def run(self, command: str, timeout: int) -> SandboxResult:
        docker = shutil.which("docker")
        if docker is None:
            raise DockerUnavailableError(
                "docker CLI not found on PATH; install Docker or fall back to LocalSandbox"
            )
        cidfile = tempfile.mkstemp(prefix="harness-cid-", suffix=".txt")[1]
        argv = [docker, "run", "--rm"]
        if not self.network_enabled:
            argv.append("--network=none")
        argv += [
            "-v", f"{self.workspace}:/workspace",
            "--cidfile", cidfile,
            self.image, "sh", "-c", command,
        ]
        start = time.monotonic()
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or "", exc.stderr or ""
            stderr = f"{stderr}\ntimeout: command exceeded {timeout}s".strip()
            exit_code = -1
            self._stop_container(docker, cidfile, timeout)
        finally:
            try:
                os.unlink(cidfile)
            except OSError:
                pass
        stdout, stdout_truncated = self._truncate(stdout)
        stderr, stderr_truncated = self._truncate(stderr)
        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - start) * 1000),
            truncated=stdout_truncated or stderr_truncated,
        )

    def cancel(self, call_id: str) -> None:
        self.cancelled.add(call_id)

    def _stop_container(self, docker: str, cidfile: str, timeout: int) -> None:
        try:
            cid = Path(cidfile).read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not cid:
            return
        try:
            subprocess.run([docker, "stop", cid], capture_output=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            pass
