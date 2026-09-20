"""Project, research-run and control endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import (
    AgentEventOut,
    CreateProjectRequest,
    CreateRunRequest,
    DecisionOut,
    ExperimentOut,
    HypothesisOut,
    InjectHypothesisRequest,
    PaperOut,
    ProjectOut,
    RunDetailOut,
    RunOut,
)
from ..db import get_db
from ..events import bus
from ..graph import build_comparison, build_graph
from ..models import (
    AgentEvent,
    Hypothesis,
    HypothesisStatus,
    Project,
    ResearchQuestion,
    ResearchRun,
    RunState,
)
from ..orchestrator import manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_run(session: Session, run_id: str) -> ResearchRun:
    run = session.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="research run not found")
    return run


# ------------------------------------------------------------------ projects
@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: CreateProjectRequest, db: Session = Depends(get_db)) -> Project:
    project = Project(name=body.name, domain=body.domain)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


# -------------------------------------------------------------- research runs
@router.post("/research-runs", response_model=RunOut, status_code=201)
def create_run(body: CreateRunRequest, db: Session = Depends(get_db)) -> ResearchRun:
    project = Project(name=body.project_name)
    db.add(project)
    db.flush()

    question = ResearchQuestion(project_id=project.id, question=body.question)
    db.add(question)
    db.flush()

    run = ResearchRun(
        research_question_id=question.id,
        max_experiments=body.max_experiments,
        demo_mode=body.demo_mode,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    logger.info("created research run %s (demo=%s)", run.id, body.demo_mode)
    return run


@router.get("/research-runs", response_model=list[RunOut])
def list_runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return (
        db.execute(select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )


@router.get("/research-runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return {
        **RunOut.model_validate(run).model_dump(),
        "question": run.research_question.question,
        "project": ProjectOut.model_validate(run.research_question.project),
        "papers": [PaperOut.model_validate(p) for p in sorted(run.papers, key=lambda p: -p.relevance)],
        "hypotheses": [
            HypothesisOut.model_validate(h) for h in sorted(run.hypotheses, key=lambda h: h.index)
        ],
        "experiments": [
            ExperimentOut.model_validate(e) for e in sorted(run.experiments, key=lambda e: e.index)
        ],
        "decisions": [
            DecisionOut.model_validate(d) for d in sorted(run.decisions, key=lambda d: d.index)
        ],
        "is_running": manager.is_running(run_id),
    }


# ---------------------------------------------------------------- run control
@router.post("/research-runs/{run_id}/start", response_model=RunOut)
def start_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRun:
    run = _get_run(db, run_id)
    if manager.is_running(run_id):
        raise HTTPException(status_code=409, detail="run is already in progress")
    if run.state == RunState.COMPLETED.value:
        raise HTTPException(status_code=409, detail="run already completed")

    run.stop_requested = False
    run.pause_requested = False
    run.error = None
    db.commit()

    manager.start(run_id)
    db.refresh(run)
    return run


@router.post("/research-runs/{run_id}/pause", response_model=RunOut)
def pause_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRun:
    run = _get_run(db, run_id)
    run.pause_requested = True
    db.commit()
    db.refresh(run)
    return run


@router.post("/research-runs/{run_id}/resume", response_model=RunOut)
def resume_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRun:
    run = _get_run(db, run_id)
    if manager.is_running(run_id):
        raise HTTPException(status_code=409, detail="run is already in progress")

    run.pause_requested = False
    run.stop_requested = False
    db.commit()
    manager.start(run_id)
    db.refresh(run)
    return run


@router.post("/research-runs/{run_id}/stop", response_model=RunOut)
def stop_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRun:
    run = _get_run(db, run_id)
    run.stop_requested = True
    db.commit()
    manager.stop(run_id)
    db.refresh(run)
    return run


# ------------------------------------------------------------------- reading
@router.get("/research-runs/{run_id}/events", response_model=list[AgentEventOut])
def get_events(
    run_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(400, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    _get_run(db, run_id)
    return (
        db.execute(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.seq > after)
            .order_by(AgentEvent.seq)
            .limit(limit)
        )
        .scalars()
        .all()
    )


@router.get("/research-runs/{run_id}/graph")
def get_graph(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return build_graph(db, run)


@router.get("/research-runs/{run_id}/comparison")
def get_comparison(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return build_comparison(run)


@router.get("/research-runs/{run_id}/hypotheses", response_model=list[HypothesisOut])
def get_hypotheses(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return sorted(run.hypotheses, key=lambda h: h.index)


@router.get("/research-runs/{run_id}/experiments", response_model=list[ExperimentOut])
def get_experiments(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return sorted(run.experiments, key=lambda e: e.index)


@router.get("/research-runs/{run_id}/papers", response_model=list[PaperOut])
def get_papers(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return sorted(run.papers, key=lambda p: -p.relevance)


@router.get("/research-runs/{run_id}/decisions", response_model=list[DecisionOut])
def get_decisions(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    return sorted(run.decisions, key=lambda d: d.index)


# ---------------------------------------------------------------- hypotheses
@router.post("/hypotheses", response_model=HypothesisOut, status_code=201)
def inject_hypothesis(body: InjectHypothesisRequest, db: Session = Depends(get_db)) -> Hypothesis:
    """Let a user inject a hypothesis for GENESIS to evaluate next."""
    run = _get_run(db, body.run_id)
    index = len(run.hypotheses)

    description = body.description
    # The orchestrator infers feature_set from the description, so make the
    # user's choice explicit in the text it reads.
    if body.feature_set == "temporal" and "temporal" not in description.lower():
        description = f"{description} Uses the temporal (windowed) feature set.".strip()

    hypothesis = Hypothesis(
        run_id=run.id,
        index=index,
        title=body.title,
        description=description,
        rationale=body.rationale or "Injected by the user for evaluation.",
        expected_outcome="To be determined by execution.",
        assumptions=[],
        approach=body.approach,
        difficulty="medium",
        expected_improvement=0.1,
        confidence=0.5,
        status=HypothesisStatus.PROPOSED.value,
        origin="user",
    )
    db.add(hypothesis)
    db.commit()
    db.refresh(hypothesis)

    bus.publish(run.id, {"type": "graph_update"})
    return hypothesis
