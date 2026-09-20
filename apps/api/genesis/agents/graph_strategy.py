"""Graph-search research domain: detection and candidate registry.

A second built-in domain alongside anomaly detection. Without a candidate
registry here a pathfinding run executed its baseline and then reported "No
untested hypotheses remain in the search space" -- the Scientist had nothing
domain-appropriate to propose, so the research stopped after one experiment.

Kept separate from ``strategy.py`` so the anomaly ladder stays untouched.
"""
from __future__ import annotations

from .strategy import Rung, signature

_GRAPH_TERMS = (
    "pathfinding", "path finding", "graph search", "graph-search",
    "shortest path", "route planning", "routing algorithm", "traversal",
    "a*", "a-star", "astar", "dijkstra", "heuristic search", "best-first",
    "maze", "navigation", "search algorithm", "expanded nodes",
)


def is_graph_search_question(question: str) -> bool:
    """True when the shipped pathfinding benchmark genuinely fits the question."""
    lowered = question.lower()
    return any(term in lowered for term in _GRAPH_TERMS)


GRAPH_BASELINE = Rung(
    approach="ucs",
    feature_set="base",
    threshold_strategy="default",
    title="Uniform-cost search establishes the optimal reference",
    description=(
        "Run uniform-cost search over the shared weighted grid to obtain the true "
        "optimal path cost, its runtime, and the number of nodes expanded."
    ),
    rationale=(
        "Every later claim about speed or path quality needs a reference that is "
        "known optimal. UCS expands in order of true path cost and uses no "
        "heuristic, so its result is the ground truth the others are measured "
        "against."
    ),
    expected_outcome=(
        "Optimal path cost with a 0% optimality gap by definition, at the highest "
        "node-expansion count of any method tested."
    ),
    assumptions=(
        "Edge costs are non-negative, so uniform-cost search is optimal",
        "The instance is solvable and identical for every experiment",
    ),
    difficulty="low",
    expected_improvement=0.0,
    confidence=0.95,
)

GRAPH_LADDER: tuple[Rung, ...] = (
    Rung(
        approach="astar_manhattan",
        feature_set="base",
        threshold_strategy="default",
        title=(
            "A* with an admissible Manhattan heuristic preserves optimality while "
            "expanding fewer nodes"
        ),
        description=(
            "Order the frontier by g + h, where h is Manhattan distance scaled by "
            "the minimum step cost. Because h never overestimates, optimality is "
            "preserved while the search is directed toward the goal."
        ),
        rationale=(
            "UCS explores outward in every direction because it has no notion of "
            "where the goal is. An admissible heuristic keeps the optimality "
            "guarantee and should cut expansions substantially."
        ),
        expected_outcome=(
            "Identical path cost to UCS, 0% gap, with fewer nodes expanded and "
            "lower runtime."
        ),
        assumptions=(
            "Manhattan distance times the minimum step cost never overestimates",
            "The heuristic is informative enough to change the expansion order",
        ),
        difficulty="low",
        expected_improvement=0.35,
        confidence=0.88,
    ),
    Rung(
        approach="weighted_astar",
        feature_set="base",
        threshold_strategy="default",
        title="Weighted A* trades a bounded optimality gap for a large speedup",
        description=(
            "Inflate the heuristic by w > 1 so the search commits toward the goal "
            "sooner. The resulting path cost is bounded by w times optimal."
        ),
        rationale=(
            "If the research permits paths close to optimal rather than exactly "
            "optimal, weighting the heuristic is the standard way to buy speed -- "
            "and the price of that speed is directly measurable as the gap."
        ),
        expected_outcome=(
            "Much lower runtime and expansions, with a small positive optimality gap."
        ),
        assumptions=(
            "A small optimality gap is acceptable for this research question",
            "The bound of w x optimal holds for the chosen weight",
        ),
        difficulty="low",
        expected_improvement=0.5,
        confidence=0.85,
    ),
    Rung(
        approach="greedy_best_first",
        feature_set="base",
        threshold_strategy="default",
        title=(
            "Greedy best-first minimises search effort but abandons any optimality "
            "guarantee"
        ),
        description=(
            "Order the frontier on the heuristic alone, ignoring the cost incurred "
            "so far, and measure how much path quality that sacrifices."
        ),
        rationale=(
            "This is the extreme end of the speed/quality trade-off. Quantifying how "
            "poor its path is establishes whether the middle ground of weighted A* "
            "is worth anything."
        ),
        expected_outcome=(
            "Fewest expansions of any method, with a clearly worse path cost."
        ),
        assumptions=(
            "Path quality may be sacrificed for the purpose of this comparison",
        ),
        difficulty="low",
        expected_improvement=0.3,
        confidence=0.8,
    ),
    Rung(
        approach="bidirectional_ucs",
        feature_set="base",
        threshold_strategy="default",
        title="Bidirectional search meets in the middle to shrink the explored region",
        description=(
            "Search forward from the start and backward from the goal until the "
            "frontiers meet, then reconstruct the path through the meeting point."
        ),
        rationale=(
            "Two searches of radius r/2 cover less area than one of radius r, so "
            "expansions should fall without needing a heuristic at all."
        ),
        expected_outcome=(
            "Fewer expansions than UCS; stopping at the first meeting point may "
            "leave a small optimality gap."
        ),
        assumptions=(
            "The graph can be searched backward from the goal",
            "The first meeting point is close enough to optimal to be useful",
        ),
        difficulty="medium",
        expected_improvement=0.25,
        confidence=0.7,
    ),
    Rung(
        approach="astar_euclidean",
        feature_set="base",
        threshold_strategy="default",
        title=(
            "A Euclidean heuristic is admissible but weaker than Manhattan on a "
            "4-connected grid"
        ),
        description=(
            "Replace the Manhattan heuristic with Euclidean distance and measure how "
            "heuristic tightness alone affects the number of expansions."
        ),
        rationale=(
            "On a 4-connected grid, Euclidean distance is a looser lower bound than "
            "Manhattan. Isolating that difference shows how much heuristic quality "
            "matters independently of the algorithm."
        ),
        expected_outcome="Same optimal cost, but more nodes expanded than Manhattan A*.",
        assumptions=("Euclidean distance remains admissible on this grid",),
        difficulty="low",
        expected_improvement=0.15,
        confidence=0.75,
    ),
)


def next_graph_rungs(tried: set[str], limit: int = 3) -> list[Rung]:
    """Highest-value untried graph-search candidates, best expected value first."""
    remaining = [
        rung
        for rung in GRAPH_LADDER
        if signature(rung.approach, rung.feature_set, rung.threshold_strategy)
        not in tried
    ]
    remaining.sort(key=lambda r: -(r.expected_improvement * r.confidence))
    return remaining[:limit]


GRAPH_CAPABILITIES = """\
This question is about GRAPH SEARCH / PATHFINDING, so experiments use the
shipped benchmark (dataset_mode="builtin_graph_search").

   approach : ucs                | uniform-cost search, the optimal reference
              astar_manhattan    | A*, admissible Manhattan heuristic
              astar_euclidean    | A*, admissible Euclidean heuristic
              weighted_astar     | A* with an inflated heuristic (w > 1)
              greedy_best_first  | heuristic only, no optimality guarantee
              bidirectional_ucs  | search from both ends until they meet

Benchmark: a fixed 96x96 4-connected weighted grid with ~24% obstacles and mild
terrain costs, start at one corner and goal at the opposite one. EVERY
experiment uses the identical instance, so runtimes and expansion counts are
directly comparable. The optimal cost is computed independently by the
benchmark itself, so an experiment cannot define its own optimum.

Metrics measured: path_cost, optimality_gap_percent, runtime_ms,
expanded_nodes, generated_nodes, path_length, peak_memory_kb.

This is NOT a machine-learning problem. Do not propose classifiers, feature
engineering, F1, precision, recall or false-positive rate -- none of those mean
anything here. Propose search strategies and heuristics.
"""
