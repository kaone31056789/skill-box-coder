"""Deterministic research strategy.

Used when no LLM is configured, and as the guardrail that stops the LLM path
from proposing an experiment that has already been run. The ladder encodes
ordinary methodology for this domain -- start with a cheap unsupervised
baseline, add temporal context, move to supervised models, then tune the
decision threshold -- but which rung actually wins is decided by executed
metrics, never asserted here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import HypothesisOut


@dataclass(frozen=True)
class Rung:
    approach: str
    feature_set: str
    threshold_strategy: str
    title: str
    description: str
    rationale: str
    expected_outcome: str
    assumptions: tuple[str, ...]
    difficulty: str
    expected_improvement: float
    confidence: float


BASELINE = Rung(
    approach="isolation_forest",
    feature_set="base",
    threshold_strategy="default",
    title="Isolation Forest on per-flow features establishes the baseline",
    description=(
        "Fit an unsupervised Isolation Forest on per-flow features only "
        "(duration, byte counts, packets, port, protocol, TCP flags) and flag the "
        "top-scoring fraction matching the training anomaly prior."
    ),
    rationale=(
        "Isolation Forest is the standard cheap unsupervised baseline for this "
        "problem. Every later claim needs a reference point measured under the "
        "same split and metrics."
    ),
    expected_outcome=(
        "Moderate recall driven by high-volume transfers, with a false-positive "
        "rate inflated by benign traffic that resembles attacks."
    ),
    assumptions=(
        "Anomalies are rare relative to normal traffic",
        "Per-flow features alone carry enough signal for a usable baseline",
    ),
    difficulty="low",
    expected_improvement=0.0,
    confidence=0.9,
)

LADDER: tuple[Rung, ...] = (
    Rung(
        approach="isolation_forest",
        feature_set="temporal",
        threshold_strategy="default",
        title="Windowed temporal features expose burst-shaped attacks",
        description=(
            "Extend the feature vector with 60-second windowed statistics: distinct "
            "destination ports per source, flows per source, packet rate, byte ratio, "
            "mean inter-arrival time, and source entropy."
        ),
        rationale=(
            "Port scans and DDoS bursts are defined by behaviour across many flows, not "
            "by any single flow. A per-flow model is structurally blind to them, so "
            "adding window aggregates should raise recall without changing the model."
        ),
        expected_outcome="Higher recall on scan and burst traffic; F1 improves over baseline.",
        assumptions=(
            "Flow timestamps are reliable enough to window over",
            "A 60-second window captures the relevant attack behaviour",
        ),
        difficulty="low",
        expected_improvement=0.22,
        confidence=0.82,
    ),
    Rung(
        approach="random_forest",
        feature_set="base",
        threshold_strategy="default",
        title="Supervised classification exploits available attack labels",
        description=(
            "Train a class-balanced Random Forest on the same per-flow features, using "
            "the labelled training split."
        ),
        rationale=(
            "The unsupervised baseline discards the labels entirely. Isolating the effect "
            "of supervision -- holding features constant -- separates 'we needed labels' "
            "from 'we needed better features'."
        ),
        expected_outcome="Large precision gain over the unsupervised baseline.",
        assumptions=(
            "Training labels are accurate",
            "Attack types in the test split also appear in training",
        ),
        difficulty="low",
        expected_improvement=0.3,
        confidence=0.85,
    ),
    Rung(
        approach="random_forest",
        feature_set="temporal",
        threshold_strategy="adaptive_percentile",
        title="Temporal features plus adaptive thresholding cut false positives",
        description=(
            "Combine the windowed temporal features with a supervised Random Forest, and "
            "place the decision threshold at a local density minimum of the training score "
            "distribution instead of a fixed cut."
        ),
        rationale=(
            "Benign monitoring sweeps, scheduled backups and flash crowds mimic attacks "
            "per-flow; window statistics are what separate them. An adaptive threshold "
            "puts the boundary in a sparse region of the score distribution rather than "
            "through the middle of a cluster."
        ),
        expected_outcome="Best expected F1 with a substantially lower false-positive rate.",
        assumptions=(
            "The score distribution is genuinely bimodal near the boundary",
            "Window statistics separate benign look-alikes from real attacks",
        ),
        difficulty="medium",
        expected_improvement=0.35,
        confidence=0.8,
    ),
    Rung(
        approach="gradient_boosting",
        feature_set="temporal",
        threshold_strategy="f1_optimized",
        title="Gradient boosting with an F1-tuned threshold",
        description=(
            "Train histogram gradient boosting on the temporal feature set and select the "
            "decision threshold by sweeping F1 on the training split only."
        ),
        rationale=(
            "Boosting models residual errors sequentially and often edges out bagging on "
            "tabular data. Tuning the threshold on train (never on test) converts better "
            "ranking into a better operating point."
        ),
        expected_outcome="Comparable or slightly better F1 than the tuned Random Forest.",
        assumptions=(
            "The train and test score distributions are similar enough to transfer",
            "Threshold tuning on train does not overfit the operating point",
        ),
        difficulty="medium",
        expected_improvement=0.36,
        confidence=0.72,
    ),
    Rung(
        approach="ensemble_adaptive",
        feature_set="temporal",
        threshold_strategy="adaptive_percentile",
        title="Hybrid ensemble retains novelty detection under supervision",
        description=(
            "Blend the Isolation Forest novelty score with the supervised classifier "
            "probability, mapping both through the training distribution, then threshold "
            "adaptively."
        ),
        rationale=(
            "A purely supervised model can only recognise attack shapes it was trained on. "
            "Retaining an unsupervised term preserves some sensitivity to novel behaviour "
            "at a small cost in precision."
        ),
        expected_outcome="Slightly below the best supervised F1, but more robust to novel attacks.",
        assumptions=(
            "Novel attacks resemble low-density regions of normal traffic",
            "A fixed blend weight suits both signal sources",
        ),
        difficulty="medium",
        expected_improvement=0.3,
        confidence=0.65,
    ),
    Rung(
        approach="autoencoder",
        feature_set="temporal",
        threshold_strategy="adaptive_percentile",
        title="Reconstruction error as a label-free anomaly score",
        description=(
            "Train a bottleneck autoencoder on normal traffic only and score anomalies by "
            "reconstruction error over the temporal feature set."
        ),
        rationale=(
            "Where labels are unavailable or stale, a normality model is the practical "
            "option. Worth measuring how much performance supervision is actually buying."
        ),
        expected_outcome="Below supervised methods, but competitive with the unsupervised baseline.",
        assumptions=(
            "The training split is clean enough to represent normal behaviour",
            "A low-dimensional bottleneck captures normal traffic structure",
        ),
        difficulty="medium",
        expected_improvement=0.18,
        confidence=0.6,
    ),
    Rung(
        approach="one_class_svm",
        feature_set="temporal",
        threshold_strategy="default",
        title="Kernel one-class boundary over temporal features",
        description=(
            "Fit an approximate one-class SVM (Nystroem feature map plus SGD) around the "
            "normal region of the temporal feature space."
        ),
        rationale=(
            "A different inductive bias to tree ensembles. Cheap to test, and disagreement "
            "with the forest would itself be informative about the decision boundary."
        ),
        expected_outcome="Likely weaker than tree ensembles on this feature geometry.",
        assumptions=(
            "The normal class is reasonably compact after scaling",
            "The kernel approximation preserves the boundary",
        ),
        difficulty="low",
        expected_improvement=0.1,
        confidence=0.5,
    ),
)


def variant_slug(text: str) -> str:
    """A short, stable identifier for a method that has no built-in name."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return "_".join(words[:5])[:56]


def signature(
    approach: str, feature_set: str, threshold_strategy: str, variant: str = ""
) -> str:
    """Identity of an experimental configuration, for "has this been run?".

    ``variant`` matters for self-contained questions: there the approach is
    always "custom", so without it three genuinely different methods share one
    signature, every proposal after the baseline looks already-tested, and the
    run reports an exhausted search space after a single experiment.
    """
    return f"{approach}|{feature_set}|{threshold_strategy}|{variant}"


def rung_to_hypothesis(rung: Rung) -> HypothesisOut:
    return HypothesisOut(
        title=rung.title,
        description=rung.description,
        rationale=rung.rationale,
        expected_outcome=rung.expected_outcome,
        assumptions=list(rung.assumptions),
        approach=rung.approach,  # type: ignore[arg-type]
        feature_set=rung.feature_set,  # type: ignore[arg-type]
        difficulty=rung.difficulty,  # type: ignore[arg-type]
        expected_improvement=rung.expected_improvement,
        confidence=rung.confidence,
    )


def next_rungs(tried: set[str], limit: int = 3) -> list[Rung]:
    """Highest-value untried rungs, best expected value first."""
    remaining = [
        r
        for r in LADDER
        if signature(r.approach, r.feature_set, r.threshold_strategy) not in tried
    ]
    remaining.sort(key=lambda r: -(r.expected_improvement * r.confidence))
    return remaining[:limit]


# --------------------------------------------------------------------------
# Self-contained fallback ladder
# --------------------------------------------------------------------------
# The anomaly ladder names concrete estimators, which is why it may only be
# used for anomaly questions. Everything else routes to a self-contained
# experiment where the Engineer writes the code, so the fallback here proposes
# *methodological* variations instead: they are meaningful for any predictive
# or algorithmic question, and none of them asserts a domain the question did
# not ask about.
#
# Without this a self-contained run had no fallback at all. If the scientist
# proposed nothing usable, the run stopped after its baseline with the budget
# unspent, which is the opposite of comparing alternatives.
_GENERIC_VARIATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "alternative_model_family",
        "A different model family outperforms the baseline approach",
        "Solve the same task with a materially different family than the "
        "baseline used -- if the baseline is linear or rule-based, use a "
        "non-linear ensemble, and otherwise the reverse.",
        "The baseline was chosen to be simple, not best. Whether its bias is "
        "actually costing accuracy on this task is a measurable question, and "
        "the cheapest way to answer it is to measure a different family under "
        "the identical split and metrics.",
    ),
    (
        "tuned_hyperparameters",
        "Tuning the baseline's parameters closes most of the gap",
        "Keep the baseline approach and search its main hyperparameters on the "
        "training split only, reporting the same metrics on the untouched test "
        "split.",
        "An untuned baseline understates what the simple approach can do. If "
        "tuning alone matches a more complex family, the complexity is not "
        "earning its cost and the simple model should be kept.",
    ),
    (
        "adaptive_online_variant",
        "An adaptive variant that updates as data arrives beats a static fit",
        "Refit or update the model incrementally across the evaluation stream "
        "rather than fitting once on the training split.",
        "A model fitted once assumes the data it sees later resembles the data "
        "it was trained on. Where that assumption breaks, an adaptive variant "
        "should separate from the static one, and where it holds the two "
        "should agree -- either result is informative.",
    ),
    (
        "richer_input_representation",
        "A richer input representation carries signal the baseline discards",
        "Derive additional inputs from the existing data -- interactions, "
        "aggregates, or history -- and fit the baseline approach on them.",
        "Representation and model family are separate variables. Changing this "
        "one alone shows whether the limit is what the model can express or "
        "what it is being shown.",
    ),
    (
        "ensemble_of_candidates",
        "Combining the candidates beats any single one",
        "Combine the approaches already measured in this run and report the "
        "combination under the same split and metrics.",
        "Ensembling is the standard check on whether the candidates are making "
        "different mistakes. If the combination does not beat the best single "
        "model, their errors are correlated and the extra cost buys nothing.",
    ),
)


def generic_variations(tried: set[str], limit: int = 3) -> list[HypothesisOut]:
    """Domain-neutral next experiments for a self-contained question."""
    fresh: list[HypothesisOut] = []
    for variant, title, description, rationale in _GENERIC_VARIATIONS:
        if signature("custom", "base", "default", variant) in tried:
            continue
        fresh.append(
            HypothesisOut(
                title=title,
                description=description,
                rationale=rationale,
                expected_outcome=(
                    "A measured result under the same split and metrics as the "
                    "baseline, so the comparison is like-for-like."
                ),
                assumptions=[
                    "The baseline result is a valid reference point.",
                    "Only this variable changed relative to the baseline.",
                ],
                approach="custom",
                feature_set="base",
                dataset_mode="self_contained",
                difficulty="medium",
                variant=variant,
            )
        )
        if len(fresh) >= limit:
            break
    return fresh


def threshold_for(rung_approach: str, feature_set: str) -> str:
    """Default threshold strategy when a hypothesis does not specify one."""
    if feature_set == "temporal":
        return "adaptive_percentile"
    return "default"


# --------------------------------------------------------------------------
# Domain routing
# --------------------------------------------------------------------------
# The built-in dataset is network traffic. A question is only routed to it when
# it is actually about that; everything else gets a self-contained experiment
# that generates its own data. This is deliberately a keyword rule rather than
# an LLM call: it is free, deterministic, and cannot silently regress the way a
# defaulted schema field did.
_NETWORK_TERMS = (
    "network anomaly",
    "network intrusion",
    "intrusion detection",
    "network traffic",
    "packet",
    "netflow",
    "port scan",
    "ddos",
    "exfiltration",
    "firewall",
    "nids",
    "ids ",
    "cyber",
    "malicious traffic",
)
_ANOMALY_TERMS = ("anomaly", "intrusion", "outlier")
_CONTEXT_TERMS = ("network", "traffic", "packet", "flow", "security", "attack")


def is_builtin_anomaly_question(question: str) -> bool:
    """True when the shipped network-flow dataset genuinely fits the question."""
    q = question.lower()
    if any(term in q for term in _NETWORK_TERMS):
        return True
    # "anomaly detection" alone is ambiguous -- require networking context.
    if any(term in q for term in _ANOMALY_TERMS):
        return any(term in q for term in _CONTEXT_TERMS)
    return False


def route_hypothesis(hypothesis, question: str):
    """Force a hypothesis onto the dataset mode its question actually implies.

    Mutates and returns the hypothesis.
    """
    from .graph_codegen import is_graph_algorithm
    from .graph_strategy import is_graph_search_question

    if is_graph_search_question(question):
        hypothesis.dataset_mode = "builtin_graph_search"
        # ML estimator names mean nothing here and would pull the Engineer
        # toward the wrong benchmark entirely.
        if not is_graph_algorithm(hypothesis.approach):
            hypothesis.approach = "ucs"
    elif is_builtin_anomaly_question(question):
        hypothesis.dataset_mode = "builtin_anomaly"
        if hypothesis.approach == "custom":
            hypothesis.approach = "isolation_forest"
    else:
        hypothesis.dataset_mode = "self_contained"
        # The built-in estimator names are anomaly-detection specific and would
        # pull the Engineer back toward the wrong dataset. The proposed name is
        # already coerced to "custom" by validation, so the title is what keeps
        # one self-contained hypothesis distinguishable from another.
        if not hypothesis.variant:
            hypothesis.variant = variant_slug(hypothesis.title)
        hypothesis.approach = "custom"
    return hypothesis
