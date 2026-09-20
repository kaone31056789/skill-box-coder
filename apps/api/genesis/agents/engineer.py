"""ENGINEER -- writes and repairs executable experiment code.

Always returns runnable code. If the LLM is unavailable, or its code fails
twice in the sandbox, the deterministic generator takes over so the research
loop is never blocked by a code-generation failure.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from .codegen import CODE_CONTRACT, generate_experiment_code
from .graph_codegen import (
    GRAPH_CODE_CONTRACT,
    generate_graph_experiment_code,
    is_graph_algorithm,
)
from .llm import LLMError, get_llm
from .schemas import ExperimentDesign, GeneratedCode

logger = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 2

# An experiment program is ~100-200 lines. The global budget (32k) exists for
# reasoning headroom elsewhere; handing it to code generation just invites the
# model to deliberate for minutes.
CODE_TOKEN_BUDGET = 12000

SYSTEM = (
    "You are ENGINEER, the research engineer of an autonomous lab. You write "
    "clean, reproducible, self-contained Python experiment code. Your code runs "
    "unattended in a locked-down sandbox, so it must be correct on the first run: "
    "no interactive input, no network, no file access beyond the working "
    "directory. Return the complete program, never a fragment or a diff."
)


class EngineerAgent:
    name = "ENGINEER"

    def generate(self, design: ExperimentDesign, hypothesis_title: str) -> tuple[str, str]:
        """Return ``(code, origin)`` where origin is 'llm' or 'template'."""
        graph_search = design.dataset_mode == "builtin_graph_search"
        if graph_search:
            reference = generate_graph_experiment_code(
                design.approach, design.name, design.parameters
            )
        else:
            reference = generate_experiment_code(design)
        # Both built-in domains have verified templates covering every approach.
        builtin = design.dataset_mode in ("builtin_anomaly", "builtin_graph_search")
        mode = get_settings().engineer_mode

        # A built-in design is fully covered by the template, which is verified
        # by tests and costs nothing. Asking a model to reproduce it added
        # minutes per experiment for no gain, so `auto` uses the template here
        # and saves the model for designs it alone can write.
        if mode == "template" or (mode == "auto" and builtin):
            logger.info("engineer: using verified template for %s", design.name)
            return reference, "template"

        llm = get_llm()
        if not llm.enabled:
            if not builtin:
                # No LLM and no template for this domain: the fallback below is
                # anomaly-detection code, which would not test the hypothesis.
                logger.warning(
                    "self-contained design %r needs an LLM to author its experiment; "
                    "falling back to the built-in baseline",
                    design.name,
                )
            return reference, "deterministic"

        # The worked example only helps when the experiment really does use the
        # shipped dataset. Showing it for a self-contained design just tempts
        # the model into importing genesis_data for an unrelated question.
        guidance = (
            "Here is a known-good reference implementation for this class of "
            "experiment. Follow its structure and its result.json contract "
            f"exactly, adapting it to the specification above:\n"
            f"```python\n{reference}\n```"
            if builtin
            else (
                "This experiment is self-contained: generate the dataset inside "
                "the program with numpy (seed 42). Do NOT import genesis_data. "
                "Make the generative process a fair test of the hypothesis and "
                "explain it in a comment."
            )
        )

        try:
            result = llm.complete_json(
                SYSTEM,
                (
                    f"Hypothesis under test: {hypothesis_title}\n\n"
                    f"Experiment specification:\n{design.model_dump_json(indent=2)}\n\n"
                    f"{GRAPH_CODE_CONTRACT if graph_search else CODE_CONTRACT}\n"
                    f"{guidance}\n\n"
                    "Return the full program in the 'code' field."
                ),
                GeneratedCode,
                temperature=0.3,
                max_tokens=CODE_TOKEN_BUDGET,
                task="engineer",
            )
            return result.code, "llm"
        except LLMError as exc:
            logger.warning("engineer LLM failed (%s); using deterministic code", exc)
            return reference, "deterministic"

    def repair(
        self,
        design: ExperimentDesign,
        failed_code: str,
        error: str,
        stderr: str,
        attempt: int,
    ) -> tuple[str, str]:
        """Attempt to fix code that failed in the sandbox.

        The final attempt falls back to the deterministic generator, which is
        known to run -- better a working experiment than a third failure.
        """
        llm = get_llm()
        if not llm.enabled or attempt > MAX_REPAIR_ATTEMPTS:
            return generate_experiment_code(design), "deterministic"

        try:
            result = llm.complete_json(
                SYSTEM,
                (
                    f"The experiment below failed in the sandbox (repair attempt "
                    f"{attempt} of {MAX_REPAIR_ATTEMPTS}).\n\n"
                    f"Specification:\n{design.model_dump_json(indent=2)}\n\n"
                    f"Error: {error}\n\n"
                    f"stderr (tail):\n{stderr[-2500:]}\n\n"
                    f"Failing code:\n```python\n{failed_code}\n```\n\n"
                    f"{CODE_CONTRACT}\n"
                    "Diagnose the root cause and return the COMPLETE corrected program. "
                    "Do not paper over the error with a try/except that fabricates "
                    "metrics -- the metrics must come from a real model evaluation. "
                    "Explain the fix in the 'notes' field."
                ),
                GeneratedCode,
                temperature=0.2,
                max_tokens=CODE_TOKEN_BUDGET,
                task="engineer",
            )
            return result.code, "llm"
        except LLMError as exc:
            logger.warning("engineer repair failed (%s); using deterministic code", exc)
            return generate_experiment_code(design), "deterministic"
