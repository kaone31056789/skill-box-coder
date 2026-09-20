"""Deterministic pathfinding benchmark for GENESIS graph-search experiments.

TRUSTED code, copied into the sandbox beside the untrusted experiment. Shipping
the benchmark as code is what lets the sandbox run with no network.

Why this module exists
----------------------
Comparing search algorithms is only meaningful if every algorithm sees the
*same* problem. This module fixes the grid, the start, the goal, the edge costs
and the obstacle layout for a given seed, so EXP-002 is measured against the
identical instance as EXP-001.

It also provides the ground-truth optimal cost, computed here by an exhaustive
uniform-cost search rather than taken from any experiment's own claim. That is
what makes `optimality_gap_percent` trustworthy: an experiment cannot define
its own optimum.
"""
from __future__ import annotations

import heapq
from functools import lru_cache

import numpy as np

__all__ = [
    "GRID_SIZE",
    "load_grid",
    "neighbours",
    "optimal_cost",
    "manhattan",
    "euclidean",
    "describe",
]

GRID_SIZE = 96
_OBSTACLE_RATE = 0.24
# Terrain cost varies so this is a genuine weighted search rather than a maze:
# an algorithm can find a *shorter* route that is more *expensive*. The range is
# deliberately mild. Measured on this instance, the ratio of the admissible
# heuristic to the true optimum (h/h*) drives whether A* helps at all:
#     cost range 1..2.5 -> h/h* 0.64 -> A* expands 99% of UCS (useless)
#     cost range 1..1.2 -> h/h* 0.93 -> A* expands 65% of UCS
# Wide cost variance makes any distance-based admissible heuristic a poor
# lower bound, and A* degenerates to UCS.
_MIN_COST = 1.0
_MAX_COST = 1.2


def load_grid(seed: int = 42, size: int = GRID_SIZE):
    """Return ``(cost_grid, start, goal)`` for a deterministic instance.

    ``cost_grid`` is a float array where ``inf`` marks an obstacle and any
    finite value is the cost of entering that cell. Start and goal are opposite
    corners and are guaranteed traversable and connected.
    """
    rng = np.random.default_rng(seed)

    # Smooth, clustered terrain: random noise blurred so costs form regions
    # rather than salt-and-pepper, which makes heuristics behave realistically.
    noise = rng.random((size, size))
    smooth = noise.copy()
    for _ in range(2):
        padded = np.pad(smooth, 1, mode="edge")
        smooth = (
            padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2]
            + padded[1:-1, 2:] + padded[1:-1, 1:-1]
        ) / 5.0
    smooth = (smooth - smooth.min()) / max(smooth.max() - smooth.min(), 1e-9)
    cost = _MIN_COST + smooth * (_MAX_COST - _MIN_COST)

    obstacles = rng.random((size, size)) < _OBSTACLE_RATE
    cost[obstacles] = np.inf

    start, goal = (0, 0), (size - 1, size - 1)
    cost[start] = _MIN_COST
    cost[goal] = _MIN_COST

    # Guarantee the instance is solvable. A benchmark where no path exists
    # measures nothing, and every algorithm would tie at "failed".
    if not np.isfinite(_ucs(cost, start, goal)[0]):
        cost = _carve_corridor(cost, start, goal, rng)

    return cost, start, goal


def _carve_corridor(cost, start, goal, rng):
    """Open a winding corridor so the instance is always solvable."""
    cost = cost.copy()
    row, col = start
    goal_row, goal_col = goal
    while (row, col) != (goal_row, goal_col):
        cost[row, col] = min(cost[row, col], _MAX_COST)
        if row < goal_row and (col == goal_col or rng.random() < 0.5):
            row += 1
        elif col < goal_col:
            col += 1
        else:
            row += 1
    cost[goal_row, goal_col] = _MIN_COST
    return cost


def neighbours(cell, cost_grid):
    """4-connected traversable neighbours of ``cell`` as ``(cell, step_cost)``."""
    row, col = cell
    size = cost_grid.shape[0]
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        r, c = row + dr, col + dc
        if 0 <= r < size and 0 <= c < size:
            step = cost_grid[r, c]
            if np.isfinite(step):
                out.append(((r, c), float(step)))
    return out


def _ucs(cost_grid, start, goal):
    """Uniform-cost search. Returns ``(cost, expanded)``; cost is inf if unreachable."""
    frontier = [(0.0, start)]
    best = {start: 0.0}
    seen: set = set()
    expanded = 0
    while frontier:
        dist, cell = heapq.heappop(frontier)
        if cell in seen:
            continue
        seen.add(cell)
        expanded += 1
        if cell == goal:
            return dist, expanded
        for nxt, step in neighbours(cell, cost_grid):
            nd = dist + step
            if nd < best.get(nxt, float("inf")):
                best[nxt] = nd
                heapq.heappush(frontier, (nd, nxt))
    return float("inf"), expanded


@lru_cache(maxsize=8)
def optimal_cost(seed: int = 42, size: int = GRID_SIZE) -> float:
    """Ground-truth optimal path cost for this instance.

    Computed here, by exhaustive search, so `optimality_gap_percent` measures an
    experiment against an independent optimum rather than its own claim.
    """
    cost_grid, start, goal = load_grid(seed=seed, size=size)
    return _ucs(cost_grid, start, goal)[0]


def manhattan(cell, goal, min_step: float = _MIN_COST) -> float:
    """Admissible heuristic: never overestimates, since every step costs >= min_step."""
    return (abs(cell[0] - goal[0]) + abs(cell[1] - goal[1])) * min_step


def euclidean(cell, goal, min_step: float = _MIN_COST) -> float:
    return float(np.hypot(cell[0] - goal[0], cell[1] - goal[1])) * min_step


def describe(seed: int = 42) -> dict[str, object]:
    """Instance summary, used by the Experimentalist agent."""
    cost_grid, start, goal = load_grid(seed=seed)
    finite = np.isfinite(cost_grid)
    return {
        "grid": f"{GRID_SIZE}x{GRID_SIZE} 4-connected weighted grid",
        "traversable_cells": int(finite.sum()),
        "obstacle_cells": int((~finite).sum()),
        "step_cost_range": [_MIN_COST, _MAX_COST],
        "start": list(start),
        "goal": list(goal),
        "optimal_cost": round(optimal_cost(seed), 4),
        "seed": seed,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(describe(), indent=2))
