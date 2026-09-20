"""SQLAlchemy models for the GENESIS research record.

The entire research run is persisted so a backend restart can recover it.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Enumerations (stored as plain strings for painless migrations)
# --------------------------------------------------------------------------
class RunState(str, enum.Enum):
    CREATED = "CREATED"
    RESEARCHING = "RESEARCHING"
    HYPOTHESIS_GENERATION = "HYPOTHESIS_GENERATION"
    EXPERIMENT_DESIGN = "EXPERIMENT_DESIGN"
    CODE_GENERATION = "CODE_GENERATION"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    DECISION = "DECISION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


TERMINAL_STATES = {RunState.COMPLETED, RunState.FAILED}


class ExperimentStatus(str, enum.Enum):
    DESIGNED = "DESIGNED"
    CODE_READY = "CODE_READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class HypothesisStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    SELECTED = "SELECTED"
    TESTING = "TESTING"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    ABANDONED = "ABANDONED"


class AgentName(str, enum.Enum):
    SCOUT = "SCOUT"
    SCIENTIST = "SCIENTIST"
    EXPERIMENTALIST = "EXPERIMENTALIST"
    ENGINEER = "ENGINEER"
    RUNNER = "RUNNER"
    ANALYST = "ANALYST"
    PI = "PI"
    SYSTEM = "SYSTEM"


# --------------------------------------------------------------------------
# Core tables
# --------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(120), default="network_anomaly_detection")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    research_questions: Mapped[list["ResearchQuestion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ResearchQuestion(Base):
    __tablename__ = "research_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="research_questions")
    runs: Mapped[list["ResearchRun"]] = relationship(
        back_populates="research_question", cascade="all, delete-orphan"
    )


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    research_question_id: Mapped[str] = mapped_column(
        ForeignKey("research_questions.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String(40), default=RunState.CREATED.value)
    # Control flags the orchestrator thread polls between phases.
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    max_experiments: Mapped[int] = mapped_column(Integer, default=3)
    experiments_completed: Mapped[int] = mapped_column(Integer, default=0)
    llm_provider: Mapped[str] = mapped_column(String(40), default="offline")
    sandbox_backend: Mapped[str] = mapped_column(String(40), default="subprocess")
    best_experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    final_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    research_question: Mapped[ResearchQuestion] = relationship(back_populates="runs")
    papers: Mapped[list["Paper"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    experiments: Mapped[list["Experiment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list["AgentEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    edges: Mapped[list["ResearchEdge"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    abstract: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(40), default="arxiv")
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    concepts: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="papers")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True
    )
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    approach: Mapped[str] = mapped_column(String(80), default="isolation_forest")
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    expected_improvement: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(30), default=HypothesisStatus.PROPOSED.value)
    origin: Mapped[str] = mapped_column(String(20), default="scientist")  # or "user"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="hypotheses")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="hypothesis")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True
    )
    index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(30), default=ExperimentStatus.DESIGNED.value)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)

    # Design produced by the Experimentalist
    design: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Code produced by the Engineer (latest revision)
    code: Mapped[str] = mapped_column(Text, default="")
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)

    # Analysis produced by the Analyst
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    hypothesis_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    run: Mapped[ResearchRun] = relationship(back_populates="experiments")
    hypothesis: Mapped[Hypothesis | None] = relationship(back_populates="experiments")
    runs: Mapped[list["ExperimentRun"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentRun(Base):
    """One sandbox execution attempt of an experiment."""

    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    backend: Mapped[str] = mapped_column(String(30), default="subprocess")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_time: Mapped[float] = mapped_column(Float, default=0.0)
    raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    code: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    experiment: Mapped[Experiment] = relationship(back_populates="runs")


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    experiment_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="metrics")

    __table_args__ = (Index("ix_metrics_experiment_name", "experiment_id", "name"),)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(40), default="json")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="artifacts")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="events")

    __table_args__ = (Index("ix_agent_events_run_seq", "run_id", "seq"),)


class ResearchEdge(Base):
    """Typed edge in the research graph."""

    __tablename__ = "research_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(36))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(36))
    relation: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="edges")


class Decision(Base):
    """A Principal Investigator decision with its structured explanation."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(40), default="next_experiment")
    decision: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    selected_hypothesis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expected_value: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cost: Mapped[str] = mapped_column(String(20), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[ResearchRun] = relationship(back_populates="decisions")
