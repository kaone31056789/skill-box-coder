"""GENESIS API entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api_schemas import SystemStatusOut
from .config import get_settings
from .db import init_db
from .events import bus
from .literature.arxiv import CURATED_CORPUS
from .orchestrator import manager
from .routes import experiments, runs, ws
from .sandbox.runner import get_backend

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("genesis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    recovered = manager.recover_interrupted_runs()

    backend = get_backend().name
    logger.info(
        "GENESIS ready — llm=%s (%s), sandbox=%s, db=%s%s",
        settings.resolved_provider,
        settings.llm_model if settings.resolved_provider != "offline" else "deterministic agents",
        backend,
        "sqlite" if settings.is_sqlite else "postgres",
        f", recovered {recovered} interrupted run(s)" if recovered else "",
    )
    if settings.resolved_provider == "offline":
        logger.warning(
            "No LLM key configured: agents run their deterministic strategies. "
            "Experiment metrics still come from real sandbox execution."
        )
    yield


app = FastAPI(
    title="GENESIS",
    description="Autonomous AI Research Laboratory",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Any loopback port during local dev, plus Railway deployments. Without
    # the 127.0.0.1 spelling a browser served from 127.0.0.1:3000 is blocked,
    # which surfaces in the UI as a confusing "backend unreachable".
    allow_origin_regex=r"^(https://.*\.up\.railway\.app|http://(localhost|127\.0\.0\.1):\d+)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router, tags=["research"])
app.include_router(experiments.router, tags=["experiments"])
app.include_router(ws.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/system/status", response_model=SystemStatusOut)
def system_status() -> SystemStatusOut:
    """What the system is actually using -- surfaced in the UI so the
    provenance of a run is never ambiguous."""
    return SystemStatusOut(
        llm_provider=settings.resolved_provider,
        llm_model=settings.llm_model if settings.resolved_provider != "offline" else "deterministic",
        sandbox_backend=get_backend().name,
        database="sqlite" if settings.is_sqlite else "postgres",
        arxiv_enabled=settings.enable_arxiv,
    )


@app.get("/system/corpus")
def corpus() -> dict[str, object]:
    """The curated offline literature corpus, for transparency."""
    return {
        "count": len(CURATED_CORPUS),
        "papers": [
            {"title": p.title, "authors": p.authors, "url": p.url, "published": p.published}
            for p in CURATED_CORPUS
        ],
    }
