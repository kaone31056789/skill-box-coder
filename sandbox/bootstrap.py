"""Sandbox bootstrap. TRUSTED code that runs before untrusted experiment code.

Copied into the sandbox working directory and invoked as the process entry
point. It hardens the interpreter, then hands control to ``experiment.py``.

Threat model note
-----------------
This bootstrap is *defence in depth*, not a security boundary on its own. A
determined attacker with arbitrary Python execution can undo in-process
patches. The real boundary is the container: CPU/memory caps, a read-only
root filesystem, a dropped network and a non-root user, all applied by
``DockerSandbox``. This file exists so that the ``SubprocessSandbox``
fallback -- used where Docker is unavailable, e.g. on Railway -- still blocks
the accidental and casual cases (a generated script that tries to pip-install
a package, phone home, or read the host environment).
"""
from __future__ import annotations

import builtins
import os
import sys

EXPERIMENT_FILE = "experiment.py"


def _harden() -> None:
    # -- 1. Resource limits (POSIX only; Windows relies on the wall-clock
    #       timeout and, under Docker, on the container's cgroup limits).
    try:
        import resource  # type: ignore[import-not-found]

        mem_bytes = int(os.environ.get("GENESIS_MEM_LIMIT_MB", "1024")) * 1024 * 1024
        cpu_seconds = int(os.environ.get("GENESIS_CPU_LIMIT_S", "120"))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:
        pass

    # -- 2. Kill outbound network. Experiments ship their data with them.
    try:
        import socket

        class _BlockedSocket(socket.socket):
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise OSError(
                    "network access is disabled in the GENESIS sandbox; "
                    "the dataset is available via `import genesis_data`"
                )

        def _blocked(*args: object, **kwargs: object):
            raise OSError("network access is disabled in the GENESIS sandbox")

        socket.socket = _BlockedSocket  # type: ignore[misc,assignment]
        socket.create_connection = _blocked  # type: ignore[assignment]
        socket.getaddrinfo = _blocked  # type: ignore[assignment]
    except Exception:
        pass

    # -- 3. Block process spawning (no pip installs, no shelling out).
    try:
        import subprocess

        def _no_spawn(*args: object, **kwargs: object):
            raise OSError("spawning processes is disabled in the GENESIS sandbox")

        # Popen must stay a *class*: the stdlib subclasses it during import
        # (asyncio.windows_utils does `class Popen(subprocess.Popen)`), so
        # swapping in a function breaks every library that imports asyncio --
        # which includes joblib, and therefore all of scikit-learn.
        class _BlockedPopen(subprocess.Popen):  # type: ignore[misc]
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise OSError("spawning processes is disabled in the GENESIS sandbox")

        subprocess.Popen = _BlockedPopen  # type: ignore[misc,assignment]
        subprocess.run = _no_spawn  # type: ignore[assignment]
        subprocess.call = _no_spawn  # type: ignore[assignment]
        subprocess.check_output = _no_spawn  # type: ignore[assignment]
        os.system = _no_spawn  # type: ignore[assignment]
        for name in ("execv", "execve", "execvp", "spawnv", "spawnve", "fork"):
            if hasattr(os, name):
                setattr(os, name, _no_spawn)
    except Exception:
        pass

    # -- 4. Hide host secrets. The sandbox env is already scrubbed by the
    #       runner; this covers anything the interpreter picked up.
    for key in list(os.environ):
        if key.startswith("GENESIS_"):
            continue
        if any(
            token in key.upper()
            for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE", "DSN", "URL")
        ):
            os.environ.pop(key, None)


def main() -> int:
    # `-E -s` keeps host env/user-site out, but we still need the sandbox
    # working directory importable so the experiment can `import genesis_data`.
    workdir = os.getcwd()
    if workdir not in sys.path:
        sys.path.insert(0, workdir)

    _harden()

    if not os.path.exists(EXPERIMENT_FILE):
        print(f"bootstrap: {EXPERIMENT_FILE} not found", file=sys.stderr)
        return 2

    # Run the untrusted experiment as __main__ so `if __name__ == "__main__"`
    # blocks in generated code fire as the author expects.
    source = open(EXPERIMENT_FILE, encoding="utf-8").read()
    globals_dict: dict[str, object] = {
        "__name__": "__main__",
        "__file__": EXPERIMENT_FILE,
        "__builtins__": builtins,
    }
    code = compile(source, EXPERIMENT_FILE, "exec")
    exec(code, globals_dict)  # noqa: S102 -- executing untrusted code is the point
    return 0


if __name__ == "__main__":
    sys.exit(main())
