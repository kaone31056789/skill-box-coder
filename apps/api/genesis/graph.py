"""Research graph construction for the React Flow view.

Turns the persisted research record into typed nodes and edges. Node kinds are
distinguished so the UI can style question / hypothesis / experiment / result,
and flag the current and best-performing experiments.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import (
    Experiment,
    ExperimentStatus,
    Hypothesis,
    ResearchEdge,
    ResearchRun,
)



# Metrics that are never the point of an experiment -- counts and bookkeeping.
_NON_PRIMARY = {
    "true_positives", "false_positives", "false_negatives", "true_negatives",
    "n_test", "n_train", "execution_time", "runtime_seconds",
}

# Lower is better for these, whatever the experiment forgot to declare.
_MINIMIZE_HINTS = ("loss", "error", "rmse", "mae", "mse", "runtime", "time",
                   "cost", "latency", "fpr", "false_positive_rate")


def primary_metric_of(design: dict[str, Any], metrics: dict[str, float]) -> tuple[str, bool]:
    """Return ``(metric_name, higher_is_better)`` for ranking an experiment.

    Preference order: what the experiment declared, then F1 for the
    classification case, then the first metric that is plausibly a score.
    Without this the lab ranks every domain on an F1 that may not exist.
    """
    declared = design.get("primary_metric")
    if isinstance(declared, str) and declared and declared in metrics:
        return declared, design.get("metric_direction") != "minimize"

    if "f1" in metrics:
        return "f1", True

    for name in metrics:
        if name in _NON_PRIMARY:
            continue
        lowered = name.lower()
        return name, not any(hint in lowered for hint in _MINIMIZE_HINTS)

    return "f1", True


def primary_value(design: dict[str, Any], metrics: dict[str, float]) -> float:
    name, _ = primary_metric_of(design, metrics)
    return metrics.get(name, 0.0)


def rank_key(design: dict[str, Any], metrics: dict[str, float]) -> float:
    """Sortable score where larger is always better."""
    name, higher_is_better = primary_metric_of(design, metrics)
    value = metrics.get(name, 0.0)
    return value if higher_is_better else -value


def build_graph(session: Session, run: ResearchRun) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    question = run.research_question
    nodes.append(
        {
            "id": f"q-{question.id}",
            "kind": "question",
            "label": question.question,
            "data": {"createdAt": question.created_at.isoformat()},
        }
    )

    hypotheses: list[Hypothesis] = sorted(run.hypotheses, key=lambda h: h.index)
    experiments: list[Experiment] = sorted(run.experiments, key=lambda e: e.index)

    running_ids = {
        e.id for e in experiments if e.status == ExperimentStatus.RUNNING.value
    }

    for hypothesis in hypotheses:
        nodes.append(
            {
                "id": f"h-{hypothesis.id}",
                "kind": "hypothesis",
                "label": hypothesis.title,
                "data": {
                    "status": hypothesis.status,
                    "approach": hypothesis.approach,
                    "confidence": hypothesis.confidence,
                    "expectedImprovement": hypothesis.expected_improvement,
                    "difficulty": hypothesis.difficulty,
                    "origin": hypothesis.origin,
                    "rationale": hypothesis.rationale,
                },
            }
        )

    for experiment in experiments:
        metrics = {m.name: m.value for m in experiment.metrics}
        succeeded = experiment.status == ExperimentStatus.SUCCEEDED.value
        failed = experiment.status == ExperimentStatus.FAILED.value

        nodes.append(
            {
                "id": f"e-{experiment.id}",
                "kind": "experiment",
                "label": experiment.name,
                "data": {
                    "status": experiment.status,
                    "index": experiment.index,
                    "isBaseline": experiment.is_baseline,
                    "isBest": experiment.id == run.best_experiment_id,
                    "isCurrent": experiment.id in running_ids,
                    "approach": experiment.design.get("approach"),
                    "featureSet": experiment.design.get("feature_set"),
                    "repairAttempts": experiment.repair_attempts,
                },
            }
        )

        # Every finished experiment gets a result node so success and failure
        # are visually distinct in the graph.
        if succeeded or failed:
            nodes.append(
                {
                    "id": f"r-{experiment.id}",
                    "kind": "result_success" if succeeded else "result_failed",
                    "label": (
                        f"{primary_metric_of(experiment.design, metrics)[0]} "
                        f"{primary_value(experiment.design, metrics):.4g}"
                        if succeeded
                        else "Execution failed"
                    ),
                    "data": {
                        "metrics": metrics,
                        "supported": experiment.hypothesis_supported,
                        "isBest": experiment.id == run.best_experiment_id,
                        "verdict": (experiment.analysis or {}).get("verdict", ""),
                        "error": (experiment.runs[-1].error if experiment.runs else None),
                    },
                }
            )
            edges.append(
                {
                    "id": f"edge-result-{experiment.id}",
                    "source": f"e-{experiment.id}",
                    "target": f"r-{experiment.id}",
                    "relation": "produced",
                }
            )

    node_ids = {n["id"] for n in nodes}
    prefix = {"question": "q-", "hypothesis": "h-", "experiment": "e-", "result": "r-"}

    stored: list[ResearchEdge] = run.edges
    for edge in stored:
        source = f"{prefix.get(edge.source_type, '')}{edge.source_id}"
        target = f"{prefix.get(edge.target_type, '')}{edge.target_id}"
        if source in node_ids and target in node_ids:
            edges.append(
                {
                    "id": f"edge-{edge.id}",
                    "source": source,
                    "target": target,
                    "relation": edge.relation,
                }
            )

    return {
        "nodes": nodes,
        "edges": edges,
        "bestExperimentId": f"e-{run.best_experiment_id}" if run.best_experiment_id else None,
    }


def build_comparison(run: ResearchRun) -> dict[str, Any]:
    """Metric comparison table across all executed experiments."""
    experiments = sorted(
        [e for e in run.experiments if e.status == ExperimentStatus.SUCCEEDED.value],
        key=lambda e: e.index,
    )
    if not experiments:
        return {"rows": [], "baseline": None, "best": None}

    baseline_metrics = {m.name: m.value for m in experiments[0].metrics}
    metric_name, higher_is_better = primary_metric_of(
        experiments[0].design, baseline_metrics
    )
    base_primary = baseline_metrics.get(metric_name, 0.0)
    base_fpr = baseline_metrics.get("false_positive_rate", 0.0)

    rows = []
    for experiment in experiments:
        metrics = {m.name: m.value for m in experiment.metrics}
        primary = metrics.get(metric_name, 0.0)
        fpr = metrics.get("false_positive_rate", 0.0)
        rows.append(
            {
                "id": experiment.id,
                "index": experiment.index,
                "name": experiment.name,
                "approach": experiment.design.get("approach"),
                "featureSet": experiment.design.get("feature_set"),
                "thresholdStrategy": experiment.design.get("threshold_strategy"),
                "isBaseline": experiment.is_baseline,
                "isBest": experiment.id == run.best_experiment_id,
                "hypothesisSupported": experiment.hypothesis_supported,
                "metrics": metrics,
                "executionTime": experiment.runs[-1].execution_time if experiment.runs else 0.0,
                "primaryMetric": metric_name,
                "primaryValue": primary,
                "f1Delta": round(primary - base_primary, 4),
                "f1ImprovementPct": (
                    round((primary - base_primary) / abs(base_primary) * 100, 2)
                    if base_primary
                    else 0.0
                ),
                "fprDelta": round(fpr - base_fpr, 4),
                "fprChangePct": round((fpr - base_fpr) / base_fpr * 100, 2) if base_fpr else 0.0,
            }
        )

    best = max(
        rows,
        key=lambda r: (
            r["primaryValue"] if higher_is_better else -r["primaryValue"]
        ),
    )
    return {
        "rows": rows,
        "baseline": rows[0],
        "best": best,
        "primaryMetric": metric_name,
        "metricDirection": "maximize" if higher_is_better else "minimize",
    }
