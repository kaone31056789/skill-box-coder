"""Central configuration. Every secret comes from the environment."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["auto", "openrouter", "anthropic", "offline"]
EngineerMode = Literal["auto", "llm", "template"]

# Measured on this project's structured-output workload; see docs/MODELS.md.
# Ordered fastest-capable first, ending on a free model so a run degrades to
# zero cost rather than failing when a paid provider is rate limited.
_FREE_TAIL = "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_ROUTES: dict[str, str] = {
    # Short structured summaries of paper abstracts -- cheap and fast wins.
    "scout": f"qwen/qwen3.7-flash,deepseek/deepseek-v4-flash-0731,{_FREE_TAIL}",
    # Creative but schema-bound; deepseek was both fastest and most reliable.
    "scientist": f"deepseek/deepseek-v4-flash-0731,qwen/qwen3.7-flash,{_FREE_TAIL}",
    "experimentalist": f"deepseek/deepseek-v4-flash-0731,qwen/qwen3.7-flash,{_FREE_TAIL}",
    # Long-form code. ox-alpha is deliberately excluded: it failed to return a
    # valid program on this task in every trial.
    "engineer": f"deepseek/deepseek-v4-flash-0731,{_FREE_TAIL}",
    "analyst": f"deepseek/deepseek-v4-flash-0731,qwen/qwen3.7-flash,{_FREE_TAIL}",
    # Judgement over evidence; the larger free model is a good second opinion.
    "pi": f"deepseek/deepseek-v4-flash-0731,nvidia/nemotron-3-ultra-550b-a55b:free,{_FREE_TAIL}",
}
SandboxBackend = Literal["auto", "docker", "subprocess"]


def _repo_root() -> str:
    # genesis/config.py -> genesis -> api -> apps -> <repo root>
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(os.path.join(_repo_root(), ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- LLM ----------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    anthropic_api_key: str = ""
    llm_provider: ProviderName = "auto"
    llm_model: str = "anthropic/claude-sonnet-4.5"
    # Ordered, comma-separated failover chain, tried left to right when the
    # primary model errors, is rate limited, or keeps returning unusable
    # output. Empty disables failover. Used for any task without its own route.
    llm_fallback_models: str = (
        "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3-ultra-550b-a55b:free"
    )

    # Per-task routes. Each is a comma-separated chain; the first entry is the
    # preferred model. Empty falls back to llm_model + llm_fallback_models.
    # Defaults come from measured latency on this workload -- see docs/MODELS.md.
    llm_route_scout: str = ""
    llm_route_scientist: str = ""
    llm_route_experimentalist: str = ""
    llm_route_engineer: str = ""
    llm_route_analyst: str = ""
    llm_route_pi: str = ""
    # Reasoning models spend this budget before emitting any content, and the
    # Engineer must return a whole program. 4k left it returning empty strings.
    llm_max_tokens: int = 32768
    llm_temperature: float = 0.7
    llm_timeout_seconds: float = 120.0
    # Reasoning models bill thinking against max_tokens and wall clock. Code
    # generation does not benefit from extended deliberation, and unconstrained
    # reasoning was costing minutes per experiment.
    # low | medium | high | none
    llm_reasoning_effort: str = "low"
    # How the Engineer produces experiment code. See genesis/agents/engineer.py.
    engineer_mode: EngineerMode = "auto"

    # ---------- Database ----------
    database_url: str = "sqlite:///./genesis.db"

    # ---------- Sandbox ----------
    sandbox_backend: SandboxBackend = "auto"
    sandbox_timeout_seconds: int = 180
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    sandbox_image: str = "genesis-sandbox:latest"

    # ---------- Literature ----------
    enable_arxiv: bool = True
    arxiv_timeout_seconds: float = 12.0
    max_papers: int = 12

    # ---------- API ----------
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Railway/Heroku hand out `postgres://` or `postgresql://`.

        SQLAlchemy 2 needs an explicit driver, and we ship psycopg 3.
        """
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @property
    def resolved_provider(self) -> str:
        """Which LLM provider will actually be used."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.openrouter_api_key.strip():
            return "openrouter"
        if self.anthropic_api_key.strip():
            return "anthropic"
        return "offline"

    @property
    def llm_model_chain(self) -> list[str]:
        """Primary model followed by each distinct fallback, in order."""
        return self.model_chain_for(None)

    def model_chain_for(self, task: str | None) -> list[str]:
        """Resolve the model chain for an agent task.

        A task route, when set, takes precedence; the general chain is then
        appended as a last resort so no task can be left with nothing to try.
        """
        chain: list[str] = []

        def _extend(raw: str) -> None:
            for name in raw.split(","):
                name = name.strip()
                if name and name not in chain:
                    chain.append(name)

        if task:
            _extend(getattr(self, f"llm_route_{task}", "") or DEFAULT_ROUTES.get(task, ""))
        _extend(self.llm_model)
        _extend(self.llm_fallback_models)
        return [m for m in chain if m]

    @property
    def cors_origin_list(self) -> list[str]:
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return raw or ["http://localhost:3000", "http://127.0.0.1:3000"]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
