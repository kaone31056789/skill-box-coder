"""Backend selection and the support files shipped into every sandbox."""
from __future__ import annotations

import functools
import logging

from ..config import get_settings
from .base import OutputCallback, SandboxBackend, SandboxResult
from .docker_runner import DockerSandbox
from .subprocess_runner import SubprocessSandbox, find_root

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def dataset_module_source() -> str:
    """The trusted dataset module copied in beside the generated experiment.

    Shipping the data as code is what lets the sandbox run with no network.
    """
    root = find_root("experiments/anomaly_detection/genesis_data.py")
    path = root / "experiments" / "anomaly_detection" / "genesis_data.py"
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def graph_module_source() -> str:
    """The shared pathfinding benchmark, for graph-search experiments."""
    root = find_root("experiments/graph_search/genesis_graph.py")
    return (root / "experiments" / "graph_search" / "genesis_graph.py").read_text(
        encoding="utf-8"
    )


def support_files() -> dict[str, str]:
    """Both benchmarks ship into every sandbox.

    They are small, and shipping both means the runner never has to know which
    domain an experiment belongs to.
    """
    return {
        "genesis_data.py": dataset_module_source(),
        "genesis_graph.py": graph_module_source(),
    }


@functools.lru_cache(maxsize=1)
def get_backend() -> SandboxBackend:
    """Resolve the configured backend, falling back when Docker is absent."""
    settings = get_settings()
    choice = settings.sandbox_backend

    if choice in ("auto", "docker"):
        docker = DockerSandbox(
            image=settings.sandbox_image,
            memory_mb=settings.sandbox_memory_mb,
            cpus=settings.sandbox_cpus,
        )
        if docker.available():
            logger.info("sandbox backend: docker (image=%s)", settings.sandbox_image)
            return docker
        if choice == "docker":
            raise RuntimeError(
                "SANDBOX_BACKEND=docker was requested but the Docker daemon or the "
                f"image {settings.sandbox_image!r} is unavailable. Build it with "
                "`docker compose build sandbox`, or set SANDBOX_BACKEND=subprocess."
            )
        logger.warning(
            "docker unavailable; using the subprocess sandbox "
            "(weaker isolation -- see docs/SECURITY.md)"
        )

    return SubprocessSandbox(
        memory_mb=settings.sandbox_memory_mb, cpus=settings.sandbox_cpus
    )


def execute(
    code: str,
    timeout: int | None = None,
    on_output: OutputCallback | None = None,
) -> SandboxResult:
    """Execute untrusted experiment code and return a structured result.

    ``on_output`` receives each stdout line as it is produced, so the UI can
    show a running experiment live rather than only its final result.
    """
    settings = get_settings()
    backend = get_backend()
    return backend.run(
        code=code,
        support_files=support_files(),
        timeout=timeout or settings.sandbox_timeout_seconds,
        on_output=on_output,
    )
