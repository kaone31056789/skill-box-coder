"""Pydantic schemas for every structured agent output.

All AI output is validated against these before it touches the database.
Invalid output is rejected and retried rather than trusted.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Approach = Literal[
    "isolation_forest",
    "one_class_svm",
    "random_forest",
    "gradient_boosting",
    "autoencoder",
    "ensemble_adaptive",
    # Escape hatch for research questions outside the built-in anomaly-detection
    # domain: the Engineer writes the whole experiment, data generation included.
    "custom",
]
FeatureSet = Literal["base", "temporal"]
# builtin_anomaly -> use the shipped genesis_data network-flow dataset.
# self_contained  -> the experiment generates its own deterministic dataset.
DatasetMode = Literal["builtin_anomaly", "builtin_graph_search", "self_contained"]
ThresholdStrategy = Literal["default", "adaptive_percentile", "f1_optimized"]
Difficulty = Literal["low", "medium", "high"]


# Anomaly-detection estimators.
_ANOMALY_APPROACHES = {
    "isolation_forest", "one_class_svm", "random_forest",
    "gradient_boosting", "autoencoder", "ensemble_adaptive",
}
# Graph-search strategies. Without these the coercion below rewrote
# "astar_manhattan" to "custom", which stripped every pathfinding hypothesis of
# the algorithm it was actually proposing.
_GRAPH_APPROACHES = {
    "ucs", "astar_manhattan", "astar_euclidean", "weighted_astar",
    "greedy_best_first", "bidirectional_ucs",
}
BUILTIN_APPROACHES = _ANOMALY_APPROACHES | _GRAPH_APPROACHES | {"custom"}


def _coerce_approach(value: object) -> str:
    """Accept any approach name; anything outside the built-ins is `custom`.

    Rejecting unknown names was expensive rather than safe: a pathfinding
    question naturally proposes `a_star`, which failed validation, triggered
    retries, and walked the whole model chain -- minutes per call. An approach
    the templates do not implement simply IS a custom, self-contained
    experiment, so normalise instead of erroring.
    """
    if isinstance(value, str):
        name = value.strip().lower().replace("-", "_").replace(" ", "_")
        if name in BUILTIN_APPROACHES:
            return name
    return "custom"


def _coerce_choice(value: object, allowed: set[str], default: str) -> str:
    if isinstance(value, str):
        name = value.strip().lower().replace("-", "_").replace(" ", "_")
        if name in allowed:
            return name
    return default


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# Scout
# --------------------------------------------------------------------------
class PaperOut(StrictModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    url: str = ""
    published: str = ""
    relevance: float = 0.5
    concepts: list[str] = Field(default_factory=list)

    @field_validator("relevance")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ScoutReport(StrictModel):
    concepts: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.6

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


# --------------------------------------------------------------------------
# Scientist
# --------------------------------------------------------------------------
class HypothesisOut(StrictModel):
    title: str
    description: str = ""
    rationale: str = ""
    expected_outcome: str = ""
    assumptions: list[str] = Field(default_factory=list)
    approach: str = "isolation_forest"
    feature_set: str = "base"
    dataset_mode: DatasetMode = "builtin_anomaly"
    difficulty: str = "medium"
    # Self-contained questions have no built-in estimator to name, so every
    # hypothesis is flattened to approach="custom". This slug keeps them
    # distinguishable; without it they all share one experiment signature.
    variant: str = ""
    # Normally the experimentalist picks the decision threshold. A hypothesis
    # that is *about* the threshold pins it here, so recalibrating is an
    # isolated change rather than a model swap that confounds the comparison.
    threshold_strategy: str = ""

    @field_validator("approach", mode="before")
    @classmethod
    def _norm_approach(cls, v: object) -> str:
        return _coerce_approach(v)

    @field_validator("feature_set", mode="before")
    @classmethod
    def _norm_features(cls, v: object) -> str:
        return _coerce_choice(v, {"base", "temporal"}, "base")

    @field_validator("threshold_strategy", mode="before")
    @classmethod
    def _norm_threshold(cls, v: object) -> str:
        """Empty means "unpinned": let the experimentalist choose."""
        if v is None or v == "":
            return ""
        return _coerce_choice(v, {"default", "adaptive_percentile", "f1_optimized"}, "")

    @field_validator("difficulty", mode="before")
    @classmethod
    def _norm_difficulty(cls, v: object) -> str:
        return _coerce_choice(v, {"low", "medium", "high"}, "medium")
    expected_improvement: float = 0.05
    confidence: float = 0.6

    @field_validator("confidence", "expected_improvement")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class HypothesisSet(StrictModel):
    hypotheses: list[HypothesisOut] = Field(min_length=1)


# --------------------------------------------------------------------------
# Experimentalist
# --------------------------------------------------------------------------
class ExperimentDesign(StrictModel):
    name: str
    dataset_mode: DatasetMode = "builtin_anomaly"
    # Carried from the hypothesis so an executed design can be compared
    # against future proposals (see strategy.signature).
    variant: str = ""
    dataset: str = "synthetic_network_flows_v1"
    approach: str = "isolation_forest"
    feature_set: str = "base"
    baseline: str = "IsolationForest on per-flow features"
    variables: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: list[str] = Field(
        default_factory=lambda: [
            "accuracy",
            "precision",
            "recall",
            "f1",
            "false_positive_rate",
        ]
    )
    train_test_split: str = "chronological 70/30"
    threshold_strategy: str = "default"
    expected_result: str = ""
    # Which measured metric ranks this experiment, and which way is better.
    # Without these the lab falls back to a name heuristic, which cannot know
    # that a shorter path is better.
    primary_metric: str = ""
    metric_direction: str = "maximize"

    @field_validator("approach", mode="before")
    @classmethod
    def _norm_approach(cls, v: object) -> str:
        return _coerce_approach(v)

    @field_validator("feature_set", mode="before")
    @classmethod
    def _norm_features(cls, v: object) -> str:
        return _coerce_choice(v, {"base", "temporal"}, "base")

    @field_validator("threshold_strategy", mode="before")
    @classmethod
    def _norm_threshold(cls, v: object) -> str:
        return _coerce_choice(
            v, {"default", "adaptive_percentile", "f1_optimized"}, "default"
        )

    @field_validator("metric_direction", mode="before")
    @classmethod
    def _norm_direction(cls, v: object) -> str:
        return _coerce_choice(v, {"maximize", "minimize"}, "maximize")

    @field_validator("parameters")
    @classmethod
    def _sane_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Keep only JSON-safe scalars; generated params feed straight into code."""
        clean: dict[str, Any] = {}
        for key, value in list(v.items())[:20]:
            if isinstance(value, (int, float, str, bool)) and not isinstance(value, bool):
                clean[str(key)[:40]] = value
            elif isinstance(value, bool):
                clean[str(key)[:40]] = value
        return clean


# --------------------------------------------------------------------------
# Engineer
# --------------------------------------------------------------------------
class GeneratedCode(StrictModel):
    code: str
    notes: str = ""

    @field_validator("code")
    @classmethod
    def _must_write_results(cls, v: str) -> str:
        if "result.json" not in v:
            raise ValueError("generated code must write its metrics to result.json")
        if len(v) < 120:
            raise ValueError("generated code is implausibly short")
        return v


# --------------------------------------------------------------------------
# Analyst
# --------------------------------------------------------------------------
class AnalysisReport(StrictModel):
    hypothesis_supported: bool
    verdict: str
    key_findings: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    comparison: str = ""
    confidence: float = 0.6

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


# --------------------------------------------------------------------------
# Principal Investigator
# --------------------------------------------------------------------------
class PIDecision(StrictModel):
    """A next-step decision. `selected_hypothesis_index` refers to the
    candidate list the PI was shown, not a database id."""

    action: str = "run_experiment"
    selected_hypothesis_index: int = 0

    @field_validator("action", mode="before")
    @classmethod
    def _norm_action(cls, v: object) -> str:
        return _coerce_choice(
            v, {"run_experiment", "conclude", "abandon"}, "run_experiment"
        )
    decision: str = ""
    evidence: list[str] = Field(default_factory=list)
    expected_value: float = 0.5
    estimated_cost: str = "low"
    confidence: float = 0.7

    @field_validator("confidence", "expected_value")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class FinalSummary(StrictModel):
    recommendation: str
    what_was_learned: list[str] = Field(default_factory=list)
    future_work: list[str] = Field(default_factory=list)
    confidence: float = 0.7

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))
