"""Registry of running orchestrator threads."""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from ..db import session_scope
from ..models import RunState, ResearchRun
from .loop import ResearchOrchestrator

logger = logging.getLogger(__name__)

_threads: dict[str, threading.Thread] = {}
_cancels: dict[str, threading.Event] = {}
_lock = threading.Lock()


def is_running(run_id: str) -> bool:
    with _lock:
        thread = _threads.get(run_id)
        return thread is not None and thread.is_alive()


def start(run_id: str) -> bool:
    """Start the research loop for a run. Returns False if already running."""
    with _lock:
        existing = _threads.get(run_id)
        if existing is not None and existing.is_alive():
            return False

        cancel = threading.Event()
        orchestrator = ResearchOrchestrator(run_id, cancel)
        thread = threading.Thread(
            target=orchestrator.run, name=f"genesis-run-{run_id[:8]}", daemon=True
        )
        _threads[run_id] = thread
        _cancels[run_id] = cancel
        thread.start()
        logger.info("started orchestrator thread for run %s", run_id)
        return True


def stop(run_id: str) -> None:
    """Signal the loop to stop at the next phase boundary."""
    with _lock:
        cancel = _cancels.get(run_id)
    if cancel:
        cancel.set()


def recover_interrupted_runs() -> int:
    """Mark runs orphaned by a backend restart as PAUSED so they can be resumed.

    Their experiments, metrics and events are already persisted, so resuming
    picks up from the next experiment rather than starting over.
    """
    active = {
        RunState.RESEARCHING.value,
        RunState.HYPOTHESIS_GENERATION.value,
        RunState.EXPERIMENT_DESIGN.value,
        RunState.CODE_GENERATION.value,
        RunState.RUNNING.value,
        RunState.ANALYZING.value,
        RunState.DECISION.value,
    }
    recovered = 0
    with session_scope() as session:
        runs = (
            session.execute(select(ResearchRun).where(ResearchRun.state.in_(active)))
            .scalars()
            .all()
        )
        for run in runs:
            run.state = RunState.PAUSED.value
            run.pause_requested = False
            recovered += 1
        session.commit()
    if recovered:
        logger.info("recovered %d interrupted run(s) into PAUSED", recovered)
    return recovered
