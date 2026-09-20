"""Experiment inspection and manual execution."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..api_schemas import ExperimentDetailOut, ExperimentRunOut
from ..config import get_settings
from ..db import get_db
from ..events import bus
from ..models import (
    Artifact,
    Experiment,
    ExperimentRun,
    ExperimentStatus,
    Metric,
    utcnow,
)
from ..sandbox.runner import execute

logger = logging.getLogger(__name__)
router = APIRouter()


def _detail(experiment: Experiment) -> dict:
    return {
        **ExperimentDetailOut.model_validate(
            {
                **experiment.__dict__,
                "metrics": {m.name: m.value for m in experiment.metrics},
                "runs": [ExperimentRunOut.model_validate(r) for r in experiment.runs],
            }
        ).model_dump()
    }


@router.get("/experiments/{experiment_id}", response_model=ExperimentDetailOut)
def get_experiment(experiment_id: str, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return _detail(experiment)


@router.get("/experiments/{experiment_id}/results")
def get_results(experiment_id: str, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    latest = experiment.runs[-1] if experiment.runs else None
    return {
        "id": experiment.id,
        "name": experiment.name,
        "status": experiment.status,
        "metrics": {m.name: m.value for m in experiment.metrics},
        "analysis": experiment.analysis,
        "hypothesis_supported": experiment.hypothesis_supported,
        "artifacts": [
            {"name": a.name, "kind": a.kind, "content": a.content} for a in experiment.artifacts
        ],
        "stdout": latest.stdout if latest else "",
        "stderr": latest.stderr if latest else "",
        "execution_time": latest.execution_time if latest else 0.0,
        "attempts": len(experiment.runs),
    }


@router.get("/experiments/{experiment_id}/code")
def get_code(experiment_id: str, db: Session = Depends(get_db)):
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return {
        "id": experiment.id,
        "name": experiment.name,
        "code": experiment.code,
        "language": "python",
        "repair_attempts": experiment.repair_attempts,
    }


@router.post("/experiments/{experiment_id}/run")
def run_experiment(experiment_id: str, db: Session = Depends(get_db)):
    """Re-execute an experiment's current code in the sandbox.

    Synchronous by design: this is a manual "RUN EXPERIMENT" action from the
    UI, and the caller wants the measured result back.
    """
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if not experiment.code:
        raise HTTPException(status_code=409, detail="experiment has no code to run")

    settings = get_settings()
    attempt = len(experiment.runs) + 1

    bus.publish(
        experiment.run_id,
        {
            "type": "agent_event",
            "agent": "RUNNER",
            "action": "manual_run",
            "status": "info",
            "message": f"Manual re-run of {experiment.name} (attempt {attempt}).",
            "meta": {"experiment_id": experiment.id},
        },
    )

    result = execute(experiment.code, timeout=settings.sandbox_timeout_seconds)

    experiment_run = ExperimentRun(
        experiment_id=experiment.id,
        attempt=attempt,
        status="SUCCEEDED" if result.ok else "FAILED",
        backend=result.backend,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        error=result.error,
        execution_time=result.execution_time,
        raw_result=result.to_dict(),
        code=experiment.code,
        finished_at=utcnow(),
    )
    db.add(experiment_run)
    db.flush()

    if result.ok:
        # Replace the previous measurements for this experiment.
        db.query(Metric).filter(Metric.experiment_id == experiment.id).delete()
        db.query(Artifact).filter(Artifact.experiment_id == experiment.id).delete()
        for name, value in result.metrics.items():
            db.add(
                Metric(
                    experiment_id=experiment.id,
                    experiment_run_id=experiment_run.id,
                    name=name,
                    value=value,
                )
            )
        for artifact in result.artifacts:
            db.add(
                Artifact(
                    experiment_id=experiment.id,
                    name=artifact["name"],
                    kind=artifact.get("kind", "json"),
                    content=artifact.get("content", ""),
                )
            )
        experiment.status = ExperimentStatus.SUCCEEDED.value
    else:
        experiment.status = ExperimentStatus.FAILED.value

    db.commit()

    bus.publish(
        experiment.run_id,
        {
            "type": "agent_event",
            "agent": "RUNNER",
            "action": "manual_run_complete",
            "status": "success" if result.ok else "error",
            "message": (
                f"Manual run completed — F1 = {result.metrics.get('f1', 0):.4f}."
                if result.ok
                else f"Manual run failed: {result.error}"
            ),
            "meta": {"experiment_id": experiment.id, "metrics": result.metrics},
        },
    )
    bus.publish(experiment.run_id, {"type": "graph_update"})

    return result.to_dict()
