"""Request/response models for the HTTP API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_QUESTION = (
    "Can we improve network anomaly detection while reducing false positives?"
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ requests
class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    domain: str = "network_anomaly_detection"


class CreateRunRequest(BaseModel):
    question: str = Field(default=DEFAULT_QUESTION, min_length=8, max_length=2000)
    project_name: str = Field(default="GENESIS Research", max_length=255)
    max_experiments: int = Field(default=3, ge=1, le=8)
    demo_mode: bool = False


class InjectHypothesisRequest(BaseModel):
    run_id: str
    title: str = Field(min_length=4, max_length=400)
    description: str = ""
    rationale: str = ""
    approach: str = "random_forest"
    feature_set: str = "temporal"


# ----------------------------------------------------------------- responses
class ProjectOut(ORMModel):
    id: str
    name: str
    domain: str
    created_at: datetime


class PaperOut(ORMModel):
    id: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    published: str
    source: str
    relevance: float
    concepts: list[str]


class HypothesisOut(ORMModel):
    id: str
    index: int
    title: str
    description: str
    rationale: str
    expected_outcome: str
    assumptions: list[str]
    approach: str
    difficulty: str
    expected_improvement: float
    confidence: float
    status: str
    origin: str
    created_at: datetime


class MetricOut(ORMModel):
    name: str
    value: float


class ExperimentRunOut(ORMModel):
    id: str
    attempt: int
    status: str
    backend: str
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None
    execution_time: float
    started_at: datetime


class ExperimentOut(ORMModel):
    id: str
    index: int
    name: str
    status: str
    is_baseline: bool
    hypothesis_id: str | None
    design: dict[str, Any]
    analysis: dict[str, Any] | None
    hypothesis_supported: bool | None
    repair_attempts: int
    created_at: datetime


class ExperimentDetailOut(ExperimentOut):
    code: str
    metrics: dict[str, float]
    runs: list[ExperimentRunOut]


class AgentEventOut(ORMModel):
    id: str
    seq: int
    agent: str
    action: str
    status: str
    message: str
    meta: dict[str, Any]
    timestamp: datetime


class DecisionOut(ORMModel):
    id: str
    index: int
    kind: str
    decision: str
    evidence: list[str]
    confidence: float
    selected_hypothesis_id: str | None
    expected_value: float
    estimated_cost: str
    created_at: datetime


class RunOut(ORMModel):
    id: str
    state: str
    demo_mode: bool
    max_experiments: int
    experiments_completed: int
    llm_provider: str
    sandbox_backend: str
    best_experiment_id: str | None
    final_summary: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class RunDetailOut(RunOut):
    question: str
    project: ProjectOut
    papers: list[PaperOut]
    hypotheses: list[HypothesisOut]
    experiments: list[ExperimentOut]
    decisions: list[DecisionOut]
    is_running: bool


class SystemStatusOut(BaseModel):
    llm_provider: str
    llm_model: str
    sandbox_backend: str
    database: str
    arxiv_enabled: bool
