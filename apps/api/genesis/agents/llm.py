"""LLM client with schema-validated structured output.

Supports OpenRouter (default) and the Anthropic API directly. When no key is
configured the client reports ``enabled == False`` and each agent falls back
to its deterministic strategy -- the research loop still runs end to end, and
experiment metrics still come from real sandbox execution either way.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

# Output budget per task. This is not just a cost control: OpenRouter sizes a
# reasoning model's thinking budget as a FRACTION OF max_tokens, so handing a
# 32k budget to a call that emits ~1.5k of JSON buys minutes of deliberation
# for nothing. A baseline-hypothesis call took 170s before these caps.
TASK_TOKEN_BUDGET: dict[str, int] = {
    "scout": 3000,           # ScoutReport: concepts, methods, gaps
    "scientist": 6000,       # HypothesisSet: 3 hypotheses with rationale
    "experimentalist": 3000, # ExperimentDesign: a flat spec
    "engineer": 12000,       # GeneratedCode: a whole program
    "analyst": 3000,         # AnalysisReport: verdict and findings
    "pi": 3000,              # PIDecision / FinalSummary
}
DEFAULT_TASK_BUDGET = 4000


class LLMError(RuntimeError):
    """Raised when the provider fails or returns unusable output."""


def extract_json(text: str) -> str:
    """Pull a JSON object out of a model response.

    Handles fenced blocks and stray prose around the payload.
    """
    text = text.strip()
    if not text:
        raise LLMError("empty response from model")

    fenced = _JSON_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    # Fall back to the outermost balanced braces.
    start = text.find("{")
    if start == -1:
        raise LLMError("no JSON object found in response")
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise LLMError("unterminated JSON object in response")


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.resolved_provider
        self.model = self.settings.llm_model
        self.model_chain = self.settings.llm_model_chain
        self._client: object | None = None

        if self.provider == "openrouter":
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    base_url=self.settings.openrouter_base_url,
                    api_key=self.settings.openrouter_api_key,
                    timeout=self.settings.llm_timeout_seconds,
                    # No SDK-level retries: complete_json already retries and
                    # then fails over across the model chain. Leaving them on
                    # multiplies the timeout (3 SDK tries x 120s per attempt
                    # per model), which is how a single slow model stalls an
                    # entire research run.
                    max_retries=0,
                )
            except Exception as exc:  # pragma: no cover - import/config failure
                logger.warning("openrouter client unavailable (%s); using offline agents", exc)
                self.provider = "offline"
        elif self.provider == "anthropic":
            try:
                import anthropic

                self._client = anthropic.Anthropic(
                    api_key=self.settings.anthropic_api_key,
                    timeout=self.settings.llm_timeout_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("anthropic client unavailable (%s); using offline agents", exc)
                self.provider = "offline"

    @property
    def enabled(self) -> bool:
        return self.provider in ("openrouter", "anthropic") and self._client is not None

    # ---------------------------------------------------------------- raw
    def _complete(
        self,
        system: str,
        user: str,
        temperature: float | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        temp = self.settings.llm_temperature if temperature is None else temperature
        model = model or self.model
        budget = max_tokens or self.settings.llm_max_tokens

        if self.provider == "openrouter":
            # OpenRouter's unified reasoning control. Without it a reasoning
            # model deliberates unboundedly against max_tokens, which is how a
            # single code-generation call reached 359 seconds.
            effort = self.settings.llm_reasoning_effort.strip().lower()
            extra_body: dict[str, object] = {}
            if effort in ("low", "medium", "high"):
                extra_body["reasoning"] = {"effort": effort}
            elif effort == "none":
                extra_body["reasoning"] = {"exclude": True}

            response = self._client.chat.completions.create(  # type: ignore[union-attr]
                model=model,
                max_tokens=budget,
                temperature=temp,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                extra_headers={
                    "HTTP-Referer": "https://github.com/genesis-lab/genesis",
                    "X-Title": "GENESIS Autonomous Research Lab",
                },
                extra_body=extra_body,
            )
            if not response.choices:
                raise LLMError("provider returned no choices")
            return response.choices[0].message.content or ""

        if self.provider == "anthropic":
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=model,
                max_tokens=budget,
                temperature=temp,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            )

        raise LLMError("no LLM provider configured")

    # ------------------------------------------------------------ structured
    def complete_json(
        self,
        system: str,
        user: str,
        model_cls: type[T],
        max_attempts: int = 3,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task: str | None = None,
    ) -> T:
        """Call the model and validate the response against ``model_cls``.

        Invalid JSON or schema violations are fed back to the model and
        retried. After ``max_attempts`` the caller falls back to its
        deterministic path rather than persisting unvalidated output.
        """
        if not self.enabled:
            raise LLMError("LLM provider not configured")

        # Size the budget to the task unless the caller was explicit. Left at
        # the global default, reasoning models spend minutes thinking.
        if max_tokens is None:
            max_tokens = min(
                TASK_TOKEN_BUDGET.get(task or "", DEFAULT_TASK_BUDGET),
                self.settings.llm_max_tokens,
            )

        schema = json.dumps(model_cls.model_json_schema(), indent=2)
        base_prompt = (
            f"{user}\n\n"
            "Respond with a single JSON object and nothing else. "
            f"It must validate against this JSON Schema:\n{schema}"
        )
        last_error = ""

        # Walk the failover chain. A model that is overloaded, rate limited,
        # or simply bad at holding a JSON schema should not take the whole
        # research run down with it.
        # A task route picks a model suited to this specific call; without one
        # we use the general chain.
        chain = self.settings.model_chain_for(task) if task else self.model_chain

        for model_index, model in enumerate(chain):
            prompt = base_prompt
            for attempt in range(1, max_attempts + 1):
                try:
                    raw = self._complete(
                        system, prompt, temperature, model=model, max_tokens=max_tokens
                    )
                    result = model_cls.model_validate_json(extract_json(raw))
                    if model_index > 0:
                        logger.info(
                            "%s satisfied by fallback model %s (task=%s)",
                            model_cls.__name__,
                            model,
                            task or "general",
                        )
                    return result
                except (ValidationError, LLMError, json.JSONDecodeError) as exc:
                    last_error = str(exc)[:900]
                    logger.warning(
                        "%s attempt %d/%d on %s failed validation: %s",
                        model_cls.__name__,
                        attempt,
                        max_attempts,
                        model,
                        last_error,
                    )
                    # An empty response means the model spent its whole token
                    # budget on reasoning before emitting content. Retrying the
                    # same model is counter-productive: the retry prompt is
                    # LONGER (it carries the error text), so there is even less
                    # budget left. Switch models instead.
                    if "empty response" in last_error:
                        logger.warning(
                            "%s returned no content on %s (token budget exhausted "
                            "by reasoning); moving to the next model",
                            model_cls.__name__,
                            model,
                        )
                        break
                    prompt = (
                        f"{user}\n\nYour previous response was rejected:\n{last_error}\n\n"
                        "Return ONLY a valid JSON object matching this schema:\n"
                        f"{schema}"
                    )
                except Exception as exc:  # provider/network failure
                    last_error = str(exc)[:900]
                    logger.warning("LLM provider error on %s: %s", model, last_error)
                    break  # switch models rather than hammer a failing one

        raise LLMError(f"failed to obtain valid {model_cls.__name__}: {last_error}")


_client: LLMClient | None = None

# Per-thread override. The orchestrator runs each research run on its own
# thread, so a demo run can opt out of the LLM without touching global config
# or disturbing a concurrent live run.
_local = threading.local()


class _DisabledLLM:
    """Stands in for the client when a run has opted out of model calls."""

    provider = "deterministic"
    model = "deterministic"
    model_chain: list[str] = []
    enabled = False

    def complete_json(self, *args: object, **kwargs: object):
        raise LLMError("LLM disabled for this run")


def set_llm_enabled(enabled: bool) -> None:
    """Enable or disable model calls for the calling thread."""
    _local.enabled = enabled


def get_llm() -> LLMClient:
    if getattr(_local, "enabled", True) is False:
        return _DisabledLLM()  # type: ignore[return-value]
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
