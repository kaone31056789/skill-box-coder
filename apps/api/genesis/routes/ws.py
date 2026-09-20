"""WebSocket endpoint streaming live research events."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..db import SessionLocal
from ..events import bus
from ..models import AgentEvent, ResearchRun
from ..orchestrator import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Keeps proxies (and Railway's edge) from dropping an idle socket.
_HEARTBEAT_SECONDS = 25


def _snapshot(run_id: str) -> dict | None:
    """Current state plus recent events, so a late subscriber catches up."""
    session = SessionLocal()
    try:
        run = session.get(ResearchRun, run_id)
        if run is None:
            return None
        events = (
            session.query(AgentEvent)
            .filter(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.seq.desc())
            .limit(60)
            .all()
        )
        return {
            "type": "snapshot",
            "state": run.state,
            "experimentsCompleted": run.experiments_completed,
            "maxExperiments": run.max_experiments,
            "isRunning": manager.is_running(run_id),
            "events": [
                {
                    "seq": e.seq,
                    "agent": e.agent,
                    "action": e.action,
                    "status": e.status,
                    "message": e.message,
                    "meta": e.meta,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                }
                for e in reversed(events)
            ],
        }
    finally:
        session.close()


@router.websocket("/ws/research-runs/{run_id}")
async def research_socket(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()

    snapshot = await asyncio.to_thread(_snapshot, run_id)
    if snapshot is None:
        await websocket.send_json({"type": "error", "message": "research run not found"})
        await websocket.close(code=4004)
        return
    await websocket.send_json(snapshot)

    queue = bus.subscribe(run_id)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.debug("client disconnected from run %s", run_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("websocket error on run %s: %s", run_id, exc)
    finally:
        bus.unsubscribe(run_id, queue)
