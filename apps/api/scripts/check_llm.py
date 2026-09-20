"""Verify the configured LLM provider end to end.

Run this after putting your key in .env, before a demo:

    apps/api/.venv/Scripts/python.exe apps/api/scripts/check_llm.py

It makes one real structured call per critical agent path and validates the
response against the same Pydantic schemas the orchestrator uses, so a
misconfigured key or an unavailable model fails here rather than mid-demo.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows consoles default to cp1252, which cannot encode the box-drawing and
# tick characters below. Force UTF-8 rather than crash on a demo machine.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from genesis.agents.llm import LLMError, get_llm  # noqa: E402
from genesis.agents.schemas import HypothesisSet, PIDecision  # noqa: E402
from genesis.config import get_settings  # noqa: E402

QUESTION = "Do temporal context features improve network anomaly detection?"


def main() -> int:
    settings = get_settings()
    llm = get_llm()

    print("=" * 62)
    print("GENESIS -- LLM configuration check")
    print("=" * 62)
    print(f"  provider      : {llm.provider}")
    print(f"  model         : {settings.llm_model}")
    print(f"  base url      : {settings.openrouter_base_url}")
    key = settings.openrouter_api_key or settings.anthropic_api_key
    print(f"  key present   : {'yes (' + str(len(key)) + ' chars)' if key else 'NO'}")
    print()

    if not llm.enabled:
        print("  [FAIL] No LLM configured -- agents will run their deterministic")
        print("    strategies, so every research question produces the same")
        print("    experiment sequence.")
        print()
        print("  Fix: put your key in the repo-root .env file:")
        print("      OPENROUTER_API_KEY=sk-or-v1-...")
        print("      LLM_MODEL=stealth/ox-alpha")
        return 1

    failures = 0

    # -- 1. Structured hypothesis generation -------------------------------
    print("  [1/2] hypothesis generation …", end=" ", flush=True)
    started = time.perf_counter()
    try:
        result = llm.complete_json(
            "You are SCIENTIST, a research hypothesis generator.",
            f"Research question: {QUESTION}\n\nPropose 2 competing hypotheses.",
            HypothesisSet,
            temperature=0.7,
        )
        print(f"ok ({time.perf_counter() - started:.1f}s)")
        for hypothesis in result.hypotheses[:2]:
            print(f"        - {hypothesis.title[:78]}")
    except LLMError as exc:
        failures += 1
        print(f"FAILED\n        {exc}")

    # -- 2. Structured decision making -------------------------------------
    print("  [2/2] PI decision …", end=" ", flush=True)
    started = time.perf_counter()
    try:
        decision = llm.complete_json(
            "You are the PRINCIPAL INVESTIGATOR of an autonomous research lab.",
            (
                f"Research question: {QUESTION}\n"
                "Candidates:\n  [0] Add windowed features\n  [1] Switch model family\n"
                "Choose one by index and justify it with evidence."
            ),
            PIDecision,
            temperature=0.5,
        )
        print(f"ok ({time.perf_counter() - started:.1f}s)")
        print(f"        - chose #{decision.selected_hypothesis_index}: {decision.decision[:66]}")
    except LLMError as exc:
        failures += 1
        print(f"FAILED\n        {exc}")

    print()
    if failures:
        print(f"  [FAIL] {failures} check(s) failed -- GENESIS will fall back to its")
        print("    deterministic agents for those steps.")
        return 1

    print("  [OK] LLM path healthy. Agents will reason about the actual question.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
