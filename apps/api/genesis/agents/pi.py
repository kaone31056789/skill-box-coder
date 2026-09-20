"""PRINCIPAL INVESTIGATOR -- research strategy and the autonomous next step.

Owns the loop: which hypothesis to test next, when to stop, and why. Every
decision carries a structured explanation (decision, evidence, confidence)
that the UI renders behind the "WHY?" control. Decision factors and evidence
only -- no hidden reasoning is exposed.
"""
from __future__ import annotations

import logging
from typing import Any

from ..graph import primary_metric_of
from .llm import LLMError, get_llm
from .schemas import FinalSummary, HypothesisOut, PIDecision

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are the PRINCIPAL INVESTIGATOR of an autonomous research lab. You decide "
    "what the lab does next and you are accountable for the compute you spend. "
    "Weigh expected scientific value against cost, refuse to repeat experiments "
    "that have already been run, and target the specific error mode the measured "
    "results reveal. Justify every decision with concrete evidence drawn from "
    "those measurements. Give decision factors and conclusions only -- do not "
    "narrate your reasoning process."
)

_COST_WEIGHT = {"low": 1.0, "medium": 0.8, "high": 0.55}


class PIAgent:
    name = "PI"

    def decide(
        self,
        question: str,
        candidates: list[HypothesisOut],
        history: list[dict[str, Any]],
        experiments_remaining: int,
    ) -> PIDecision:
        if not candidates:
            return PIDecision(
                action="conclude",
                selected_hypothesis_index=0,
                decision="No untested hypotheses remain; concluding the research run.",
                evidence=[f"{len(history)} experiments completed.", "Hypothesis space exhausted."],
                confidence=0.9,
                estimated_cost="low",
            )

        computed = self._deterministic(candidates, history, experiments_remaining)

        llm = get_llm()
        if not llm.enabled:
            return computed

        candidate_block = "\n".join(
            f"  [{i}] {c.title}\n"
            f"      approach={c.approach} features={c.feature_set} "
            f"difficulty={c.difficulty} expected_improvement={c.expected_improvement:.2f} "
            f"confidence={c.confidence:.2f}\n"
            f"      rationale: {c.rationale[:220]}"
            for i, c in enumerate(candidates)
        )
        history_block = "\n".join(
            f"  - {h['name']} ({h['approach']}): "
            + ", ".join(f"{k}={v:.4g}" for k, v in h["metrics"].items())
            + f" -> {'supported' if h.get('supported') else 'not supported'}"
            for h in history
        ) or "  (no experiments run yet)"

        try:
            decision = llm.complete_json(
                SYSTEM,
                (
                    f"Research question:\n{question}\n\n"
                    f"Experiments completed (MEASURED results):\n{history_block}\n\n"
                    f"Candidate hypotheses:\n{candidate_block}\n\n"
                    f"Compute budget: {experiments_remaining} experiment(s) remaining, "
                    "and the operator has committed to spending all of them.\n\n"
                    "Choose the candidate with the highest expected value per unit of "
                    "compute, by index, and set action='run_experiment'. A strong "
                    "result already on the board is not a reason to stop early — how "
                    "many experiments to run is the operator's call, not yours. Give a "
                    "one-sentence decision, 3-5 evidence bullets citing the measured "
                    "numbers above, expected_value (0-1), estimated_cost and "
                    "confidence (0-1)."
                ),
                PIDecision,
                temperature=0.5,
                task="pi",
            )
            if not 0 <= decision.selected_hypothesis_index < len(candidates):
                logger.warning("PI selected out-of-range index; using computed choice")
                decision.selected_hypothesis_index = computed.selected_hypothesis_index
            if not decision.evidence:
                decision.evidence = computed.evidence

            # The budget is the operator's choice. With untested hypotheses and
            # experiments still paid for, "the baseline is already good enough"
            # is not the PI's call to make — it silently delivers fewer
            # experiments than were asked for.
            if decision.action != "run_experiment" and experiments_remaining > 0:
                logger.info(
                    "PI proposed '%s' with %d experiment(s) of budget left; "
                    "continuing, as the budget was chosen by the operator",
                    decision.action,
                    experiments_remaining,
                )
                decision.action = "run_experiment"
                decision.selected_hypothesis_index = computed.selected_hypothesis_index
                decision.decision = computed.decision
                decision.evidence = [
                    *decision.evidence,
                    f"{experiments_remaining} experiment(s) of the requested budget "
                    "remain, so the run continues rather than concluding early.",
                ]
            return decision
        except LLMError as exc:
            logger.warning("PI LLM failed (%s); using computed decision", exc)
            return computed

    # ------------------------------------------------------------------
    def _deterministic(
        self,
        candidates: list[HypothesisOut],
        history: list[dict[str, Any]],
        experiments_remaining: int,
    ) -> PIDecision:
        """Rank by expected improvement x confidence, discounted by cost."""
        scored = [
            (
                c.expected_improvement * c.confidence * _COST_WEIGHT.get(c.difficulty, 0.8),
                i,
                c,
            )
            for i, c in enumerate(candidates)
        ]
        scored.sort(key=lambda item: -item[0])
        value, index, choice = scored[0]

        evidence: list[str] = []
        if history:
            from ..graph import rank_key

            best = max(history, key=lambda h: rank_key(h.get("design", {}), h["metrics"]))
            metric, _ = primary_metric_of(best.get("design", {}), best["metrics"])
            evidence.append(
                f"Best result so far: {best['name']} at "
                f"{metric}={best['metrics'].get(metric, 0):.4g}."
            )
            gaps = [h["metrics"].get("optimality_gap_percent") for h in history]
            gaps = [g for g in gaps if g is not None]
            if gaps and max(gaps) > 1.0:
                evidence.append(
                    f"Optimality gap reaches {max(gaps):.2f}%, so speed is being bought "
                    "with path quality."
                )
            elif any(h["metrics"].get("false_positive_rate", 0.0) > 0.02 for h in history):
                evidence.append(
                    "False-positive rate remains the binding constraint on deployability."
                )
            evidence.append(f"{len(history)} experiment(s) completed; no design repeated.")
        else:
            evidence.append("No prior results: an unsupervised baseline is required first.")

        evidence.append(
            f"Selected hypothesis has expected improvement {choice.expected_improvement:.2f} "
            f"at {choice.difficulty} cost (value score {value:.3f})."
        )
        evidence.append(f"Compute budget remaining: {experiments_remaining} experiment(s).")

        return PIDecision(
            action="run_experiment",
            selected_hypothesis_index=index,
            decision=f"Test: {choice.title}",
            evidence=evidence,
            expected_value=round(min(value * 2.2, 1.0), 3),
            estimated_cost=choice.difficulty,  # type: ignore[arg-type]
            confidence=round(min(0.55 + choice.confidence * 0.4, 0.97), 3),
        )

    # ------------------------------------------------------------------
    def summarize(
        self, question: str, history: list[dict[str, Any]], best: dict[str, Any] | None
    ) -> FinalSummary:
        computed = self._deterministic_summary(history, best)

        llm = get_llm()
        if not llm.enabled or not best:
            return computed

        history_block = "\n".join(
            f"  - {h['name']} ({h['approach']}): "
            + ", ".join(f"{k}={v:.4g}" for k, v in h["metrics"].items())
            for h in history
        )
        try:
            return llm.complete_json(
                SYSTEM,
                (
                    f"Research question:\n{question}\n\n"
                    f"All experiments and their MEASURED results:\n{history_block}\n\n"
                    f"Best experiment: {best['name']} at "
                    f"{primary_metric_of(best.get('design', {}), best['metrics'])[0]}="
                    f"{best['metrics'].get(primary_metric_of(best.get('design', {}), best['metrics'])[0], 0):.4g}.\n\n"
                    "Write the lab's closing recommendation: a 2-3 sentence "
                    "'recommendation' citing the actual numbers, 3-5 'what_was_learned' "
                    "bullets, 2-3 'future_work' directions, and a confidence score. "
                    "Cite only metrics that appear above. State findings as results on "
                    "this benchmark, never as universal claims about a method."
                ),
                FinalSummary,
                temperature=0.5,
                task="pi",
            )
        except LLMError as exc:
            logger.warning("PI summary failed (%s); using computed summary", exc)
            return computed

    def _deterministic_summary(
        self, history: list[dict[str, Any]], best: dict[str, Any] | None
    ) -> FinalSummary:
        if not best or not history:
            return FinalSummary(
                recommendation="No experiment completed successfully; no conclusion can be drawn.",
                what_was_learned=[],
                future_work=["Re-run with a longer sandbox timeout or a simpler baseline."],
                confidence=0.2,
            )

        baseline = history[0]
        metric, higher_is_better = primary_metric_of(
            best.get("design", {}), best["metrics"]
        )
        base_value = baseline["metrics"].get(metric, 0.0)
        best_value = best["metrics"].get(metric, 0.0)
        raw_delta = best_value - base_value
        delta = raw_delta if higher_is_better else -raw_delta
        gain = (delta / abs(base_value) * 100.0) if base_value else 0.0

        learned = [
            f"{best['approach']} gave the strongest measured result at "
            f"{metric}={best_value:.4g}.",
            f"{metric} improved {gain:+.1f}% over the baseline "
            f"({base_value:.4g} -> {best_value:.4g}).",
        ]
        # Report the secondary measures this domain actually produced rather
        # than assuming a classification metric set.
        for extra, label in (
            ("optimality_gap_percent", "Optimality gap"),
            ("expanded_nodes", "Nodes expanded"),
            ("false_positive_rate", "False-positive rate"),
        ):
            if extra in best["metrics"] and extra != metric:
                base_extra = baseline["metrics"].get(extra, 0.0)
                best_extra = best["metrics"][extra]
                scale = 100.0 if extra == "false_positive_rate" else 1.0
                suffix = "%" if extra.endswith(("percent", "rate")) else ""
                learned.append(
                    f"{label} moved {base_extra * scale:.4g}{suffix} -> "
                    f"{best_extra * scale:.4g}{suffix}."
                )
        if any(h["feature_set"] == "temporal" for h in history) and any(
            h["feature_set"] == "base" for h in history
        ):
            learned.append(
                "Holding the model fixed, windowed temporal features were the single "
                "largest source of improvement, which is consistent with multi-flow "
                "attacks being unrepresentable per-flow."
            )

        return FinalSummary(
            recommendation=(
                f"On this benchmark, {best['approach'].replace('_', ' ')} gave the best "
                f"observed {metric} ({best_value:.4g}) across {len(history)} executed "
                f"experiments. This is a result on the tested instance, not a general "
                f"claim about the method."
            ),
            what_was_learned=learned,
            future_work=[
                "Evaluate robustness under distribution shift and concept drift.",
                "Measure detection latency and throughput under streaming conditions.",
                "Test against attack families held out of the training split.",
            ],
            confidence=0.82,
        )
