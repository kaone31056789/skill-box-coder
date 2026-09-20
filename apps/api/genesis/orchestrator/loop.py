"""The GENESIS autonomous research loop.

Runs in a background thread. Every phase transition, agent action and metric is
persisted to the database and published to the event bus, so the UI can follow
along live and a restarted backend can recover the run.

The loop:

    RESEARCHING -> HYPOTHESIS_GENERATION -> EXPERIMENT_DESIGN
      -> CODE_GENERATION -> RUNNING -> ANALYZING -> DECISION -> (repeat)
      -> COMPLETED
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.analyst import AnalystAgent
from ..agents.engineer import MAX_REPAIR_ATTEMPTS, EngineerAgent
from ..agents.experimentalist import ExperimentalistAgent
from ..agents.pi import PIAgent
from ..agents.schemas import ExperimentDesign, HypothesisOut
from ..agents.scientist import ScientistAgent
from ..agents.scout import ScoutAgent
from ..agents import strategy
from ..agents.llm import get_llm, set_llm_enabled
from ..config import get_settings
from ..db import session_scope
from ..events import bus
from ..graph import primary_metric_of, rank_key
from ..models import (
    AgentEvent,
    Artifact,
    Decision,
    Experiment,
    ExperimentRun,
    ExperimentStatus,
    Hypothesis,
    HypothesisStatus,
    Metric,
    Paper,
    ResearchEdge,
    ResearchRun,
    RunState,
    utcnow,
)
from ..sandbox.runner import execute, get_backend

logger = logging.getLogger(__name__)


class RunStopped(Exception):
    """Raised internally when the user stops the run."""


class RunPaused(Exception):
    """Raised internally when the user pauses the run."""


class ResearchOrchestrator:
    def __init__(self, run_id: str, cancel_event: threading.Event) -> None:
        self.run_id = run_id
        self.cancel = cancel_event
        self.scout = ScoutAgent()
        self.scientist = ScientistAgent()
        self.experimentalist = ExperimentalistAgent()
        self.engineer = EngineerAgent()
        self.analyst = AnalystAgent()
        self.pi = PIAgent()
        self._seq = 0

    # ------------------------------------------------------------------ util
    def _emit(
        self,
        session: Session,
        agent: str,
        action: str,
        message: str,
        status: str = "info",
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._seq += 1
        event = AgentEvent(
            run_id=self.run_id,
            seq=self._seq,
            agent=agent,
            action=action,
            status=status,
            message=message,
            meta=meta or {},
        )
        session.add(event)
        session.commit()
        bus.publish(
            self.run_id,
            {
                "type": "agent_event",
                "seq": self._seq,
                "agent": agent,
                "action": action,
                "status": status,
                "message": message,
                "meta": meta or {},
                "timestamp": event.timestamp.isoformat()
                if event.timestamp
                else datetime.now(timezone.utc).isoformat(),
            },
        )

    def _set_state(self, session: Session, run: ResearchRun, state: RunState) -> None:
        run.state = state.value
        run.updated_at = utcnow()
        session.commit()
        bus.publish(self.run_id, {"type": "state", "state": state.value})

    def _checkpoint(self, session: Session, run: ResearchRun) -> None:
        """Honour pause/stop requests between phases."""
        session.refresh(run)
        if self.cancel.is_set() or run.stop_requested:
            raise RunStopped
        if run.pause_requested:
            raise RunPaused

    def _next_seq(self, session: Session) -> None:
        last = session.execute(
            select(AgentEvent.seq)
            .where(AgentEvent.run_id == self.run_id)
            .order_by(AgentEvent.seq.desc())
            .limit(1)
        ).scalar()
        self._seq = int(last or 0)

    def _edge(
        self,
        session: Session,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation: str,
    ) -> None:
        session.add(
            ResearchEdge(
                run_id=self.run_id,
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                relation=relation,
            )
        )
        session.commit()
        bus.publish(self.run_id, {"type": "graph_update"})

    # -------------------------------------------------------------- history
    def _history(self, session: Session) -> list[dict[str, Any]]:
        """Measured results of every completed experiment, oldest first."""
        experiments = (
            session.execute(
                select(Experiment)
                .where(
                    Experiment.run_id == self.run_id,
                    Experiment.status == ExperimentStatus.SUCCEEDED.value,
                )
                .order_by(Experiment.index)
            )
            .scalars()
            .all()
        )
        history = []
        for experiment in experiments:
            metrics = {m.name: m.value for m in experiment.metrics}
            history.append(
                {
                    "id": experiment.id,
                    "name": experiment.name,
                    "index": experiment.index,
                    "approach": experiment.design.get("approach", "unknown"),
                    "feature_set": experiment.design.get("feature_set", "base"),
                    "threshold_strategy": experiment.design.get("threshold_strategy", "default"),
                    "design": dict(experiment.design or {}),
                    "metrics": metrics,
                    "supported": experiment.hypothesis_supported,
                }
            )
        return history

    # Recalibrating the cut-off is the cheapest fix for a detector that never
    # fires, and it changes one variable rather than the model family.
    _RECOVERY_THRESHOLD = "f1_optimized"

    def _recovery_hypothesis(
        self, history: list[dict[str, Any]], tried: set[str]
    ) -> HypothesisOut | None:
        """Repair a run whose last experiment detected nothing at all.

        An experiment can exit cleanly, report every metric, and still be
        useless: if the model labels nothing as an anomaly, precision, recall
        and F1 are all zero and no hypothesis about *features* can be judged
        from it. Left alone the lab treats that as a measured result, ranks it
        as the best available, and reasons about the next experiment from a
        number that means nothing. So the next experiment fixes the threshold
        instead, holding the model and features constant.

        Returns ``None`` once the calibration has been tried, so a genuinely
        unlearnable setup falls through to the scientist rather than looping.
        """
        if not history:
            return None
        last = history[-1]
        metrics = last.get("metrics") or {}

        f1 = metrics.get("f1")
        recall = metrics.get("recall")
        positives = metrics.get("true_positives")
        alarms = metrics.get("false_positives")

        flagged_nothing = positives == 0 and alarms == 0
        found_nothing = f1 == 0 and recall == 0
        # Absent metrics (a graph-search run, say) fail both tests by design.
        if not (flagged_nothing or found_nothing):
            return None

        design = last.get("design") or {}
        approach = last.get("approach") or "isolation_forest"
        feature_set = last.get("feature_set") or "base"
        variant = design.get("variant", "")
        if (
            strategy.signature(
                approach, feature_set, self._RECOVERY_THRESHOLD, variant
            )
            in tried
        ):
            return None

        roc_auc = metrics.get("roc_auc")
        ranks_correctly = isinstance(roc_auc, (int, float)) and roc_auc > 0.6
        evidence = (
            f"ROC AUC is {roc_auc:.3f}, so the scores already separate anomalies from "
            "normal traffic and only the cut-off is wrong."
            if ranks_correctly
            else "The scores may still carry signal that the current cut-off discards."
        )

        return HypothesisOut(
            title=(
                f"Calibrating the decision threshold recovers detections from "
                f"{approach}"
            ),
            description=(
                "Hold the model family and feature set fixed and choose the "
                "decision threshold that maximises F1 on the training scores, "
                "instead of the fixed prior-based cut-off."
            ),
            rationale=(
                f"{last.get('name', 'The previous experiment')} flagged nothing as an "
                f"anomaly, so precision, recall and F1 are all zero. {evidence} Until "
                "the detector fires at all, no feature-engineering hypothesis can be "
                "judged on this benchmark."
            ),
            expected_outcome=(
                "Non-zero recall and F1, giving a usable reference point for the "
                "feature-engineering comparison."
            ),
            assumptions=[
                "The anomaly scores are ranked correctly and only the cut-off is wrong.",
                "The training score distribution is representative of the test split.",
            ],
            approach=approach,
            feature_set=feature_set,
            dataset_mode=design.get("dataset_mode") or "builtin_anomaly",
            difficulty="low",
            threshold_strategy=self._RECOVERY_THRESHOLD,
            variant=variant,
        )

    def _tried(self, session: Session) -> set[str]:
        """Configurations already executed, so nothing is repeated."""
        experiments = (
            session.execute(select(Experiment).where(Experiment.run_id == self.run_id))
            .scalars()
            .all()
        )
        return {
            strategy.signature(
                e.design.get("approach", ""),
                e.design.get("feature_set", ""),
                e.design.get("threshold_strategy", "default"),
                e.design.get("variant", ""),
            )
            for e in experiments
        }

    # ------------------------------------------------------------------ main
    def run(self) -> None:
        try:
            with session_scope() as session:
                run = session.get(ResearchRun, self.run_id)
                if run is None:
                    logger.error("run %s vanished", self.run_id)
                    return
                self._next_seq(session)
                self._execute(session, run)
        except RunStopped:
            self._finalise_control(RunState.COMPLETED, "Run stopped by user.")
        except RunPaused:
            self._finalise_control(RunState.PAUSED, "Run paused by user.")
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            logger.exception("research run %s failed", self.run_id)
            self._finalise_control(RunState.FAILED, f"Run failed: {exc}", error=str(exc))

    def _finalise_control(
        self, state: RunState, message: str, error: str | None = None
    ) -> None:
        with session_scope() as session:
            run = session.get(ResearchRun, self.run_id)
            if run is None:
                return
            run.state = state.value
            run.pause_requested = False
            if error:
                run.error = error
            if state in (RunState.COMPLETED, RunState.FAILED):
                run.completed_at = utcnow()
            session.commit()
            self._emit(
                session,
                "SYSTEM",
                state.value.lower(),
                message,
                status="error" if state == RunState.FAILED else "info",
            )
            bus.publish(self.run_id, {"type": "state", "state": state.value})

    # ------------------------------------------------------------------ flow
    def _execute(self, session: Session, run: ResearchRun) -> None:
        question = run.research_question.question
        settings = get_settings()

        # A demo must not be hostage to model latency or a provider outage.
        # Deterministic agents finish the loop in seconds; the metrics still
        # come from real sandbox execution either way.
        set_llm_enabled(not run.demo_mode)

        # The deterministic agents only cover network anomaly detection. Running
        # them against another domain would execute a network-traffic
        # experiment and present it as an answer -- refuse instead.
        from ..agents.graph_strategy import is_graph_search_question

        covered_offline = strategy.is_builtin_anomaly_question(
            question
        ) or is_graph_search_question(question)
        if not get_llm().enabled and not covered_offline:
            raise RuntimeError(
                "Deterministic agents cover network anomaly detection and graph "
                "search only, and no language model is available for this run. "
                "Configure a model (OPENROUTER_API_KEY) to research this question, "
                "or start it without demo mode."
            )

        run.llm_provider = "deterministic (demo)" if run.demo_mode else settings.resolved_provider
        run.sandbox_backend = get_backend().name
        session.commit()

        self._emit(
            session,
            "SYSTEM",
            "run_started",
            (
                "Demo run — deterministic agents for speed; experiments still "
                f"execute for real in the {run.sandbox_backend} sandbox."
                if run.demo_mode
                else f"Research run started — reasoning via {run.llm_provider}, "
                f"execution via {run.sandbox_backend} sandbox."
            ),
            meta={"llm_provider": run.llm_provider, "sandbox": run.sandbox_backend},
        )

        # -- Phase 1: literature -------------------------------------------
        if not run.papers:
            self._phase_scout(session, run, question)
        self._checkpoint(session, run)

        # A restart can leave an experiment designed or coded but never run.
        # Finish it before starting anything new.
        self._resume_stranded_experiment(session, run)

        # -- Phases 2-7: the experiment loop --------------------------------
        while run.experiments_completed < run.max_experiments:
            self._checkpoint(session, run)
            history = self._history(session)
            tried = self._tried(session)

            hypothesis, hypothesis_row_id = self._phase_decide(
                session, run, question, history, tried
            )
            if hypothesis is None:
                break

            experiment = self._phase_design_and_build(
                session,
                run,
                hypothesis,
                hypothesis_row_id,
                history,
                is_baseline=not history,
            )
            self._checkpoint(session, run)

            succeeded = self._phase_run(session, run, experiment)
            self._checkpoint(session, run)

            if succeeded:
                self._phase_analyse(session, run, experiment, hypothesis, history)
            else:
                self._phase_handle_failure(session, run, experiment)

            run.experiments_completed += 1
            session.commit()
            bus.publish(self.run_id, {"type": "graph_update"})

        self._phase_conclude(session, run, question)

    # --------------------------------------------------------------- resume
    def _resume_stranded_experiment(self, session: Session, run: ResearchRun) -> None:
        """Complete an experiment interrupted mid-flight by a restart.

        Without this, resuming abandons the in-flight experiment: the loop
        starts a fresh iteration and the old one sits in DESIGNED forever,
        cluttering the graph and never counting toward the budget.
        """
        stranded = session.execute(
            select(Experiment)
            .where(
                Experiment.run_id == self.run_id,
                Experiment.status.in_(
                    [
                        ExperimentStatus.DESIGNED.value,
                        ExperimentStatus.CODE_READY.value,
                        ExperimentStatus.RUNNING.value,
                    ]
                ),
            )
            .order_by(Experiment.index.desc())
            .limit(1)
        ).scalar_one_or_none()

        if stranded is None:
            return

        self._emit(
            session,
            "SYSTEM",
            "resuming_experiment",
            f"Resuming {stranded.name}, interrupted at {stranded.status.lower()}.",
            meta={"experiment_id": stranded.id, "status": stranded.status},
        )

        design = ExperimentDesign.model_validate(stranded.design)
        hypothesis_row = (
            session.get(Hypothesis, stranded.hypothesis_id)
            if stranded.hypothesis_id
            else None
        )
        hypothesis = (
            self._to_out(hypothesis_row)
            if hypothesis_row
            else self.scientist.baseline(run.research_question.question)
        )

        # The code may never have been written, or written but not persisted.
        if not stranded.code:
            self._set_state(session, run, RunState.CODE_GENERATION)
            code, origin = self.engineer.generate(design, hypothesis.title)
            stranded.code = code
            stranded.status = ExperimentStatus.CODE_READY.value
            session.commit()
            self._emit(
                session,
                "ENGINEER",
                "code_generated",
                f"Regenerated experiment code ({len(code.splitlines())} lines, {origin}).",
                status="success",
                meta={"experiment_id": stranded.id, "origin": origin},
            )

        history = self._history(session)
        if self._phase_run(session, run, stranded):
            self._phase_analyse(session, run, stranded, hypothesis, history)
        else:
            self._phase_handle_failure(session, run, stranded)

        run.experiments_completed += 1
        session.commit()
        bus.publish(self.run_id, {"type": "graph_update"})

    # ---------------------------------------------------------------- scout
    def _phase_scout(self, session: Session, run: ResearchRun, question: str) -> None:
        self._set_state(session, run, RunState.RESEARCHING)
        self._emit(session, "SCOUT", "search_started", f"Searching literature for: {question}")

        papers, report, source, fallback_reason = self.scout.run(question)

        for record in papers:
            session.add(
                Paper(
                    run_id=self.run_id,
                    title=record.title,
                    authors=record.authors,
                    abstract=record.abstract,
                    url=record.url,
                    published=record.published,
                    source=record.source,
                    relevance=record.relevance,
                    concepts=record.concepts,
                )
            )
        session.commit()

        label = {"arxiv": "live arXiv", "curated": "curated offline corpus", "mixed": "arXiv + curated corpus"}
        # Name the reason for a fallback. "Using the curated corpus" on its own
        # looks like a choice; it is usually an outage or an empty result set,
        # and the operator can only act on it if the run says which.
        because = f" — {fallback_reason}" if fallback_reason else ""
        self._emit(
            session,
            "SCOUT",
            "papers_found",
            f"Found {len(papers)} relevant papers via {label.get(source, source)}{because}.",
            status="warning" if fallback_reason else "success",
            meta={"count": len(papers), "source": source, "fallback_reason": fallback_reason},
        )
        self._emit(
            session,
            "SCOUT",
            "gaps_identified",
            f"Extracted {len(report.concepts)} concepts and {len(report.gaps)} research gaps.",
            meta={
                "concepts": report.concepts,
                "methods": report.methods,
                "gaps": report.gaps,
                "summary": report.summary,
            },
        )

    # --------------------------------------------------------------- decide
    def _phase_decide(
        self,
        session: Session,
        run: ResearchRun,
        question: str,
        history: list[dict[str, Any]],
        tried: set[str],
    ) -> tuple[HypothesisOut | None, str | None]:
        """Generate candidates and let the PI choose the next experiment.

        Returns the chosen hypothesis and the id of its stored row, so the
        experiment can be linked to it without re-querying by status.
        """
        self._set_state(session, run, RunState.HYPOTHESIS_GENERATION)

        # A user-injected hypothesis jumps the queue -- the judge's input is
        # evaluated next rather than competing on expected value.
        injected = session.execute(
            select(Hypothesis)
            .where(
                Hypothesis.run_id == self.run_id,
                Hypothesis.origin == "user",
                Hypothesis.status == HypothesisStatus.PROPOSED.value,
            )
            .order_by(Hypothesis.created_at)
            .limit(1)
        ).scalar_one_or_none()

        if injected is not None:
            self._emit(
                session,
                "PI",
                "hypothesis_injected",
                f"Prioritising user-injected hypothesis: {injected.title}",
                status="success",
                meta={"hypothesis_id": injected.id},
            )
            injected.status = HypothesisStatus.SELECTED.value
            session.commit()
            return self._to_out(injected), injected.id

        # A detector that fired at nothing has to be repaired before anything
        # else is worth measuring against it.
        recovery = self._recovery_hypothesis(history, tried)
        if recovery is not None:
            next_index = len(
                session.query(Hypothesis).filter_by(run_id=self.run_id).all()
            )
            stored = self._store_hypothesis(session, run, recovery, index=next_index)
            stored.status = HypothesisStatus.SELECTED.value
            session.commit()
            decision = self._store_decision(
                session,
                run,
                index=run.experiments_completed,
                decision=f"Recover from a zero-detection result: {recovery.title}",
                evidence=[
                    recovery.rationale,
                    "Model family and feature set are held constant, so the threshold "
                    "is the only variable that changed.",
                    "No feature hypothesis can be judged against a detector that never "
                    "fires.",
                ],
                confidence=0.8,
                hypothesis_id=stored.id,
                cost="low",
                expected_value=0.6,
            )
            self._emit(
                session,
                "PI",
                "recovering_from_no_detections",
                "Previous experiment detected nothing; recalibrating the decision "
                "threshold before testing any further hypothesis.",
                status="warning",
                meta={"decision_id": decision.id, "hypothesis_id": stored.id},
            )
            return recovery, stored.id

        if not history:
            # First experiment is always the baseline: nothing to compare against yet.
            hypothesis_out = self.scientist.baseline(question)
            stored = self._store_hypothesis(session, run, hypothesis_out, index=0)
            stored.status = HypothesisStatus.SELECTED.value
            session.commit()
            decision = self._store_decision(
                session,
                run,
                index=0,
                decision=(
                    "Establish a reference point before testing any improvement: "
                    f"{hypothesis_out.title}"
                ),
                # Derived from the baseline that was actually chosen. Hardcoded
                # copy here used to describe an Isolation Forest on network
                # traffic no matter what the question was, so a feature-selection
                # run explained itself in terms of a dataset it never touched.
                evidence=[
                    "No experiment has been run yet, so there is nothing to measure an "
                    "improvement against.",
                    (
                        hypothesis_out.rationale
                        or hypothesis_out.description
                        or f"{hypothesis_out.approach} is the simplest credible approach "
                        "for this question, so it makes an honest reference point."
                    ),
                    "Every later experiment is measured against this run on the same "
                    "split and the same metrics.",
                ],
                confidence=0.92,
                hypothesis_id=stored.id,
                cost="low",
                expected_value=0.3,
            )
            self._emit(
                session,
                "PI",
                "baseline_selected",
                "Baseline experiment selected to establish the reference point.",
                status="success",
                meta={"decision_id": decision.id, "hypothesis_id": stored.id},
            )
            return hypothesis_out, stored.id

        # Generate competing candidates.
        self._emit(
            session,
            "SCIENTIST",
            "generating",
            "Generating competing hypotheses from the measured results so far…",
        )
        report = None
        candidates = self.scientist.run(question, report, history, tried, count=3)
        if not candidates:
            # Distinguish a genuinely exhausted ladder from the scientist simply
            # failing to produce anything: after one experiment the search space
            # is obviously not exhausted, and saying so sent operators looking
            # for a methodology limit that was not there.
            budget_left = max(run.max_experiments - run.experiments_completed, 0)
            self._emit(
                session,
                "SCIENTIST",
                "no_candidates",
                (
                    "Could not propose an untested hypothesis, so the run ends with "
                    f"{budget_left} experiment(s) of budget unspent."
                    if budget_left
                    else "No untested hypotheses remain in the search space."
                ),
                status="warning",
                meta={"budget_remaining": budget_left},
            )
            return None, None

        base_index = len(session.query(Hypothesis).filter_by(run_id=self.run_id).all())
        stored_list = [
            self._store_hypothesis(session, run, c, index=base_index + i)
            for i, c in enumerate(candidates)
        ]
        self._emit(
            session,
            "SCIENTIST",
            "hypotheses_generated",
            f"Generated {len(candidates)} competing hypotheses.",
            status="success",
            meta={
                "count": len(candidates),
                "titles": [c.title for c in candidates],
                "hypothesis_ids": [h.id for h in stored_list],
            },
        )

        self._set_state(session, run, RunState.DECISION)
        self._emit(
            session,
            "PI",
            "deliberating",
            f"Weighing {len(candidates)} candidate hypotheses against expected value "
            "and compute cost…",
        )
        remaining = run.max_experiments - run.experiments_completed
        pi_decision = self.pi.decide(question, candidates, history, remaining)

        if pi_decision.action != "run_experiment":
            self._emit(
                session,
                "PI",
                "concluded",
                pi_decision.decision or "Concluding: no candidate justifies the remaining budget.",
                status="info",
                meta={"evidence": pi_decision.evidence},
            )
            return None, None

        index = min(max(pi_decision.selected_hypothesis_index, 0), len(candidates) - 1)
        chosen = candidates[index]
        chosen_row = stored_list[index]
        chosen_row.status = HypothesisStatus.SELECTED.value
        session.commit()

        decision = self._store_decision(
            session,
            run,
            index=run.experiments_completed,
            decision=pi_decision.decision or f"Test: {chosen.title}",
            evidence=pi_decision.evidence,
            confidence=pi_decision.confidence,
            hypothesis_id=chosen_row.id,
            cost=pi_decision.estimated_cost,
            expected_value=pi_decision.expected_value,
        )
        self._emit(
            session,
            "PI",
            "experiment_selected",
            f"Selected hypothesis #{index + 1}: {chosen.title}",
            status="success",
            meta={
                "decision_id": decision.id,
                "hypothesis_id": chosen_row.id,
                "confidence": pi_decision.confidence,
                "evidence": pi_decision.evidence,
            },
        )
        return chosen, chosen_row.id

    # ------------------------------------------------------- design + build
    def _phase_design_and_build(
        self,
        session: Session,
        run: ResearchRun,
        hypothesis: HypothesisOut,
        hypothesis_row_id: str | None,
        history: list[dict[str, Any]],
        is_baseline: bool,
    ) -> Experiment:
        self._set_state(session, run, RunState.EXPERIMENT_DESIGN)
        index = run.experiments_completed + 1

        # Defence in depth. Whatever produced this hypothesis, it must belong to
        # the question's domain: an anomaly-detection experiment answering a
        # pathfinding question is worse than no experiment, because it looks
        # like a result.
        strategy.route_hypothesis(hypothesis, run.research_question.question)

        baseline_name = history[0]["name"] if history else "none"
        self._emit(
            session,
            "EXPERIMENTALIST",
            "designing",
            f"Designing experiment #{index:03d} for: {hypothesis.title[:90]}",
        )
        design = self.experimentalist.run(
            hypothesis, index, baseline_name, history, is_baseline=is_baseline
        )

        hypothesis_row = (
            session.get(Hypothesis, hypothesis_row_id) if hypothesis_row_id else None
        )

        experiment = Experiment(
            run_id=self.run_id,
            hypothesis_id=hypothesis_row.id if hypothesis_row else None,
            index=index,
            name=design.name,
            status=ExperimentStatus.DESIGNED.value,
            is_baseline=is_baseline,
            design=design.model_dump(),
        )
        session.add(experiment)
        session.commit()

        if hypothesis_row:
            hypothesis_row.status = HypothesisStatus.TESTING.value
            session.commit()
            self._edge(session, "hypothesis", hypothesis_row.id, "experiment", experiment.id, "tested_by")

        self._emit(
            session,
            "EXPERIMENTALIST",
            "experiment_designed",
            f"Designed {design.name}.",
            status="success",
            meta={
                "experiment_id": experiment.id,
                "approach": design.approach,
                "feature_set": design.feature_set,
                "threshold_strategy": design.threshold_strategy,
                "variables": design.variables,
            },
        )

        # -- code generation
        self._set_state(session, run, RunState.CODE_GENERATION)
        self._emit(
            session,
            "ENGINEER",
            "writing_code",
            f"Writing experiment code for {design.name} "
            f"({design.approach}, {design.dataset_mode})…",
        )
        code, origin = self.engineer.generate(design, hypothesis.title)
        experiment.code = code
        experiment.status = ExperimentStatus.CODE_READY.value
        session.commit()

        self._emit(
            session,
            "ENGINEER",
            "code_generated",
            f"Generated experiment code ({len(code.splitlines())} lines, {origin}).",
            status="success",
            meta={"experiment_id": experiment.id, "lines": len(code.splitlines()), "origin": origin},
        )
        return experiment

    # ------------------------------------------------------------------ run
    def _phase_run(self, session: Session, run: ResearchRun, experiment: Experiment) -> bool:
        """Execute in the sandbox, repairing up to MAX_REPAIR_ATTEMPTS times."""
        self._set_state(session, run, RunState.RUNNING)
        settings = get_settings()
        design = ExperimentDesign.model_validate(experiment.design)

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
            self._checkpoint(session, run)
            experiment.status = ExperimentStatus.RUNNING.value
            session.commit()

            self._emit(
                session,
                "RUNNER",
                "sandbox_started",
                f"Sandbox started for {experiment.name} (attempt {attempt}).",
                meta={"experiment_id": experiment.id, "attempt": attempt},
            )

            # Stream the experiment's stdout straight to the UI. These are
            # published, not persisted -- the full stdout is stored with the
            # ExperimentRun below.
            def _stream(line: str, _exp_id: str = experiment.id) -> None:
                bus.publish(
                    self.run_id,
                    {"type": "experiment_output", "experiment_id": _exp_id, "line": line},
                )

            result = execute(
                experiment.code,
                timeout=settings.sandbox_timeout_seconds,
                on_output=_stream,
            )

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
            session.add(experiment_run)
            session.commit()

            if result.ok:
                for name, value in result.metrics.items():
                    session.add(
                        Metric(
                            experiment_id=experiment.id,
                            experiment_run_id=experiment_run.id,
                            name=name,
                            value=value,
                        )
                    )
                for artifact in result.artifacts:
                    session.add(
                        Artifact(
                            experiment_id=experiment.id,
                            name=artifact["name"],
                            kind=artifact.get("kind", "json"),
                            content=artifact.get("content", ""),
                        )
                    )
                # Record how this experiment asked to be ranked, so a
                # non-classification run is not scored on a missing F1.
                if result.primary_metric:
                    design = dict(experiment.design or {})
                    design["primary_metric"] = result.primary_metric
                    design["metric_direction"] = result.metric_direction
                    experiment.design = design
                experiment.status = ExperimentStatus.SUCCEEDED.value
                session.commit()

                metric_name, _ = primary_metric_of(
                    experiment.design, result.metrics
                )
                headline = result.metrics.get(metric_name, 0.0)
                self._emit(
                    session,
                    "RUNNER",
                    "experiment_completed",
                    f"Experiment completed in {result.execution_time:.1f}s — "
                    f"{metric_name} = {headline:.4g}.",
                    status="success",
                    meta={
                        "experiment_id": experiment.id,
                        "metrics": result.metrics,
                        "execution_time": result.execution_time,
                    },
                )
                return True

            # -- failure path
            self._emit(
                session,
                "RUNNER",
                "experiment_failed",
                f"Experiment failed (attempt {attempt}): {result.error}",
                status="error",
                meta={
                    "experiment_id": experiment.id,
                    "attempt": attempt,
                    "error": result.error,
                    "stderr_tail": result.stderr[-1200:],
                },
            )

            if attempt > MAX_REPAIR_ATTEMPTS:
                experiment.status = ExperimentStatus.FAILED.value
                session.commit()
                self._emit(
                    session,
                    "ENGINEER",
                    "repair_exhausted",
                    f"Repair budget exhausted after {MAX_REPAIR_ATTEMPTS} attempts; "
                    "marking experiment failed.",
                    status="error",
                    meta={"experiment_id": experiment.id},
                )
                return False

            self._emit(
                session,
                "ENGINEER",
                "repairing",
                f"Repairing experiment code (attempt {attempt} of {MAX_REPAIR_ATTEMPTS})…",
                status="warning",
                meta={"experiment_id": experiment.id, "error": result.error},
            )
            new_code, origin = self.engineer.repair(
                design, experiment.code, result.error or "", result.stderr, attempt
            )
            experiment.code = new_code
            experiment.repair_attempts = attempt
            session.commit()
            self._emit(
                session,
                "ENGINEER",
                "code_repaired",
                f"Regenerated experiment code ({origin}); retrying.",
                status="info",
                meta={"experiment_id": experiment.id, "origin": origin},
            )

        return False

    # -------------------------------------------------------------- analyse
    def _phase_analyse(
        self,
        session: Session,
        run: ResearchRun,
        experiment: Experiment,
        hypothesis: HypothesisOut,
        history: list[dict[str, Any]],
    ) -> None:
        self._set_state(session, run, RunState.ANALYZING)

        metrics = {m.name: m.value for m in experiment.metrics}
        baseline_metrics = history[0]["metrics"] if history else None
        design = ExperimentDesign.model_validate(experiment.design)
        elapsed = experiment.runs[-1].execution_time if experiment.runs else 0.0

        self._emit(
            session,
            "ANALYST",
            "analysing",
            f"Interpreting measured results for {experiment.name}…",
        )
        report = self.analyst.run(
            hypothesis, design, metrics, baseline_metrics, history, elapsed
        )

        experiment.analysis = report.model_dump()
        experiment.hypothesis_supported = report.hypothesis_supported
        session.commit()

        if experiment.hypothesis_id:
            hypothesis_row = session.get(Hypothesis, experiment.hypothesis_id)
            if hypothesis_row:
                hypothesis_row.status = (
                    HypothesisStatus.SUPPORTED.value
                    if report.hypothesis_supported
                    else HypothesisStatus.UNSUPPORTED.value
                )
                session.commit()

        # Track the best experiment by measured F1.
        # Rank on the metric this experiment actually measured, not an F1 it
        # may never have reported.
        best_score = float("-inf")
        if run.best_experiment_id:
            best = session.get(Experiment, run.best_experiment_id)
            if best:
                best_score = rank_key(
                    best.design, {m.name: m.value for m in best.metrics}
                )
        if rank_key(experiment.design, metrics) > best_score:
            run.best_experiment_id = experiment.id
            session.commit()

        # Link this experiment to the previous best.
        if history:
            self._edge(
                session,
                "experiment",
                history[-1]["id"],
                "experiment",
                experiment.id,
                "improved_from" if report.hypothesis_supported else "derived_from",
            )

        self._emit(
            session,
            "ANALYST",
            "analysis_complete",
            f"{'SUPPORTED' if report.hypothesis_supported else 'NOT SUPPORTED'} — "
            f"{primary_metric_of(experiment.design, metrics)[0]} = "
            f"{metrics.get(primary_metric_of(experiment.design, metrics)[0], 0):.4g}.",
            status="success" if report.hypothesis_supported else "warning",
            meta={
                "experiment_id": experiment.id,
                "supported": report.hypothesis_supported,
                "verdict": report.verdict,
                "key_findings": report.key_findings,
                "failure_modes": report.failure_modes,
                "recommendations": report.recommendations,
                "comparison": report.comparison,
                "metrics": metrics,
            },
        )

    def _phase_handle_failure(
        self, session: Session, run: ResearchRun, experiment: Experiment
    ) -> None:
        """The PI decides what to do with an experiment that would not run."""
        last_error = experiment.runs[-1].error if experiment.runs else "unknown error"
        if experiment.hypothesis_id:
            hypothesis_row = session.get(Hypothesis, experiment.hypothesis_id)
            if hypothesis_row:
                hypothesis_row.status = HypothesisStatus.INCONCLUSIVE.value
                session.commit()

        self._emit(
            session,
            "PI",
            "failure_reviewed",
            "Experiment abandoned after exhausting repairs; moving to the next "
            "hypothesis rather than spending more compute here.",
            status="warning",
            meta={"experiment_id": experiment.id, "error": last_error},
        )

    # -------------------------------------------------------------- conclude
    def _phase_conclude(self, session: Session, run: ResearchRun, question: str) -> None:
        history = self._history(session)
        best = None
        if history:
            best = max(history, key=lambda h: rank_key(h.get("design", {}), h["metrics"]))
            run.best_experiment_id = best["id"]

        self._emit(
            session,
            "PI",
            "summarising",
            f"Drawing conclusions from {len(history)} executed experiment(s)…",
        )
        summary = self.pi.summarize(question, history, best)

        baseline = history[0] if history else None
        improvement = 0.0
        fpr_change = 0.0
        if baseline and best and baseline["metrics"].get("f1", 0) > 0:
            improvement = (
                (best["metrics"].get("f1", 0) - baseline["metrics"].get("f1", 0))
                / baseline["metrics"]["f1"]
                * 100.0
            )
            base_fpr = baseline["metrics"].get("false_positive_rate", 0.0)
            if base_fpr > 0:
                fpr_change = (
                    (best["metrics"].get("false_positive_rate", 0.0) - base_fpr)
                    / base_fpr
                    * 100.0
                )

        run.final_summary = {
            **summary.model_dump(),
            "best_experiment_id": best["id"] if best else None,
            "best_experiment_name": best["name"] if best else None,
            "best_f1": best["metrics"].get("f1") if best else None,
            "best_fpr": best["metrics"].get("false_positive_rate") if best else None,
            "improvement_pct": round(improvement, 2),
            "fpr_change_pct": round(fpr_change, 2),
            "experiments_run": len(history),
            "papers_analysed": len(run.papers),
        }
        run.completed_at = utcnow()
        session.commit()

        self._set_state(session, run, RunState.COMPLETED)
        self._emit(
            session,
            "PI",
            "research_complete",
            summary.recommendation,
            status="success",
            meta=run.final_summary,
        )
        bus.publish(self.run_id, {"type": "complete", "summary": run.final_summary})

    # ------------------------------------------------------------- helpers
    def _store_hypothesis(
        self, session: Session, run: ResearchRun, out: HypothesisOut, index: int
    ) -> Hypothesis:
        # A candidate the PI passed over stays a live proposal, so the Scientist
        # will legitimately offer it again next round. Reuse the existing row
        # rather than inserting a duplicate, which would otherwise clutter the
        # research graph with repeated hypothesis nodes.
        existing = session.execute(
            select(Hypothesis).where(
                Hypothesis.run_id == self.run_id,
                Hypothesis.title == out.title,
                Hypothesis.status == HypothesisStatus.PROPOSED.value,
            )
        ).scalars().first()
        if existing is not None:
            return existing

        row = Hypothesis(
            run_id=self.run_id,
            index=index,
            title=out.title,
            description=out.description,
            rationale=out.rationale,
            expected_outcome=out.expected_outcome,
            assumptions=out.assumptions,
            approach=out.approach,
            difficulty=out.difficulty,
            expected_improvement=out.expected_improvement,
            confidence=out.confidence,
            status=HypothesisStatus.PROPOSED.value,
            origin="scientist",
        )
        # feature_set lives in the design, but the graph needs it for labelling.
        session.add(row)
        session.commit()
        self._edge(session, "question", run.research_question_id, "hypothesis", row.id, "generated_from")
        return row

    def _store_decision(
        self,
        session: Session,
        run: ResearchRun,
        index: int,
        decision: str,
        evidence: list[str],
        confidence: float,
        hypothesis_id: str | None,
        cost: str,
        expected_value: float,
    ) -> Decision:
        row = Decision(
            run_id=self.run_id,
            index=index,
            kind="next_experiment",
            decision=decision,
            evidence=evidence,
            confidence=confidence,
            selected_hypothesis_id=hypothesis_id,
            expected_value=expected_value,
            estimated_cost=cost,
        )
        session.add(row)
        session.commit()
        return row

    @staticmethod
    def _to_out(row: Hypothesis) -> HypothesisOut:
        return HypothesisOut(
            title=row.title,
            description=row.description,
            rationale=row.rationale,
            expected_outcome=row.expected_outcome,
            assumptions=row.assumptions or [],
            approach=row.approach,  # type: ignore[arg-type]
            feature_set="temporal" if "temporal" in (row.description or "").lower() else "base",
            difficulty=row.difficulty,  # type: ignore[arg-type]
            expected_improvement=row.expected_improvement,
            confidence=row.confidence,
        )
