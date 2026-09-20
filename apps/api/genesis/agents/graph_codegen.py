"""Deterministic experiment code for graph-search research.

The anomaly-detection templates in ``codegen.py`` cover classification. This
module is their counterpart for pathfinding: every algorithm runs against the
identical grid instance from ``genesis_graph``, so runtimes and expanded-node
counts are directly comparable, and every experiment measures its optimality
gap against a ground truth computed independently of it.

Metrics are always produced by executing the search, never asserted.
"""
from __future__ import annotations

from typing import Any

ALGORITHMS = (
    "ucs",
    "astar_manhattan",
    "astar_euclidean",
    "weighted_astar",
    "greedy_best_first",
    "bidirectional_ucs",
)

_PREAMBLE = '''"""GENESIS experiment: {name}

Algorithm : {algorithm}
Benchmark : shared deterministic grid (genesis_graph, seed 42)

Every algorithm in this research run searches the SAME grid, from the same
start to the same goal, with the same edge costs -- otherwise runtimes and
node counts would not be comparable. The optimal cost used for the optimality
gap is computed by genesis_graph itself, not by this experiment.
"""
import heapq
import json
import time
import tracemalloc

from genesis_graph import load_grid, neighbours, optimal_cost, manhattan, euclidean

SEED = 42
cost_grid, start, goal = load_grid(seed=SEED)
OPTIMAL = optimal_cost(SEED)
print(f"grid {{cost_grid.shape[0]}}x{{cost_grid.shape[1]}}  start={{start}}  goal={{goal}}")
print(f"ground-truth optimal cost: {{OPTIMAL:.4f}}")

expanded = 0
generated = 0
tracemalloc.start()
t0 = time.perf_counter()
'''

_BEST_FIRST = '''
# {label}
def _priority(cell, g_cost):
    return {priority}

frontier = [(_priority(start, 0.0), 0.0, start)]
best_g = {{start: 0.0}}
parent = {{start: None}}
closed = set()
found = False

while frontier:
    _, g_cost, cell = heapq.heappop(frontier)
    if cell in closed:
        continue
    closed.add(cell)
    expanded += 1
    if cell == goal:
        found = True
        break
    for nxt, step in neighbours(cell, cost_grid):
        ng = g_cost + step
        if ng < best_g.get(nxt, float("inf")):
            best_g[nxt] = ng
            parent[nxt] = cell
            generated += 1
            heapq.heappush(frontier, (_priority(nxt, ng), ng, nxt))

path_cost = best_g.get(goal, float("inf")) if found else float("inf")
node = goal if found else None
path_length = 0
while node is not None:
    path_length += 1
    node = parent.get(node)
'''

_BIDIRECTIONAL = '''
# Bidirectional uniform-cost search: expand from both ends until the frontiers
# meet, then take the best meeting point.
def _expand(frontier, best_g, parent, closed, other_closed, other_g):
    global expanded, generated
    if not frontier:
        return None
    g_cost, cell = heapq.heappop(frontier)
    if cell in closed:
        return None
    closed.add(cell)
    expanded += 1
    if cell in other_closed:
        return cell
    for nxt, step in neighbours(cell, cost_grid):
        ng = g_cost + step
        if ng < best_g.get(nxt, float("inf")):
            best_g[nxt] = ng
            parent[nxt] = cell
            generated += 1
            heapq.heappush(frontier, (ng, nxt))
    return None

fwd_frontier, bwd_frontier = [(0.0, start)], [(0.0, goal)]
fwd_g, bwd_g = {start: 0.0}, {goal: 0.0}
fwd_parent, bwd_parent = {start: None}, {goal: None}
fwd_closed, bwd_closed = set(), set()
meeting = None

while fwd_frontier and bwd_frontier and meeting is None:
    meeting = _expand(fwd_frontier, fwd_g, fwd_parent, fwd_closed, bwd_closed, bwd_g)
    if meeting is None:
        meeting = _expand(bwd_frontier, bwd_g, bwd_parent, bwd_closed, fwd_closed, fwd_g)

if meeting is not None:
    # fwd(m) covers start->m inclusive of m; bwd(m) covers m->goal inclusive of
    # m but EXCLUSIVE of goal (the backward search starts there at zero). So the
    # meeting cell is double counted and the goal cell is missing.
    path_cost = (
        fwd_g.get(meeting, float("inf"))
        + bwd_g.get(meeting, float("inf"))
        - float(cost_grid[meeting])
        + float(cost_grid[goal])
    )
    length_f, node = 0, meeting
    while node is not None:
        length_f += 1
        node = fwd_parent.get(node)
    length_b, node = 0, bwd_parent.get(meeting)
    while node is not None:
        length_b += 1
        node = bwd_parent.get(node)
    path_length = length_f + length_b
    found = True
else:
    path_cost, path_length, found = float("inf"), 0, False
'''

_EPILOGUE = '''
runtime_ms = (time.perf_counter() - t0) * 1000.0
_current, peak_bytes = tracemalloc.get_traced_memory()
tracemalloc.stop()

if not found:
    raise RuntimeError(
        "search failed to reach the goal on a solvable instance -- "
        "this experiment measured nothing"
    )

# Gap against the independently computed optimum. A negative gap would mean a
# cheaper-than-optimal path, which is impossible and signals a bug.
optimality_gap_percent = (path_cost - OPTIMAL) / OPTIMAL * 100.0
if optimality_gap_percent < -1e-6:
    raise RuntimeError(
        f"path cost {path_cost:.4f} is below the optimum {OPTIMAL:.4f}; "
        "the search or the cost accounting is wrong"
    )
optimality_gap_percent = max(optimality_gap_percent, 0.0)

metrics = {
    "path_cost": float(path_cost),
    "optimality_gap_percent": float(optimality_gap_percent),
    "runtime_ms": float(runtime_ms),
    "expanded_nodes": float(expanded),
    "generated_nodes": float(generated),
    "path_length": float(path_length),
    "peak_memory_kb": float(peak_bytes / 1024.0),
}

for key, value in metrics.items():
    print(f"{key}: {value:.4f}")

with open("result.json", "w") as handle:
    json.dump(
        {
            "status": "success",
            "metrics": metrics,
            # Runtime is the research objective; the optimality gap is the
            # constraint the PI weighs against it.
            "primary_metric": "runtime_ms",
            "metric_direction": "minimize",
            "artifacts": [],
            "execution_time": runtime_ms / 1000.0,
        },
        handle,
    )
print(f"experiment finished in {runtime_ms:.2f} ms")
'''

_BODIES: dict[str, str] = {
    "ucs": _BEST_FIRST.format(
        label="Uniform-cost search: the optimal reference. No heuristic, so it "
        "expands in order of true path cost.",
        priority="g_cost",
    ),
    "astar_manhattan": _BEST_FIRST.format(
        label="A* with an admissible Manhattan heuristic. Admissible because "
        "every step costs at least the minimum terrain cost, so f never "
        "overestimates and optimality is preserved.",
        priority="g_cost + manhattan(cell, goal)",
    ),
    "astar_euclidean": _BEST_FIRST.format(
        label="A* with a Euclidean heuristic -- also admissible on a "
        "4-connected grid, but weaker than Manhattan, so it should expand more.",
        priority="g_cost + euclidean(cell, goal)",
    ),
    "weighted_astar": _BEST_FIRST.format(
        label="Weighted A* (w>1). Inflating the heuristic trades a bounded "
        "optimality gap for speed: the cost is at most w x optimal.",
        priority="g_cost + {weight} * manhattan(cell, goal)",
    ),
    "greedy_best_first": _BEST_FIRST.format(
        label="Greedy best-first: orders purely on the heuristic and ignores "
        "cost so far. Fast, and offers no optimality guarantee at all.",
        priority="manhattan(cell, goal)",
    ),
    "bidirectional_ucs": _BIDIRECTIONAL,
}

_ALLOWED_PARAMS = {"weighted_astar": {"weight"}}
_DEFAULTS: dict[str, dict[str, Any]] = {"weighted_astar": {"weight": 1.5}}


def is_graph_algorithm(name: str) -> bool:
    return name in _BODIES


def generate_graph_experiment_code(algorithm: str, name: str, parameters: dict[str, Any] | None = None) -> str:
    """Build a runnable graph-search experiment for one algorithm."""
    if algorithm not in _BODIES:
        algorithm = "ucs"

    body = _BODIES[algorithm]
    if algorithm == "weighted_astar":
        params = dict(_DEFAULTS["weighted_astar"])
        for key, value in (parameters or {}).items():
            if key in _ALLOWED_PARAMS["weighted_astar"] and isinstance(value, (int, float)):
                params[key] = float(value)
        # A weight below 1 makes the heuristic pessimistic and the search
        # slower than plain UCS, which tests nothing.
        weight = max(1.0, min(float(params["weight"]), 5.0))
        body = body.replace("{weight}", repr(weight))

    return _PREAMBLE.format(name=name, algorithm=algorithm) + body + _EPILOGUE


GRAPH_CODE_CONTRACT = """\
This is a GRAPH-SEARCH experiment, not a machine-learning one. It MUST obey
this contract:

* Available imports: heapq, math, time, tracemalloc, numpy, and the provided
  `genesis_graph` module. There is no network.
* Load the benchmark ONLY via:
      from genesis_graph import load_grid, neighbours, optimal_cost, manhattan
      cost_grid, start, goal = load_grid(seed=42)
      OPTIMAL = optimal_cost(42)
  Every experiment in this run must use the SAME seed, start and goal --
  otherwise runtimes and node counts are not comparable.
* Do NOT compute your own optimum. `optimal_cost` is ground truth, computed
  independently; comparing an experiment against its own claim is meaningless.
* Count `expanded` (nodes popped and closed) and `generated` (nodes pushed).
* Report these metrics, all measured:
      path_cost, optimality_gap_percent, runtime_ms, expanded_nodes,
      generated_nodes, path_length, peak_memory_kb
  with optimality_gap_percent = (path_cost - OPTIMAL) / OPTIMAL * 100
* Declare ranking explicitly:
      "primary_metric": "runtime_ms", "metric_direction": "minimize"
* Raise if the goal is unreachable or the cost is below the optimum -- a run
  that measured nothing is a failure, not a result.
* Write everything to `result.json`. Keep runtime under 90 seconds.
"""
