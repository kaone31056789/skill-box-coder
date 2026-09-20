"""Subprocess sandbox backend.

Used when Docker is unavailable (local Windows dev, Railway). Isolation is
weaker than the container backend -- see the threat-model note in
``sandbox/bootstrap.py`` -- so this backend is the documented fallback, not
the preferred one. It still enforces: a throwaway working directory, a
scrubbed environment, no network, no process spawning, and a hard timeout
with process-tree kill.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .base import (
    ENV_ALLOWLIST,
    RESULT_FILENAME,
    OutputCallback,
    SandboxBackend,
    SandboxResult,
    extract_error_summary,
    parse_result_payload,
    truncate,
)

logger = logging.getLogger(__name__)


def find_root(marker: str) -> Path:
    """Walk up from this module until `marker` is found.

    Counting parents (`parents[4]`) broke the moment the container flattened
    the layout -- it raised IndexError on first use, i.e. only in production.
    Searching for the marker works under any layout.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / marker).exists():
            return parent
    raise RuntimeError(
        f"could not locate {marker!r} above {here}; the sandbox cannot start"
    )


def _bootstrap_source() -> str:
    """The trusted bootstrap copied into every sandbox working directory."""
    return (find_root("sandbox/bootstrap.py") / "sandbox" / "bootstrap.py").read_text(
        encoding="utf-8"
    )


class SubprocessSandbox(SandboxBackend):
    name = "subprocess"

    def __init__(self, memory_mb: int = 1024, cpus: float = 1.0) -> None:
        self.memory_mb = memory_mb
        # At least one thread; whole cores only, since BLAS pools are integral.
        self.threads = max(1, int(cpus))

    def available(self) -> bool:
        return True  # always available; it is the fallback

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
            return self._run_in(workdir, code, support_files, timeout, started, on_output)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _run_in(
        self,
        workdir: str,
        code: str,
        support_files: dict[str, str],
        timeout: int,
        started: float,
        on_output: OutputCallback | None = None,
    ) -> SandboxResult:
        root = Path(workdir)
        (root / "experiment.py").write_text(code, encoding="utf-8")
        (root / "_bootstrap.py").write_text(_bootstrap_source(), encoding="utf-8")
        for filename, content in support_files.items():
            (root / filename).write_text(content, encoding="utf-8")

        # Scrubbed environment: only the allowlist survives, so the experiment
        # cannot read OPENROUTER_API_KEY, DATABASE_URL, etc.
        env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
        env["GENESIS_MEM_LIMIT_MB"] = str(self.memory_mb)
        env["GENESIS_CPU_LIMIT_S"] = str(timeout)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        env["MPLBACKEND"] = "Agg"
        # Size the BLAS/OpenMP pools to the CPU allocation. Left to themselves
        # numpy and scikit-learn size these from the HOST core count and
        # allocate a workspace per thread, which overran the memory cap in
        # production:
        #   "OpenBLAS error: Memory allocation still failed after 10 retries"
        # Pinning to the allocation keeps that bounded while still letting extra
        # CPUs do work -- pinning to 1 would make SANDBOX_CPUS meaningless.
        for var in (
            "OPENBLAS_NUM_THREADS",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            env[var] = str(self.threads)
        # Keep the experiment off the host's import path beyond stdlib+site.
        env["PYTHONPATH"] = ""

        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            # New process group so the timeout kill reaches the whole tree.
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(
                [sys.executable, "-E", "-s", "_bootstrap.py"],
                cwd=workdir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_kwargs,  # type: ignore[arg-type]
            )
        except OSError as exc:
            return SandboxResult(
                status="error",
                error=f"failed to start sandbox process: {exc}",
                backend=self.name,
                execution_time=time.perf_counter() - started,
            )

        # Drain stdout on a reader thread so lines reach the UI as they are
        # printed. stderr is collected normally -- it only matters on failure.
        stdout_lines: list[str] = []

        def _drain() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_lines.append(line)
                if on_output:
                    text = line.rstrip()
                    if text:
                        try:
                            on_output(text)
                        except Exception:  # never let a UI callback kill a run
                            logger.debug("output callback failed", exc_info=True)

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        timed_out = False
        stderr = ""
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

        reader.join(timeout=10)
        if proc.stderr is not None:
            try:
                stderr = proc.stderr.read() or ""
            except (OSError, ValueError):
                stderr = ""
        stdout = "".join(stdout_lines)

        elapsed = time.perf_counter() - started
        stdout, stderr = truncate(stdout or ""), truncate(stderr or "")

        if timed_out:
            return SandboxResult(
                status="timeout",
                execution_time=elapsed,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                error=f"experiment exceeded the {timeout}s sandbox timeout",
                backend=self.name,
            )

        return _collect(root, proc.returncode, stdout, stderr, elapsed, self.name)


def _collect(
    root: Path,
    exit_code: int,
    stdout: str,
    stderr: str,
    elapsed: float,
    backend: str,
) -> SandboxResult:
    """Shared result collection for both backends."""
    if exit_code != 0:
        return SandboxResult(
            status="failed",
            execution_time=elapsed,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            error=extract_error_summary(stderr),
            backend=backend,
        )

    result_path = root / RESULT_FILENAME
    if not result_path.exists():
        return SandboxResult(
            status="failed",
            execution_time=elapsed,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            error=(
                f"experiment exited cleanly but never wrote {RESULT_FILENAME}; "
                "it must persist its metrics there"
            ),
            backend=backend,
        )

    metrics, artifacts, primary, parse_error = parse_result_payload(
        result_path.read_text(encoding="utf-8", errors="replace")
    )
    if parse_error:
        return SandboxResult(
            status="failed",
            execution_time=elapsed,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            error=parse_error,
            backend=backend,
        )

    return SandboxResult(
        status="success",
        metrics=metrics,
        artifacts=artifacts,
        primary_metric=primary["name"] if primary else None,
        metric_direction=primary["direction"] if primary else "maximize",
        execution_time=elapsed,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        backend=backend,
    )
