"""Docker sandbox backend -- the hard isolation boundary.

Preferred backend wherever a Docker daemon is reachable. Enforces, at the
container level: no network, capped CPU/memory/PIDs, a read-only root
filesystem, all capabilities dropped, no privilege escalation, and a
non-root user. The Docker socket is never exposed to the container.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import OutputCallback, SandboxBackend, SandboxResult, truncate
from .subprocess_runner import _bootstrap_source, _collect

logger = logging.getLogger(__name__)

_DAEMON_CHECK_TIMEOUT = 8


class DockerSandbox(SandboxBackend):
    name = "docker"

    def __init__(
        self,
        image: str = "genesis-sandbox:latest",
        memory_mb: int = 1024,
        cpus: float = 1.0,
    ) -> None:
        self.image = image
        self.memory_mb = memory_mb
        self.cpus = cpus
        self._available: bool | None = None

    def available(self) -> bool:
        """True only if the daemon responds AND the sandbox image exists."""
        if self._available is not None:
            return self._available

        if shutil.which("docker") is None:
            self._available = False
            return False
        try:
            info = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=_DAEMON_CHECK_TIMEOUT,
                text=True,
            )
            if info.returncode != 0:
                logger.info("docker daemon not reachable; falling back")
                self._available = False
                return False

            image_check = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                timeout=_DAEMON_CHECK_TIMEOUT,
                text=True,
            )
            if image_check.returncode != 0:
                logger.info(
                    "sandbox image %s not built; run `docker compose build sandbox`",
                    self.image,
                )
                self._available = False
                return False
        except (OSError, subprocess.TimeoutExpired):
            self._available = False
            return False

        self._available = True
        return True

    def run(
        self,
        code: str,
        support_files: dict[str, str],
        timeout: int,
        on_output: OutputCallback | None = None,
    ) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="genesis_exp_")
        started = time.perf_counter()
        try:
            root = Path(workdir)
            (root / "experiment.py").write_text(code, encoding="utf-8")
            (root / "_bootstrap.py").write_text(_bootstrap_source(), encoding="utf-8")
            for filename, content in support_files.items():
                (root / filename).write_text(content, encoding="utf-8")

            threads = max(1, int(self.cpus))
            args = [
                "docker", "run", "--rm",
                # Hard isolation
                "--network", "none",
                "--memory", f"{self.memory_mb}m",
                "--memory-swap", f"{self.memory_mb}m",
                "--cpus", str(self.cpus),
                "--pids-limit", "96",
                "--read-only",
                "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL",
                "--user", "1000:1000",
                # Scratch space; the bind mount below is the only writable path
                # the experiment gets, and it is discarded afterwards.
                "--tmpfs", "/tmp:rw,size=64m",
                "-v", f"{workdir}:/work:rw",
                "-w", "/work",
                "-e", f"GENESIS_MEM_LIMIT_MB={self.memory_mb}",
                "-e", f"GENESIS_CPU_LIMIT_S={timeout}",
                "-e", "PYTHONUNBUFFERED=1",
                "-e", "MPLBACKEND=Agg",
                # See subprocess_runner: unpinned BLAS thread pools exhaust the
                # container memory cap.
                "-e", f"OPENBLAS_NUM_THREADS={threads}",
                "-e", f"OMP_NUM_THREADS={threads}",
                "-e", f"MKL_NUM_THREADS={threads}",
                "-e", f"NUMEXPR_NUM_THREADS={threads}",
                self.image,
                "python", "-E", "-s", "_bootstrap.py",
            ]

            try:
                proc = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    # Give docker a little headroom over the in-container limit.
                    timeout=timeout + 20,
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(
                    status="timeout",
                    execution_time=time.perf_counter() - started,
                    error=f"container exceeded the {timeout}s sandbox timeout",
                    backend=self.name,
                )

            elapsed = time.perf_counter() - started
            return _collect(
                root,
                proc.returncode,
                truncate(proc.stdout or ""),
                truncate(proc.stderr or ""),
                elapsed,
                self.name,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
