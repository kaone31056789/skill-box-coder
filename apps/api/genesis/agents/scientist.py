"""SCIENTIST -- generates competing, non-redundant hypotheses."""
from __future__ import annotations

import logging
from typing import Any

from . import strategy
from .graph_strategy import (
    GRAPH_CAPABILITIES,
    is_graph_search_question,
    next_graph_rungs,
)
from .llm import LLMError, get_llm
from .schemas import HypothesisOut, HypothesisSet, ScoutReport

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are SCIENTIST, the hypothesis generator of an autonomous research lab. "
    "You propose competing, falsifiable hypotheses that can be tested by a single "
    "machine-learning experiment on a fixed dataset. Each hypothesis must be "
    "genuinely different from the others and from everything already tried -- vary "
    "the model family, the feature set, or the decision threshold, and say what "
    "would falsify it. Do not restate a hypothesis that has already been tested."
)

# Capability envelope the experiment runner can actually execute. Hypotheses
# outside it would be undeployable, so the prompt states it explicitly.
_ANOMALY_CAPABILITIES = """\
This question is about network anomaly detection, so experiments use the
shipped dataset (dataset_mode="builtin_anomaly").

   approach     : isolation_forest | one_class_svm | random_forest |
                  gradient_boosting | autoencoder | ensemble_adaptive
   feature_set  : base     (8 per-flow features: duration, src_bytes, dst_bytes,
                            packets, pkt_size_mean, dst_port, protocol, tcp_flags)
                  temporal (base + 6 windowed features: unique_dst_ports_60s,
                            flows_from_src_60s, pkt_rate, bytes_ratio,
                            iat_mean_60s, src_entropy_60s)

Dataset: ~6.3k synthetic network flows, ~7.7% anomalies, chronological 70/30
split. Attacks: port scans, DDoS bursts, exfiltration. Benign traffic
deliberately includes attack look-alikes (monitoring sweeps, scheduled backups,
flash crowds), the main source of false positives.
"""

_GENERAL_CAPABILITIES = """\
Experiments for this question are self-contained (dataset_mode="self_contained",
approach="custom"): each experiment generates its own deterministic synthetic
dataset with numpy (seed 42) that embodies the phenomenon being tested, then
trains and evaluates on it.

Constraints the experiment must respect:
  - Libraries: numpy, scipy and scikit-learn ONLY. No network, no downloads,
    no deep-learning frameworks, no real-world datasets.
  - Runtime under 90 seconds, so keep datasets modest (thousands of rows).
  - Report metrics appropriate to the task, and keep the primary metric name
    consistent across experiments so runs stay comparable.

Stay strictly within the subject of the research question. Do NOT reframe it as
network anomaly detection or intrusion detection -- that is a different problem
and would not test this hypothesis.
"""


def capabilities_for(question: str) -> str:
    """Only ever show the envelope the question actually routes to."""
    if is_graph_search_question(question):
        return GRAPH_CAPABILITIES
    if strategy.is_builtin_anomaly_question(question):
        return _ANOMALY_CAPABILITIES
    return _GENERAL_CAPABILITIES


class ScientistAgent:
    name = "SCIENTIST"

    def run(
        self,
        question: str,
        report: ScoutReport | None,
        history: list[dict[str, Any]],
        tried: set[str],
        count: int = 3,
    ) -> list[HypothesisOut]:
        """Propose `count` hypotheses that have not already been tested."""
        llm = get_llm()
        if llm.enabled:
            try:
                proposed = self._from_llm(llm, question, report, history, tried, count)
                proposed = [strategy.route_hypothesis(h, question) for h in proposed]
                fresh = self._drop_duplicates(proposed, tried)
                if fresh:
                    return fresh[:count]
                logger.info("scientist LLM proposed only already-tested designs; falling back")
            except LLMError as exc:
                logger.warning("scientist LLM failed (%s); using strategy ladder", exc)

        if is_graph_search_question(question):
            # A dedicated registry, so a pathfinding run never reports
            # "no untested hypotheses remain" while candidates are left.
            return [
                strategy.route_hypothesis(strategy.rung_to_hypothesis(r), question)
                for r in next_graph_rungs(tried, count)
            ]
        if not strategy.is_builtin_anomaly_question(question):
            # The anomaly ladder names concrete estimators, and returning it here
            # silently produced random-forest experiments on network traffic for
            # a pathfinding question. So fall back to methodological variations
            # instead: they are valid for any self-contained question and cannot
            # assert a domain that was never asked about. Returning nothing was
            # the alternative, and it ended the run after its baseline.
            logger.info(
                "no LLM hypotheses for a non-anomaly question; proposing "
                "methodological variations of the baseline"
            )
            return strategy.generic_variations(tried, count)
        return [strategy.rung_to_hypothesis(r) for r in strategy.next_rungs(tried, count)]

    # ------------------------------------------------------------------
    def _from_llm(
        self,
        llm: Any,
        question: str,
        report: ScoutReport | None,
        history: list[dict[str, Any]],
        tried: set[str],
        count: int,
    ) -> list[HypothesisOut]:
        literature = ""
        if report:
            literature = (
                f"Literature concepts: {', '.join(report.concepts)}\n"
                f"Known methods: {', '.join(report.methods)}\n"
                f"Identified gaps:\n"
                + "\n".join(f"  - {g}" for g in report.gaps)
            )

        if history:
            prior = "\n".join(
                f"  - {h['name']}: approach={h['approach']} features={h['feature_set']} "
                f"-> F1={h['metrics'].get('f1', 0):.3f}, "
                f"FPR={h['metrics'].get('false_positive_rate', 0) * 100:.2f}% "
                f"({'supported' if h.get('supported') else 'not supported'})"
                for h in history
            )
            prior_block = f"Experiments already run and their MEASURED results:\n{prior}\n"
        else:
            prior_block = "No experiments have been run yet.\n"

        result = llm.complete_json(
            SYSTEM,
            (
                f"Research question:\n{question}\n\n"
                f"{literature}\n\n{capabilities_for(question)}\n{prior_block}\n"
                f"Propose {count} competing hypotheses that have NOT been tested yet. "
                "Ground each one in the measured results above where they exist -- "
                "specifically target the error mode the numbers reveal. For each give "
                "title, description, rationale, expected_outcome, assumptions, "
                "dataset_mode, approach, feature_set, difficulty, "
                "expected_improvement (0-1) and confidence (0-1)."
            ),
            HypothesisSet,
            temperature=0.8,
            task="scientist",
        )
        return result.hypotheses

    def _drop_duplicates(
        self, hypotheses: list[HypothesisOut], tried: set[str]
    ) -> list[HypothesisOut]:
        """Remove hypotheses whose experimental configuration was already run."""
        seen = set(tried)
        fresh: list[HypothesisOut] = []
        for hypothesis in hypotheses:
            threshold = strategy.threshold_for(hypothesis.approach, hypothesis.feature_set)
            key = strategy.signature(
                hypothesis.approach,
                hypothesis.feature_set,
                threshold,
                hypothesis.variant,
            )
            if key in seen:
                continue
            seen.add(key)
            fresh.append(hypothesis)
        return fresh

    def baseline(self, question: str, report: ScoutReport | None = None) -> HypothesisOut:
        """The first experiment: a simple, defensible reference point.

        With an LLM available this is derived from the actual research
        question, so a non-anomaly-detection question does not silently get an
        Isolation Forest baseline on network traffic.
        """
        llm = get_llm()
        if llm.enabled:
            literature = ""
            if report:
                literature = f"Literature concepts: {', '.join(report.concepts)}\n"
            try:
                result = llm.complete_json(
                    SYSTEM,
                    (
                        f"Research question:\n{question}\n\n{literature}\n"
                        f"{capabilities_for(question)}\n"
                        "Propose exactly ONE baseline hypothesis: the simplest credible "
                        "approach that establishes a reference point for this question. "
                        "It must not be clever -- later experiments are measured against "
                        "it. Choose the dataset_mode that fits the question."
                    ),
                    HypothesisSet,
                    temperature=0.4,
                    task="scientist",
                )
                if result.hypotheses:
                    return strategy.route_hypothesis(result.hypotheses[0], question)
            except LLMError as exc:
                logger.warning("scientist baseline LLM failed (%s); using ladder", exc)

        # The ladder only describes network anomaly detection. Route it anyway
        # so dataset_mode matches the question rather than silently claiming a
        # network-traffic experiment answers something else.
        if is_graph_search_question(question):
            from .graph_strategy import GRAPH_BASELINE

            return strategy.route_hypothesis(
                strategy.rung_to_hypothesis(GRAPH_BASELINE), question
            )
        return strategy.route_hypothesis(
            strategy.rung_to_hypothesis(strategy.BASELINE), question
        )
