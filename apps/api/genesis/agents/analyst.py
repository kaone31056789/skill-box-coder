"""ANALYST -- interprets measured results against the hypothesis.

Every judgement here is derived from metrics that came out of the sandbox.
The analyst never invents a number: when the LLM is unavailable the verdict is
computed arithmetically from the same measurements.
"""
from __future__ import annotations

import logging
from typing import Any

from ..graph import primary_metric_of
from .llm import LLMError, get_llm
from .schemas import AnalysisReport, ExperimentDesign, HypothesisOut

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are ANALYST, the results analyst of an autonomous research lab. You are "
    "given MEASURED metrics from a real sandbox execution. Interpret only those "
    "numbers -- never invent, round away, or assume a result. State plainly "
    "whether the hypothesis was supported, name the failure mode when it was not, "
    "and recommend a concrete next modification."
)

# Significance is RELATIVE, not absolute. An absolute 0.01 floor only makes
# sense for a 0-1 bounded metric like F1: applied to a runtime measured in
# thousandths of a second it called a 31% speedup "not supported".
SIGNIFICANCE_RELATIVE = 0.01   # 1% relative change in the primary metric
SIGNIFICANCE_DELTA = 0.01      # absolute floor, for 0-1 bounded scores only

# Metrics that genuinely live on a 0-1 scale, identified by NAME. Value range
# is not a usable test: a runtime of 0.0083s also sits inside [0, 1], and
# judging it as a bounded score called a 31% speedup "not supported".
_BOUNDED_SCORES = (
    "f1", "precision", "recall", "accuracy", "auc", "roc",
    "r2", "iou", "map", "ndcg", "specificity", "sensitivity", "rate",
)


def _is_bounded_score(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _BOUNDED_SCORES)


_COUNTS = ("true_positives", "false_positives", "false_negatives", "true_negatives")


def _fmt(metrics: dict[str, float]) -> str:
    """Format whatever the experiment measured -- not an assumed metric set."""
    parts = []
    for key, value in metrics.items():
        if key in _COUNTS:
            parts.append(f"{key}={int(value)}")
        elif key == "false_positive_rate":
            parts.append(f"{key}={value * 100:.2f}%")
        else:
            parts.append(f"{key}={value:.4g}")
    return ", ".join(parts)


class AnalystAgent:
    name = "ANALYST"

    def run(
        self,
        hypothesis: HypothesisOut,
        design: ExperimentDesign,
        metrics: dict[str, float],
        baseline_metrics: dict[str, float] | None,
        history: list[dict[str, Any]],
        execution_time: float,
    ) -> AnalysisReport:
        computed = self._deterministic(hypothesis, design, metrics, baseline_metrics, history)

        llm = get_llm()
        if not llm.enabled:
            return computed

        prior = "\n".join(
            f"  - {h['name']}: F1={h['metrics'].get('f1', 0):.4f}, "
            f"FPR={h['metrics'].get('false_positive_rate', 0) * 100:.2f}%"
            for h in history
        ) or "  (none)"

        baseline_line = (
            f"Baseline measured: {_fmt(baseline_metrics)}"
            if baseline_metrics
            else "This run defines the baseline."
        )

        try:
            report = llm.complete_json(
                SYSTEM,
                (
                    f"Hypothesis: {hypothesis.title}\n"
                    f"Expected outcome: {hypothesis.expected_outcome}\n"
                    f"Method: {design.approach} on the '{design.feature_set}' feature set, "
                    f"threshold strategy '{design.threshold_strategy}'\n\n"
                    f"MEASURED metrics from this run: {_fmt(metrics)}\n"
                    f"Wall-clock execution time: {execution_time:.2f}s\n"
                    f"{baseline_line}\n\n"
                    f"Previous experiments:\n{prior}\n\n"
                    f"An F1 change smaller than {SIGNIFICANCE_DELTA} on this test split "
                    "is within noise and must not be called an improvement.\n\n"
                    "Decide hypothesis_supported (true/false), give a one-sentence verdict, "
                    "3-5 key_findings citing the actual numbers, any failure_modes, and "
                    "2-3 concrete recommendations for the next experiment."
                ),
                AnalysisReport,
                temperature=0.4,
                task="analyst",
            )
            # The support verdict is arithmetic, not editorial. If the model's
            # prose disagrees with the measurement, its verdict line goes too --
            # otherwise the UI shows "SUPPORTED" above text saying the opposite.
            if report.hypothesis_supported != computed.hypothesis_supported:
                logger.info(
                    "analyst narrative disagreed with the measured verdict; "
                    "using the computed one"
                )
                report.verdict = computed.verdict
            report.hypothesis_supported = computed.hypothesis_supported
            if not report.comparison:
                report.comparison = computed.comparison
            return report
        except LLMError as exc:
            logger.warning("analyst LLM failed (%s); using computed analysis", exc)
            return computed

    # ------------------------------------------------------------------
    def _deterministic(
        self,
        hypothesis: HypothesisOut,
        design: ExperimentDesign | None,
        metrics: dict[str, float],
        baseline_metrics: dict[str, float] | None,
        history: list[dict[str, Any]],
    ) -> AnalysisReport:
        # Judge on the metric this experiment actually measured. Assuming F1
        # made a pathfinding run report "SUPPORTED - F1 = 0.0000".
        design_dict = design.model_dump() if design else {}
        metric_name, higher_is_better = primary_metric_of(design_dict, metrics)
        value = metrics.get(metric_name, 0.0)
        precision = metrics.get("precision", 0.0)
        recall = metrics.get("recall", 0.0)
        fpr = metrics.get("false_positive_rate", 0.0)

        findings = [f"Measured {metric_name} = {value:.4g}."]
        if "precision" in metrics and "recall" in metrics:
            findings.append(f"Precision {precision:.4f}, recall {recall:.4f}.")
        if "false_positive_rate" in metrics:
            findings.append(
                f"False-positive rate = {fpr * 100:.2f}% on "
                f"{int(metrics.get('n_test', 0))} held-out samples."
            )
        failure_modes: list[str] = []
        recommendations: list[str] = []

        if baseline_metrics:
            base_value = baseline_metrics.get(metric_name, 0.0)
            raw_delta = value - base_value
            # Normalise so "bigger is better" regardless of direction.
            delta = raw_delta if higher_is_better else -raw_delta
            relative_change = (delta / abs(base_value)) if base_value else 0.0
            relative = relative_change * 100.0
            # A bounded score also has to clear an absolute floor, because 1%
            # of a tiny F1 is still noise. Everything else is judged purely on
            # relative movement, since its scale is arbitrary.
            bounded = _is_bounded_score(metric_name)
            supported = (
                delta >= SIGNIFICANCE_DELTA
                if bounded
                else relative_change >= SIGNIFICANCE_RELATIVE
            )
            comparison = (
                f"{metric_name} {base_value:.4g} -> {value:.4g} "
                f"({raw_delta:+.4g}, {relative:+.1f}% "
                f"{'better' if delta >= 0 else 'worse'})"
            )
            findings.append(comparison)
            if not supported:
                failure_modes.append(
                    f"No significant gain over baseline (Δ{metric_name} = {raw_delta:+.4g}, "
                    f"{relative:+.1f}%) -- within noise."
                )
        else:
            supported = True
            comparison = "First run: this experiment defines the reference point."

        if "recall" in metrics and recall < 0.6:
            failure_modes.append(
                f"Recall {recall:.3f}: a large share of attacks go undetected. "
                "Multi-flow attack behaviour is the most likely blind spot."
            )
            recommendations.append(
                "Add 60-second windowed features so attacks defined across flows "
                "become representable."
            )
        if "precision" in metrics and precision < 0.7 and fpr > 0.02:
            failure_modes.append(
                f"Precision {precision:.3f} with FPR {fpr * 100:.2f}%: benign traffic "
                "resembling attacks is being flagged."
            )
            recommendations.append(
                "Move the decision threshold to a low-density region of the score "
                "distribution to cut false positives."
            )
        if not recommendations:
            recommendations.append(
                "Test robustness under distribution shift before treating this as final."
            )

        verdict = (
            f"Hypothesis SUPPORTED: {hypothesis.title[:90]}"
            if supported
            else f"Hypothesis NOT SUPPORTED: measured {metric_name} {value:.4g} "
            "did not clear the baseline."
        )

        return AnalysisReport(
            hypothesis_supported=supported,
            verdict=verdict,
            key_findings=findings,
            failure_modes=failure_modes,
            recommendations=recommendations[:3],
            comparison=comparison,
            confidence=0.85 if history else 0.7,
        )
