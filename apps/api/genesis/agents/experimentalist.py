"""EXPERIMENTALIST -- turns a hypothesis into a reproducible experiment spec."""
from __future__ import annotations

import logging
from typing import Any

from . import strategy
from .llm import LLMError, get_llm
from .schemas import ExperimentDesign, HypothesisOut

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are EXPERIMENTALIST, the experiment designer of an autonomous research "
    "lab. You convert a hypothesis into a precise, reproducible specification: "
    "dataset, baseline, method, variables, hyperparameters, evaluation metrics and "
    "split. The design must isolate the variable the hypothesis is about -- change "
    "one thing relative to the baseline, not several."
)

_METRICS = ["accuracy", "precision", "recall", "f1", "false_positive_rate", "roc_auc"]


class ExperimentalistAgent:
    name = "EXPERIMENTALIST"

    def run(
        self,
        hypothesis: HypothesisOut,
        index: int,
        baseline_name: str,
        history: list[dict[str, Any]],
        is_baseline: bool = False,
    ) -> ExperimentDesign:
        # A hypothesis about the decision threshold pins it; everything else
        # leaves the choice to the strategy table.
        pinned = hypothesis.threshold_strategy
        threshold = pinned or strategy.threshold_for(
            hypothesis.approach, hypothesis.feature_set
        )
        fallback = self._deterministic(hypothesis, index, baseline_name, threshold, is_baseline)

        llm = get_llm()
        if not llm.enabled:
            return fallback

        try:
            design = llm.complete_json(
                SYSTEM,
                (
                    f"Hypothesis: {hypothesis.title}\n"
                    f"Description: {hypothesis.description}\n"
                    f"Rationale: {hypothesis.rationale}\n"
                    f"Required approach: {hypothesis.approach}\n"
                    f"Required feature_set: {hypothesis.feature_set}\n"
                    f"Required dataset_mode: {hypothesis.dataset_mode}\n"
                    f"Baseline to compare against: {baseline_name}\n\n"
                    # f-string, not %-formatting: this literal is implicitly
                    # concatenated with the f-strings above, so a single "%" in
                    # an LLM-written hypothesis title (e.g. "cuts FPR by 20%")
                    # would be parsed as a format spec and blow up the run.
                    f"Design experiment #{index:03d}. Keep dataset_mode exactly as "
                    "given -- 'self_contained' means the experiment generates its own "
                    "data and must NOT reference the network-flow dataset. List the "
                    "variables being manipulated and give hyperparameters as a flat "
                    "dict of scalars. Keep runtime under 90 seconds."
                ),
                ExperimentDesign,
                temperature=0.5,
                task="experimentalist",
            )
        except LLMError as exc:
            logger.warning("experimentalist LLM failed (%s); using deterministic design", exc)
            return fallback

        # The hypothesis owns the approach and feature set -- the designer may
        # not silently change what is being tested.
        design.approach = hypothesis.approach
        design.feature_set = hypothesis.feature_set
        design.dataset_mode = hypothesis.dataset_mode
        # Only the built-in dataset has fixed columns, splits and metrics; a
        # self-contained experiment defines its own.
        if design.dataset_mode == "builtin_anomaly":
            design.dataset = fallback.dataset
            design.train_test_split = fallback.train_test_split
            design.metrics = _METRICS
        if not design.name:
            design.name = fallback.name
        if not design.baseline:
            design.baseline = baseline_name
        if pinned:
            # The whole point of the experiment is this threshold, so the LLM
            # does not get to quietly design a different one.
            design.threshold_strategy = pinned  # type: ignore[assignment]
        # The variant identifies the hypothesis, not the design, so it is
        # always carried across rather than left to the model to echo back.
        design.variant = hypothesis.variant
        return design

    def _deterministic(
        self,
        hypothesis: HypothesisOut,
        index: int,
        baseline_name: str,
        threshold: str,
        is_baseline: bool,
    ) -> ExperimentDesign:
        variables = [f"model family = {hypothesis.approach}"]
        if hypothesis.feature_set == "temporal":
            variables.append("feature set = base + 60s windowed statistics")
        else:
            variables.append("feature set = per-flow only")
        if threshold != "default":
            variables.append(f"decision threshold = {threshold}")

        graph_search = hypothesis.dataset_mode == "builtin_graph_search"
        if graph_search:
            return ExperimentDesign(
                name=f"EXP-{index:03d} {hypothesis.approach}",
                dataset_mode="builtin_graph_search",
                dataset="genesis_graph 96x96 weighted grid (deterministic, seed=42)",
                approach=hypothesis.approach,
                feature_set="base",
                baseline=(
                    "none (this run defines the optimal reference)"
                    if is_baseline
                    else baseline_name
                ),
                variables=[f"search strategy = {hypothesis.approach}"],
                parameters={},
                metrics=[
                    "path_cost", "optimality_gap_percent", "runtime_ms",
                    "expanded_nodes", "generated_nodes", "path_length",
                ],
                train_test_split="n/a - single fixed instance",
                threshold_strategy="default",
                primary_metric="runtime_ms",
                metric_direction="minimize",
                expected_result=hypothesis.expected_outcome,
            )

        self_contained = hypothesis.dataset_mode == "self_contained"
        return ExperimentDesign(
            name=(
                f"EXP-{index:03d} {hypothesis.approach}"
                + ("" if self_contained else f" / {hypothesis.feature_set}")
            ),
            dataset_mode=hypothesis.dataset_mode,
            dataset=(
                "self-contained synthetic dataset (deterministic, seed=42)"
                if self_contained
                else "synthetic_network_flows_v1 (deterministic, seed=42)"
            ),
            approach=hypothesis.approach,
            feature_set=hypothesis.feature_set,
            baseline="none (this run defines the baseline)" if is_baseline else baseline_name,
            variables=variables,
            parameters={},
            metrics=_METRICS,
            train_test_split="chronological 70/30",
            threshold_strategy=threshold,  # type: ignore[arg-type]
            variant=hypothesis.variant,
            expected_result=hypothesis.expected_outcome,
        )
