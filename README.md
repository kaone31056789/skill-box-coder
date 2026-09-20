# GENESIS — Autonomous AI Research Laboratory🔬

**From question to experiment to discovery.**

GENESIS takes a computational research question and closes the loop on it without
a human in the middle: it searches the literature, generates competing
hypotheses, designs an experiment, writes the experiment code, executes that
code in an isolated sandbox, analyses the **real** metrics that come back,
compares them against previous runs, and decides what to try next.

It is not a chatbot. There is no chat window.

```
Research Question → Literature → Hypotheses → Experiment Design → Code Generation
       ↑                                                                  ↓
Next Experiment ← Hypothesis Evaluation ← Result Analysis ← Sandbox Execution
```

## The one thing that matters

**Every metric in the UI is computed by code that actually ran.** The agents
decide *what* to test and *why*; they never decide what the numbers are. If the
LLM is unreachable the agents fall back to deterministic strategies — and the
metrics still come from real execution.

A representative run (network anomaly detection, 3 experiments, ~13s of compute):

| Experiment | Approach | Features | F1 | FPR |
|---|---|---|---|---|
| EXP-001 | isolation_forest | base | 0.364 | 4.27% |
| EXP-002 | random_forest | base | 0.848 | 1.98% |
| EXP-003 | random_forest | temporal | **0.984** | **0.24%** |

F1 +170%, false-positive rate −94%. Nothing above is hard-coded; re-run it and
the ranking is re-derived from execution.

---

## Quick start

Requires **Python 3.12+** and **Node 20+**. Docker is optional.

```bash
# 1. Configure
cp .env.example .env
#    Put your OpenRouter key in .env:
#      OPENROUTER_API_KEY=sk-or-v1-...
#      LLM_MODEL=stealth/ox-alpha

# 2. Backend
cd apps/api
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt                   # macOS / Linux
.venv/Scripts/python.exe -m uvicorn genesis.main:app --host 0.0.0.0 --port 8000

# 3. Frontend (separate terminal)
cd apps/web
npm install
npm run dev
```

Open **http://localhost:3000**.

Verify the LLM path before demoing:

```bash
apps/api/.venv/Scripts/python.exe apps/api/scripts/check_llm.py
```

### Docker Compose (Postgres + containerised sandbox)

```bash
docker compose -f infrastructure/docker-compose.yml --profile build-only build sandbox
docker compose -f infrastructure/docker-compose.yml up
```

---

## Gotchas worth knowing

These cost real debugging time; they are documented so they cost you none.

- **Use `127.0.0.1`, not `localhost`, in `NEXT_PUBLIC_API_URL` on Windows.**
  Browsers resolve `localhost` to IPv6 `::1` first, while uvicorn binds IPv4
  only — you get a connection refused that looks like the backend being down.
- **The API must allow your browser's exact origin.** `CORS_ORIGINS` ships with
  both `http://localhost:3000` and `http://127.0.0.1:3000`. A CORS block also
  surfaces as "cannot reach the API".
- **`NEXT_PUBLIC_*` variables are baked in at build time.** Change one and you
  must rebuild the frontend.
- **Model latency dominates the demo clock**, not compute. Experiments run in
  ~3–8s each; a single LLM call can take 25–50s. Budget accordingly, and see
  *Demo mode* below.

---

## The six agents

| Agent | Responsibility |
|---|---|
| **Scout** | Searches arXiv (live) with a curated offline corpus as fallback; extracts concepts, methods and research gaps. |
| **Scientist** | Generates competing, falsifiable hypotheses grounded in measured results. Will not restate something already tested. |
| **Experimentalist** | Turns a hypothesis into a reproducible spec: dataset, baseline, variables, parameters, metrics, split. |
| **Engineer** | Writes executable Python. On failure it receives the error, stderr and previous code, and repairs — up to 2 attempts. |
| **Analyst** | Interprets the measured metrics against the hypothesis. The support verdict is arithmetic, not editorial. |
| **Principal Investigator** | Owns strategy: what to run next, when to stop, and *why*. Every decision carries structured evidence and a confidence score. |

Each agent has a deterministic fallback, so the loop completes even with no LLM
configured. What degrades is the *reasoning*, never the *measurement*.

## Two experiment modes

GENESIS is not limited to its demo domain:

- **`builtin_anomaly`** — for network anomaly detection questions. Uses the
  shipped deterministic flow dataset (`experiments/anomaly_detection/`).
- **`self_contained`** — for any other domain. The Engineer generates a
  deterministic synthetic dataset inside the experiment with numpy, then trains
  and evaluates on it.

The Scientist picks the mode from the research question.

## Why the demo dataset is honest

The synthetic network data is built so different approaches *genuinely* differ:

- **Port scans** are deliberately invisible per-flow — each scan flow looks like
  an ordinary DNS probe. They only appear in a time window, via distinct
  destination ports per source.
- **Benign confusers** (monitoring sweeps, scheduled backups, flash crowds) are
  labelled normal but mimic attacks per-flow. They are the reason false
  positives exist, and each is separable only via a windowed feature.
- **Measurement jitter** prevents a supervised model from memorising the exact
  generative signature and scoring a meaningless F1 = 1.0.

So "temporal features help" is a finding the system *measures*, not one the
dataset was rigged to produce.

---

## Security model

AI-generated code is treated as untrusted. See [docs/SECURITY.md](docs/SECURITY.md).

Two backends, auto-selected:

- **`DockerSandbox`** (preferred) — the real boundary: `--network none`, capped
  CPU/memory/PIDs, read-only root filesystem, all capabilities dropped,
  non-root user. The Docker socket is never exposed to the container.
- **`SubprocessSandbox`** (fallback, used where Docker is unavailable — local
  Windows dev, Railway) — throwaway working directory, scrubbed environment,
  network and process spawning blocked, hard timeout. **Defence in depth, not a
  hard boundary.**

Verified by tests: network blocked, zero host secrets visible, process spawning
blocked, timeouts enforced, and a clean exit without `result.json` counts as
failure rather than success.

---

## Architecture

```
apps/web    Next.js 16 · TypeScript (strict) · Tailwind · React Flow · Recharts
apps/api    FastAPI · Pydantic · SQLAlchemy
              genesis/agents/        the six agents + LLM client + codegen
              genesis/orchestrator/  research loop and state machine
              genesis/sandbox/       docker + subprocess backends
              genesis/literature/    arXiv + curated corpus
              genesis/routes/        REST + WebSocket
experiments/anomaly_detection/  deterministic dataset (shipped into the sandbox)
sandbox/    bootstrap + container image for untrusted code
infrastructure/  docker-compose
```

The orchestrator runs in a **background thread** using plain synchronous
SQLAlchemy, publishing to the WebSocket bus via `call_soon_threadsafe`. This
avoids async-DB friction while keeping the UI live.

State machine: `CREATED → RESEARCHING → HYPOTHESIS_GENERATION →
EXPERIMENT_DESIGN → CODE_GENERATION → RUNNING → ANALYZING → DECISION → …
→ COMPLETED`, with `PAUSED` / `FAILED`. Everything is persisted, so a restarted
backend recovers interrupted runs into `PAUSED` for resumption.

## API

```
POST   /research-runs                    GET /research-runs/{id}
POST   /research-runs/{id}/start|pause|resume|stop
GET    /research-runs/{id}/events        ?after=<seq>
GET    /research-runs/{id}/graph         /comparison /hypotheses /experiments /papers /decisions
POST   /hypotheses                       inject a hypothesis for GENESIS to evaluate
GET    /experiments/{id}                 /results /code
POST   /experiments/{id}/run             re-execute in the sandbox
WS     /ws/research-runs/{id}
GET    /system/status                    which LLM / sandbox / DB is actually in use
```

## Tests

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest -q
```

51 tests: sandbox security and result handling, dataset determinism and
separability, code generation across all approach × feature-set combinations,
agent output validation, and the API contract.

## Deployment (Railway)

The API deploys from `apps/api/Dockerfile`; `DATABASE_URL` is injected and
normalised to `postgresql+psycopg://` automatically. Set `OPENROUTER_API_KEY`,
`LLM_MODEL` and `CORS_ORIGINS` in the service variables, and point the web
service at the API with `NEXT_PUBLIC_API_URL`.

Railway has no Docker-in-Docker, so the subprocess sandbox is the production
path there. For untrusted multi-tenant use, run the Docker backend on a host
that supports it.

## Demo mode

"Watch Demo" runs the network anomaly question with a fixed 3-experiment budget
on the deterministic dataset. Literature may be served from the curated corpus
and the data is deterministic — but **the experiments really execute and the
metrics are really measured**.

For the fastest, most reliable demo, leave `LLM_PROVIDER=offline`: the agents
use their deterministic strategies, the whole run takes ~13 seconds, and the
measured results are identical. Configure a key when you want the reasoning
itself — hypotheses, decisions, explanations — to respond to an arbitrary
question.
