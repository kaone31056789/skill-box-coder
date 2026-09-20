"""Dataset, code-generation, schema-validation and API tests."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments" / "anomaly_detection"))

import genesis_data  # noqa: E402

from genesis.agents.codegen import generate_experiment_code  # noqa: E402
from genesis.agents.schemas import (  # noqa: E402
    ExperimentDesign,
    GeneratedCode,
    HypothesisSet,
    PIDecision,
)
from genesis.agents import strategy  # noqa: E402

APPROACHES = [
    "isolation_forest",
    "one_class_svm",
    "random_forest",
    "gradient_boosting",
    "autoencoder",
    "ensemble_adaptive",
]


# ------------------------------------------------------------------ dataset
def test_dataset_is_deterministic() -> None:
    first = genesis_data.load_dataset(feature_set="temporal", seed=42)[0]
    second = genesis_data.load_dataset(feature_set="temporal", seed=42)[0]
    assert np.array_equal(first, second)


def test_temporal_feature_set_adds_columns() -> None:
    _, _, _, _, base_names = genesis_data.load_dataset(feature_set="base")
    _, _, _, _, temporal_names = genesis_data.load_dataset(feature_set="temporal")
    assert len(temporal_names) == len(base_names) + len(genesis_data.TEMPORAL_FEATURES)


def test_split_is_chronological_and_labels_are_binary() -> None:
    X_train, X_test, y_train, y_test, _ = genesis_data.load_dataset()
    assert len(X_train) > len(X_test)
    assert set(np.unique(y_train)) <= {0, 1}
    assert 0.0 < y_train.mean() < 0.3


def test_temporal_features_carry_real_signal() -> None:
    """The demo narrative rests on this: windowed features must genuinely
    separate port scans from benign monitoring, not merely appear to."""
    data = genesis_data.generate_flows(seed=42)
    kinds = data["attack_kind"]
    temporal = genesis_data._temporal_features(data)
    scan_ports = temporal["unique_dst_ports_60s"][kinds == "port_scan"]
    monitor_ports = temporal["unique_dst_ports_60s"][kinds == "benign_monitor"]
    assert scan_ports.mean() > monitor_ports.mean() * 2


# -------------------------------------------------------------- code generation
@pytest.mark.parametrize("approach", APPROACHES)
@pytest.mark.parametrize("feature_set", ["base", "temporal"])
def test_generated_code_compiles(approach: str, feature_set: str) -> None:
    design = ExperimentDesign(name="t", approach=approach, feature_set=feature_set)
    code = generate_experiment_code(design)
    compile(code, "experiment.py", "exec")
    assert "result.json" in code
    assert "load_dataset" in code


@pytest.mark.parametrize("threshold", ["default", "adaptive_percentile", "f1_optimized"])
def test_threshold_strategies_compile(threshold: str) -> None:
    design = ExperimentDesign(name="t", approach="random_forest", threshold_strategy=threshold)
    compile(generate_experiment_code(design), "experiment.py", "exec")


def test_hallucinated_parameters_are_filtered_out() -> None:
    """An invented kwarg must not reach the estimator constructor."""
    design = ExperimentDesign(
        name="t",
        approach="isolation_forest",
        parameters={"n_estimators": 50, "learning_rate": 0.5, "nonsense": "x"},
    )
    code = generate_experiment_code(design)
    assert "n_estimators=50" in code
    assert "learning_rate" not in code
    assert "nonsense" not in code


def test_f1_optimized_threshold_never_tunes_on_test() -> None:
    design = ExperimentDesign(name="t", approach="random_forest", threshold_strategy="f1_optimized")
    code = generate_experiment_code(design)
    tuning = code.split("threshold tuned on train")[0].split("# Tune the threshold")[1]
    assert "y_test" not in tuning
    assert "test_scores" not in tuning


# ------------------------------------------------------ agent output validation
def test_generated_code_schema_rejects_code_without_results() -> None:
    with pytest.raises(ValidationError):
        GeneratedCode(code="print('hello')" * 20)


def test_generated_code_schema_rejects_stub() -> None:
    with pytest.raises(ValidationError):
        GeneratedCode(code="result.json")


def test_hypothesis_set_requires_at_least_one() -> None:
    with pytest.raises(ValidationError):
        HypothesisSet(hypotheses=[])


def test_confidence_is_clamped() -> None:
    assert PIDecision(confidence=5.0).confidence == 1.0
    assert PIDecision(confidence=-2.0).confidence == 0.0


def test_unknown_approach_becomes_custom_rather_than_erroring() -> None:
    """Rejecting unknown approach names was expensive, not safe.

    A pathfinding question naturally proposes `a_star`; the strict enum
    rejected it, which triggered retries and walked the whole model chain --
    minutes per call. An approach the templates do not implement simply IS a
    custom, self-contained experiment.
    """
    assert ExperimentDesign(name="t", approach="quantum_neural_blockchain").approach == "custom"
    assert ExperimentDesign(name="t", approach="a_star").approach == "custom"
    # Known approaches still survive, including sloppy casing/separators.
    assert ExperimentDesign(name="t", approach="RANDOM-FOREST").approach == "random_forest"


@pytest.mark.parametrize(
    "raw,expected",
    [("a_star", "custom"), ("dijkstra", "custom"), ("", "custom"),
     ("isolation_forest", "isolation_forest"),
     # Graph-search strategies are first-class approaches, so they survive
     # normalisation instead of collapsing to "custom".
     ("Greedy Best-First", "greedy_best_first"), ("ASTAR-MANHATTAN", "astar_manhattan")],
)
def test_hypothesis_approach_is_normalised(raw: str, expected: str) -> None:
    hypothesis = HypothesisSet.model_validate(
        {"hypotheses": [{"title": "t", "approach": raw}]}
    ).hypotheses[0]
    assert hypothesis.approach == expected


def test_sloppy_enum_values_do_not_fail_validation() -> None:
    """Every rejected field costs a retry and a model-chain hop."""
    payload = {
        "hypotheses": [
            {"title": "t", "approach": "bfs", "feature_set": "windowed",
             "difficulty": "moderate"}
        ]
    }
    hypothesis = HypothesisSet.model_validate(payload).hypotheses[0]
    assert (hypothesis.approach, hypothesis.feature_set, hypothesis.difficulty) == (
        "custom", "base", "medium",
    )


# -------------------------------------------------------------------- strategy
def test_strategy_never_repeats_a_tried_configuration() -> None:
    tried = {strategy.signature(r.approach, r.feature_set, r.threshold_strategy) for r in strategy.LADDER[:3]}
    for rung in strategy.next_rungs(tried, limit=5):
        assert strategy.signature(rung.approach, rung.feature_set, rung.threshold_strategy) not in tried


def test_strategy_orders_by_expected_value() -> None:
    rungs = strategy.next_rungs(set(), limit=4)
    scores = [r.expected_improvement * r.confidence for r in rungs]
    assert scores == sorted(scores, reverse=True)


# ------------------------------------------------------------ domain routing
# Regression guard: a feature-scaling question once silently ran against the
# network-flow dataset because the LLM left `dataset_mode` at its default.
from genesis.agents.scientist import capabilities_for  # noqa: E402
from genesis.agents.schemas import HypothesisOut  # noqa: E402

ANOMALY_QUESTIONS = [
    "Can we improve network anomaly detection while reducing false positives?",
    "How do we reduce false positives in intrusion detection?",
    "Can we detect port scans earlier?",
    "Can we detect anomalies in network traffic faster?",
]
GENERAL_QUESTIONS = [
    "Does feature scaling matter more for distance-based models than tree-based models?",
    "Do ensembles beat single models under label noise?",
    "Does SMOTE outperform class weighting for imbalanced classification?",
    "Which clustering init strategy gives better cluster quality?",
]


@pytest.mark.parametrize("question", ANOMALY_QUESTIONS)
def test_anomaly_questions_route_to_builtin_dataset(question: str) -> None:
    assert strategy.is_builtin_anomaly_question(question) is True


@pytest.mark.parametrize("question", GENERAL_QUESTIONS)
def test_general_questions_route_to_self_contained(question: str) -> None:
    assert strategy.is_builtin_anomaly_question(question) is False


@pytest.mark.parametrize("question", GENERAL_QUESTIONS)
def test_routing_overrides_a_defaulted_dataset_mode(question: str) -> None:
    """The exact failure seen in production: model leaves the default in place."""
    hypothesis = HypothesisOut(title="t", approach="isolation_forest")
    assert hypothesis.dataset_mode == "builtin_anomaly"  # schema default
    routed = strategy.route_hypothesis(hypothesis, question)
    assert routed.dataset_mode == "self_contained"
    assert routed.approach == "custom"


@pytest.mark.parametrize("question", ANOMALY_QUESTIONS)
def test_routing_keeps_anomaly_questions_on_builtin(question: str) -> None:
    hypothesis = HypothesisOut(title="t", approach="custom")
    routed = strategy.route_hypothesis(hypothesis, question)
    assert routed.dataset_mode == "builtin_anomaly"
    assert routed.approach != "custom"


def test_general_prompt_never_mentions_the_network_dataset() -> None:
    """Describing an irrelevant dataset biased the model into reframing the
    question as anomaly detection."""
    envelope = capabilities_for(GENERAL_QUESTIONS[0])
    for term in ("network flows", "port scans", "DDoS", "tcp_flags", "feature_set"):
        assert term not in envelope
    assert "self_contained" in envelope


def test_anomaly_prompt_describes_the_builtin_dataset() -> None:
    envelope = capabilities_for(ANOMALY_QUESTIONS[0])
    assert "network flows" in envelope
    assert "temporal" in envelope


# --------------------------------------------------- prompt string safety
# Regression guard: an LLM-written hypothesis title containing "%" (e.g.
# "cuts false positives by 50%") crashed a whole run with
# "not enough arguments for format string", because a %-formatted literal was
# implicitly concatenated with f-strings carrying that title.
PERCENT_HYPOTHESIS = HypothesisOut(
    title="Temporal features cut false positives by 50% at equal recall",
    description="Uses 100% of the windowed feature set",
    rationale="Benign look-alikes account for ~80% of remaining errors",
)


def test_experimentalist_prompt_survives_percent_signs(monkeypatch) -> None:
    """Building the design prompt must not treat '%' as a format spec."""
    from genesis.agents import experimentalist as module

    captured: dict[str, str] = {}

    class StubLLM:
        enabled = True

        def complete_json(self, system, user, model_cls, **kwargs):
            captured["user"] = user
            raise module.LLMError("stub: no provider")

    monkeypatch.setattr(module, "get_llm", lambda: StubLLM())

    design = module.ExperimentalistAgent().run(
        PERCENT_HYPOTHESIS, 1, "baseline", [], is_baseline=False
    )
    # The prompt was built (so no formatting crash) and we fell back cleanly.
    assert "50%" in captured["user"]
    assert "Design experiment #001" in captured["user"]
    assert design.name


def test_agent_modules_do_not_percent_format_prompts() -> None:
    """%-formatting next to f-strings is how the crash happened; ban it."""
    from pathlib import Path as _Path

    agents_dir = _Path(__file__).resolve().parents[1] / "genesis" / "agents"
    for module_path in agents_dir.glob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        assert "\n                    % " not in source, (
            f"{module_path.name} uses %-formatting in a prompt; use an f-string"
        )


# ------------------------------------------------------------- demo mode
def test_demo_mode_disables_the_llm_for_that_thread_only() -> None:
    """A demo run must not depend on a model provider; a live run in another
    thread must be unaffected."""
    import threading

    from genesis.agents.llm import get_llm, set_llm_enabled

    set_llm_enabled(False)
    assert get_llm().enabled is False

    other: dict[str, object] = {}

    def _live_run() -> None:
        other["provider"] = get_llm().provider

    thread = threading.Thread(target=_live_run)
    thread.start()
    thread.join()

    # The other thread never opted out, so it resolved normally.
    assert other["provider"] != "deterministic"
    set_llm_enabled(True)


# ------------------------------------------------------------ analyst verdicts
# Regression guards. The Analyst crashed on `design` being undefined, then --
# once running -- called a 31% speedup "not supported" because the significance
# floor was absolute and tuned for F1.
from genesis.agents.analyst import AnalystAgent  # noqa: E402


def _verdict(primary: str, direction: str, new: float, base: float) -> bool:
    design = ExperimentDesign(
        name="e", approach="custom", primary_metric=primary, metric_direction=direction
    )
    report = AnalystAgent()._deterministic(
        HypothesisOut(title="t"), design, {primary: new}, {primary: base}, []
    )
    return report.hypothesis_supported


@pytest.mark.parametrize(
    "primary,direction,new,base,expected",
    [
        # Lower-is-better metrics on arbitrary scales.
        ("avg_runtime_s", "minimize", 0.0083, 0.0121, True),    # 31% faster
        ("avg_runtime_s", "minimize", 0.0120, 0.0121, False),   # 0.8%, noise
        ("avg_runtime_s", "minimize", 0.0121, 0.0083, False),   # slower
        ("avg_path_length", "minimize", 41.2, 57.8, True),      # shorter path
        ("avg_path_length", "minimize", 57.8, 41.2, False),     # longer path
        ("nodes_expanded", "minimize", 300.0, 470.0, True),
        # Bounded scores still clear an absolute floor.
        ("f1", "maximize", 0.984, 0.848, True),
        ("f1", "maximize", 0.852, 0.848, False),                # within noise
    ],
)
def test_significance_respects_scale_and_direction(
    primary: str, direction: str, new: float, base: float, expected: bool
) -> None:
    assert _verdict(primary, direction, new, base) is expected


def test_analyst_deterministic_path_runs_without_an_llm() -> None:
    """This path raised NameError: 'design' is not defined, killing whole runs."""
    report = AnalystAgent().run(
        HypothesisOut(title="Baseline: Isolation Forest on base features"),
        ExperimentDesign(name="baseline", approach="isolation_forest"),
        {"f1": 0.1394, "precision": 0.303, "recall": 0.0905,
         "false_positive_rate": 0.0276, "n_test": 1885},
        None,
        [],
        2.4,
    )
    assert report.verdict
    assert report.hypothesis_supported is True  # first run defines the reference


def test_design_carries_the_declared_primary_metric() -> None:
    """extra='ignore' silently dropped these, so the heuristic guessed instead."""
    design = ExperimentDesign(
        name="e", approach="custom", primary_metric="avg_path_length",
        metric_direction="minimize",
    )
    assert design.primary_metric == "avg_path_length"
    assert design.metric_direction == "minimize"
    assert ExperimentDesign(name="e", metric_direction="nonsense").metric_direction == "maximize"


# --------------------------------------------------- domain leakage guards
# A pathfinding run produced random-forest and gradient-boosting experiments on
# the network dataset, and the PI then compared them against the A* baseline.
# Every path that can produce a hypothesis must respect the question's domain.
from genesis.agents.llm import set_llm_enabled  # noqa: E402
from genesis.agents.scientist import ScientistAgent  # noqa: E402


@pytest.fixture
def offline_agents():
    set_llm_enabled(False)
    yield
    set_llm_enabled(True)


def test_ladder_never_answers_a_question_it_does_not_cover(offline_agents) -> None:
    """The anomaly ladder must not leak into a question it does not cover.

    This used to assert that nothing at all was proposed. Emptiness was a proxy
    for the real hazard -- random-forest-on-network-traffic experiments offered
    up for an unrelated question -- and it cost every self-contained run the
    rest of its budget. The hazard itself is what is asserted now: the
    fallback may propose methodological variations, but never a built-in
    estimator and never the network dataset.
    """
    proposed = ScientistAgent().run(
        "Does feature scaling matter more for distance-based models?",
        None, [], set(), count=3,
    )
    assert proposed, "a self-contained question must still get candidates"
    assert all(h.dataset_mode == "self_contained" for h in proposed)
    assert all(h.approach == "custom" for h in proposed)
    # Distinct enough to be separate experiments rather than one repeated.
    assert len({h.variant for h in proposed}) == len(proposed)
    blob = " ".join(f"{h.title} {h.description}" for h in proposed).lower()
    for leaked in ("isolation forest", "random forest", "network traffic", "per-flow"):
        assert leaked not in blob, f"anomaly-domain language leaked: {leaked!r}"


def test_graph_search_keeps_proposing_after_the_baseline(offline_agents) -> None:
    """A pathfinding run reported 'no untested hypotheses remain' right after
    its baseline, ending the research at one experiment."""
    question = "Can we find a graph-search strategy that reduces pathfinding time?"
    proposed = ScientistAgent().run(question, None, [], {"ucs|base|default"}, count=3)
    assert proposed, "graph-search questions must have candidates after the baseline"
    assert all(h.dataset_mode == "builtin_graph_search" for h in proposed)
    assert "ucs" not in {h.approach for h in proposed}
    assert {h.approach for h in proposed} <= {
        "astar_manhattan", "astar_euclidean", "weighted_astar",
        "greedy_best_first", "bidirectional_ucs",
    }


def test_ladder_still_serves_its_own_domain(offline_agents) -> None:
    proposed = ScientistAgent().run(
        "Can we improve network anomaly detection while reducing false positives?",
        None, [], set(), count=3,
    )
    assert proposed
    assert all(h.dataset_mode == "builtin_anomaly" for h in proposed)


def test_offline_baseline_matches_the_question_domain(offline_agents) -> None:
    anomaly = ScientistAgent().baseline(
        "Can we improve network anomaly detection while reducing false positives?"
    )
    other = ScientistAgent().baseline(
        "Does feature scaling matter more for distance-based models?"
    )
    assert anomaly.dataset_mode == "builtin_anomaly"
    assert other.dataset_mode == "self_contained"
    assert other.approach == "custom"


@pytest.mark.parametrize(
    "question,expected_mode",
    [
        ("Can we find a graph-search strategy that reduces pathfinding time?", "builtin_graph_search"),
        ("Does feature scaling matter for linear models?", "self_contained"),
        ("Can we improve network anomaly detection?", "builtin_anomaly"),
    ],
)
def test_routing_corrects_a_mismatched_hypothesis(question: str, expected_mode: str) -> None:
    """The orchestrator re-routes before designing, so a hypothesis from any
    source lands in the right domain."""
    stray = HypothesisOut(title="t", approach="random_forest", dataset_mode="builtin_anomaly")
    routed = strategy.route_hypothesis(stray, question)
    assert routed.dataset_mode == expected_mode


def test_pi_spends_the_budget_the_operator_asked_for(monkeypatch) -> None:
    """A good baseline is not grounds for delivering fewer experiments.

    How many experiments to run is the operator's choice, so a PI that wants
    to conclude while the budget still has room is overridden into running the
    best remaining candidate.
    """
    from genesis.agents import pi as module
    from genesis.agents.schemas import PIDecision

    class ConcludingLLM:
        enabled = True

        def complete_json(self, system, user, model_cls, **kwargs):
            return PIDecision(
                action="conclude",
                selected_hypothesis_index=0,
                decision="Baseline already performs well; stopping here.",
                evidence=["f1=0.98 on the baseline."],
                confidence=0.9,
            )

    monkeypatch.setattr(module, "get_llm", lambda: ConcludingLLM())

    candidates = [
        HypothesisOut(
            title="Temporal features on random forest",
            description="Windowed features",
            rationale="Bursts are only visible over time",
            expected_improvement=0.3,
            confidence=0.7,
        ),
    ]
    history = [
        {
            "name": "EXP-001 baseline",
            "approach": "isolation_forest",
            "design": {},
            "metrics": {"f1": 0.98},
            "supported": True,
        }
    ]

    decision = module.PIAgent().decide("q", candidates, history, experiments_remaining=2)

    assert decision.action == "run_experiment"
    assert 0 <= decision.selected_hypothesis_index < len(candidates)
    assert any("budget" in bullet.lower() for bullet in decision.evidence)
    # The stale "stopping here" wording must not survive the override.
    assert "stopping here" not in decision.decision.lower()


def test_pi_concludes_when_nothing_is_left_to_test() -> None:
    """Budget alone is not a reason to run: an empty search space still ends."""
    from genesis.agents import pi as module

    decision = module.PIAgent().decide("q", [], [], experiments_remaining=3)
    assert decision.action == "conclude"


# ---------------------------------------------------------------- metric names
def test_metric_aliases_are_canonicalised() -> None:
    """LLM-written code names metrics its own way; the lab still ranks them.

    An experiment reporting `auc_roc` measured exactly what the deterministic
    template calls `roc_auc`. Without canonicalisation the UI renders a
    populated metric as an empty cell.
    """
    from genesis.sandbox.base import parse_result_payload

    metrics, _, primary, error = parse_result_payload(
        '{"metrics": {"auc_roc": 0.774, "f1_score": 0.0, "fpr": 0.01, "tp": 0},'
        ' "primary_metric": "auc_roc"}'
    )
    assert error is None
    assert metrics["roc_auc"] == 0.774
    assert metrics["f1"] == 0.0
    assert metrics["false_positive_rate"] == 0.01
    assert metrics["true_positives"] == 0.0
    assert primary == {"name": "roc_auc", "direction": "maximize"}


def test_canonical_name_never_shadows_a_real_metric() -> None:
    """A payload carrying both spellings keeps the canonical measurement."""
    from genesis.sandbox.base import parse_result_payload

    metrics, _, _, _ = parse_result_payload(
        '{"metrics": {"auc": 0.5, "roc_auc": 0.91}}'
    )
    assert metrics["roc_auc"] == 0.91


# ------------------------------------------------------------ zero detections
def _no_detection_history(threshold: str = "default") -> list[dict]:
    return [
        {
            "id": "e1",
            "name": "EXP-001 isolation_forest",
            "index": 1,
            "approach": "isolation_forest",
            "feature_set": "base",
            "threshold_strategy": threshold,
            "design": {"dataset_mode": "builtin_anomaly", "feature_set": "base"},
            "metrics": {
                "f1": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "roc_auc": 0.774,
                "true_positives": 0.0,
                "false_positives": 0.0,
            },
            "supported": True,
        }
    ]


def _loop():
    from genesis.orchestrator.loop import ResearchOrchestrator

    return ResearchOrchestrator.__new__(ResearchOrchestrator)


def test_zero_detection_result_triggers_threshold_recovery() -> None:
    """A detector that never fires is repaired, not reasoned from."""
    recovery = _loop()._recovery_hypothesis(_no_detection_history(), set())

    assert recovery is not None
    assert recovery.threshold_strategy == "f1_optimized"
    # The model and features are held constant so the threshold is the only
    # variable that moved.
    assert recovery.approach == "isolation_forest"
    assert recovery.feature_set == "base"
    assert "0.774" in recovery.rationale


def test_recovery_is_attempted_only_once() -> None:
    """A genuinely unlearnable setup must not loop on the same calibration."""
    from genesis.agents import strategy

    tried = {strategy.signature("isolation_forest", "base", "f1_optimized")}
    assert _loop()._recovery_hypothesis(_no_detection_history(), tried) is None


def test_a_working_detector_is_left_alone() -> None:
    history = _no_detection_history()
    history[0]["metrics"] = {"f1": 0.84, "recall": 0.81, "true_positives": 120.0,
                             "false_positives": 9.0}
    assert _loop()._recovery_hypothesis(history, set()) is None


def test_domains_without_detection_metrics_are_left_alone() -> None:
    """A graph-search run reports no f1/recall and must not look degenerate."""
    history = _no_detection_history()
    history[0]["metrics"] = {"path_cost": 42.0, "expanded_nodes": 1200.0}
    assert _loop()._recovery_hypothesis(history, set()) is None


def test_pinned_threshold_survives_experiment_design(monkeypatch) -> None:
    """The experimentalist may not quietly design a different threshold."""
    from genesis.agents import experimentalist as module
    from genesis.agents.schemas import ExperimentDesign, HypothesisOut

    class DriftingLLM:
        enabled = True

        def complete_json(self, system, user, model_cls, **kwargs):
            return ExperimentDesign(
                name="EXP-002 recalibrated",
                approach="isolation_forest",
                feature_set="base",
                threshold_strategy="default",  # ignores the pin
            )

    monkeypatch.setattr(module, "get_llm", lambda: DriftingLLM())

    hypothesis = HypothesisOut(
        title="Calibrate the threshold",
        approach="isolation_forest",
        feature_set="base",
        threshold_strategy="f1_optimized",
    )
    design = module.ExperimentalistAgent().run(hypothesis, 2, "baseline", [])
    assert design.threshold_strategy == "f1_optimized"


def test_baseline_rationale_is_not_hardcoded_to_anomaly_detection() -> None:
    """The PI must explain the baseline it actually chose.

    A feature-selection run reported "Establish an unsupervised baseline" and
    cited "Isolation Forest on per-flow features" for a supervised logistic
    regression on a dataset it never touched. The copy is derived from the
    chosen hypothesis now; this guards the regression.
    """
    from pathlib import Path as _Path

    source = (
        _Path(__file__).resolve().parents[1] / "genesis" / "orchestrator" / "loop.py"
    ).read_text(encoding="utf-8")

    for phrase in (
        "Establish an unsupervised baseline",
        "Isolation Forest on per-flow features is the standard",
    ):
        assert phrase not in source, (
            f"loop.py hardcodes domain-specific baseline copy: {phrase!r}"
        )


# ------------------------------------------------------------- literature
def test_search_terms_drop_interrogatives_and_filler() -> None:
    """A question must be searched for its subject, not its grammar.

    "Which ... remain most reliable ..." built the arXiv query
    all:"which" AND all:"machine-learning" AND all:"models" AND all:"remain",
    which retrieved papers on model interpretability.
    """
    from genesis.literature.arxiv import build_query, keywords_for

    question = (
        "Which machine-learning models remain most reliable when the statistical "
        "distribution of incoming data changes over time?"
    )
    keywords = keywords_for(question)
    for junk in ("which", "remain", "most", "over"):
        assert junk not in keywords, f"{junk!r} is not a search term"
    assert "machine-learning" in keywords
    assert "distribution" in keywords

    # Noun phrases survive in order, so this stays a search about the subject.
    assert build_query(
        "Can we improve network anomaly detection while reducing false positives?"
    ) == 'all:"network" AND all:"anomaly" AND all:"detection"'


def test_curated_fallback_says_why(monkeypatch) -> None:
    """Falling back to the offline corpus is reported, not silently chosen."""
    from genesis.literature import arxiv as module

    class Settings:
        enable_arxiv = False
        arxiv_timeout_seconds = 5.0
        max_papers = 12

    monkeypatch.setattr(module, "get_settings", lambda: Settings())

    papers, source, reason = module.discover("network anomaly detection")
    assert source == "curated"
    assert papers, "the curated corpus should still carry the run"
    assert reason is not None and "disabled" in reason


def test_live_results_report_no_fallback_reason(monkeypatch) -> None:
    """A run carried by arXiv must not imply something went wrong."""
    from genesis.literature import arxiv as module

    sample = [
        module.PaperRecord(title=f"Paper {i}", abstract="drift", source="arxiv")
        for i in range(6)
    ]
    monkeypatch.setattr(module, "search_arxiv", lambda *a, **k: sample)

    papers, source, reason = module.discover("concept drift detection")
    assert source == "arxiv"
    assert reason is None
    assert len(papers) == 6


# -------------------------------------------------- self-contained variants
def test_self_contained_hypotheses_stay_distinct() -> None:
    """Different methods must not collapse into one experiment signature.

    Every non-anomaly, non-graph question routes to approach="custom", so
    without a variant slug three genuinely different proposals shared the
    signature custom|base|default. That matched the baseline, every candidate
    was dropped as already-tested, and the run reported an exhausted search
    space after a single experiment.
    """
    from genesis.agents import strategy
    from genesis.agents.schemas import HypothesisOut
    from genesis.agents.scientist import ScientistAgent

    question = (
        "Which machine-learning models remain most reliable when the statistical "
        "distribution of incoming data changes over time?"
    )
    baseline = strategy.route_hypothesis(
        HypothesisOut(title="Static Logistic Regression Baseline"), question
    )
    proposals = [
        strategy.route_hypothesis(HypothesisOut(title=title), question)
        for title in (
            "Online gradient descent adapts to drift",
            "Ensemble with sliding window retraining",
            "Drift-triggered model reselection",
        )
    ]

    signatures = {
        strategy.signature(
            h.approach,
            h.feature_set,
            strategy.threshold_for(h.approach, h.feature_set),
            h.variant,
        )
        for h in [baseline, *proposals]
    }
    assert len(signatures) == 4, "each distinct method needs its own signature"

    tried = {
        strategy.signature(
            baseline.approach, baseline.feature_set, "default", baseline.variant
        )
    }
    fresh = ScientistAgent()._drop_duplicates(proposals, tried)
    assert len(fresh) == 3, "the baseline must not mask unrelated hypotheses"


def test_repeating_the_same_method_is_still_rejected() -> None:
    """The variant must not defeat duplicate detection it was added beside."""
    from genesis.agents import strategy
    from genesis.agents.schemas import HypothesisOut
    from genesis.agents.scientist import ScientistAgent

    question = "How should a queue be scheduled under bursty arrivals?"
    again = strategy.route_hypothesis(
        HypothesisOut(title="Shortest job first scheduling"), question
    )
    tried = {
        strategy.signature(again.approach, again.feature_set, "default", again.variant)
    }
    assert ScientistAgent()._drop_duplicates([again], tried) == []


def test_variant_reaches_the_executed_design() -> None:
    """_tried reads the design, so an unrecorded variant would lose the fix."""
    from genesis.agents import strategy
    from genesis.agents.experimentalist import ExperimentalistAgent
    from genesis.agents.schemas import HypothesisOut

    hypothesis = strategy.route_hypothesis(
        HypothesisOut(title="Sliding window retraining"),
        "Which scheduler copes best with bursty arrivals?",
    )
    design = ExperimentalistAgent()._deterministic(
        hypothesis, 2, "baseline", "default", is_baseline=False
    )
    assert design.variant == hypothesis.variant != ""


def test_a_self_contained_run_keeps_going_after_its_baseline(offline_agents) -> None:
    """The budget the operator asked for must actually be spent.

    A good baseline is not a reason to stop: the point of the run is the
    comparison. This is the end-to-end shape of the bug where every
    self-contained question finished after exactly one experiment.
    """
    from genesis.agents import strategy
    from genesis.agents.schemas import HypothesisOut

    question = (
        "Which machine-learning models remain most reliable when the statistical "
        "distribution of incoming data changes over time?"
    )
    baseline = strategy.route_hypothesis(
        HypothesisOut(title="Static Logistic Regression Baseline"), question
    )
    tried = {
        strategy.signature(
            baseline.approach, baseline.feature_set, "default", baseline.variant
        )
    }

    # Round two: candidates must exist even with no LLM to invent them.
    second = ScientistAgent().run(question, None, [], tried, count=3)
    assert second, "the run must not end after its baseline"

    # Round three: and again, once round two has been recorded as tried.
    for hypothesis in second[:1]:
        tried.add(
            strategy.signature(
                hypothesis.approach, hypothesis.feature_set, "default", hypothesis.variant
            )
        )
    third = ScientistAgent().run(question, None, [], tried, count=3)
    assert third, "the run must keep proposing until the budget is spent"
    assert not ({h.variant for h in third} & {h.variant for h in second[:1]})
