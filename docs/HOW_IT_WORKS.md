# How GENESIS works

A complete walkthrough: what the system does, how each piece works, and why it
is built the way it is.

---

## 1. What problem it solves

Ordinary AI tools answer questions. GENESIS *tests* them.

Given a computational research question, it runs the full scientific loop
without a human in it: read the literature, form competing hypotheses, pick the
most promising one, design an experiment, write the code, run that code for
real, measure what happened, decide whether the hypothesis held, and choose what
to try next — repeatedly, until it has an answer backed by measurements.

The distinction that matters: **an LLM decides what to test; executed code
decides what is true.** No metric in this system is ever produced by a language
model.

---

## 2. The loop

```
        ┌──────────────────── Research Question ────────────────────┐
        │                                                            │
        ▼                                                            │
   1. SCOUT ─────────► literature, concepts, research gaps            │
        │                                                            │
        ▼                                                            │
   2. SCIENTIST ─────► 3 competing hypotheses                         │
        │                                                            │
        ▼                                                            │
   3. PI ────────────► picks one + records WHY (evidence, confidence) │
        │                                                            │
        ▼                                                            │
   4. EXPERIMENTALIST► dataset, method, variables, metrics, split     │
        │                                                            │
        ▼                                                            │
   5. ENGINEER ──────► executable Python                             │
        │                                                            │
        ▼                                                            │
   6. SANDBOX ───────► real execution → result.json                  │
        │                     │                                      │
        │                     └── failed? ──► ENGINEER repairs (×2)  │
        ▼                                                            │
   7. ANALYST ───────► supported / not supported, vs. baseline        │
        │                                                            │
        ▼                                                            │
   8. PI ────────────► next experiment, or conclude ─────────────────┘
```

Each pass through the loop is one experiment. The run ends when the compute
budget is spent or the PI decides nothing further is worth testing.

---

## 3. The six agents

Each agent is a small Python class with one job. All of them have a
**deterministic fallback**, so the loop completes even if the model provider is
down — what degrades is the *reasoning*, never the *measurement*.

### SCOUT — `agents/scout.py`
Searches arXiv live using keywords extracted from the question. If arXiv is
slow, rate-limited, or unreachable, it falls back to a curated corpus of 12 real
papers in the demo domain — and labels the source `curated` so the UI never
implies a live search happened. It then extracts concepts, methods, and testable
research gaps.

### SCIENTIST — `agents/scientist.py`
Generates competing, falsifiable hypotheses. Two important behaviours:

- It is shown every experiment already run **with its measured numbers**, and
  told to target the error mode those numbers reveal.
- It is shown the set of already-tested configurations and refuses to re-propose
  them, so the lab never burns compute repeating itself.

### EXPERIMENTALIST — `agents/experimentalist.py`
Turns a hypothesis into a reproducible specification: dataset, baseline,
manipulated variables, hyperparameters, metrics, and train/test split. It is
constrained so it cannot silently change *what* is being tested — the hypothesis
owns the method; the designer only fills in the details.

### ENGINEER — `agents/engineer.py`
Writes the actual experiment program. On failure it receives the error, the
stderr tail, the failing code, and the spec, and attempts a repair — **twice**.
If both repairs fail, the experiment is marked failed and the PI decides what to
do about it. This failure/repair path is real, not staged.

### ANALYST — `agents/analyst.py`
Interprets the measured metrics against the hypothesis and the baseline. The
support verdict is **computed arithmetically**, not written by the model: an F1
improvement below the noise floor (0.01 on this test split) is not an
improvement, regardless of how the narrative reads. The LLM supplies the prose
around a verdict it cannot change.

### PRINCIPAL INVESTIGATOR — `agents/pi.py`
Owns strategy: which hypothesis to test next, when to stop, and why. Every
decision is stored as a structured record — decision, evidence bullets citing
actual numbers, expected value, estimated cost, confidence — which is what the
**WHY?** button renders. Decision factors and conclusions only; no hidden
reasoning is exposed.

---

## 4. Where the numbers come from

This is the part worth understanding in detail, because it is what separates
GENESIS from a demo that prints plausible figures.

1. The Engineer produces a Python program.
2. That program is written to a throwaway directory along with a trusted
   bootstrap and (for anomaly questions) the dataset module.
3. A **separate process** runs it, with the environment scrubbed and the network
   disabled.
4. The program must write `result.json`:

   ```json
   {"status": "success",
    "metrics": {"f1": 0.9842, "precision": 0.982, "false_positive_rate": 0.0024},
    "artifacts": [], "execution_time": 3.5}
   ```

5. GENESIS reads that file, coerces every metric to a float, and **discards
   anything non-numeric, NaN, or infinite**.
6. If the file is missing, unparseable, or has no numeric metrics, the run is a
   **failure** — a clean exit is not enough.

There is no path by which a model-authored string becomes a displayed metric.
`sandbox/base.py::parse_result_payload` is the only entry point, and it accepts
numbers only.

---

## 5. Two experiment modes (how it handles any question)

The shipped dataset is network traffic. Most research questions are not.

A **deterministic router** (`agents/strategy.py::is_builtin_anomaly_question`)
classifies the question and forces the mode:

| Mode | When | What the experiment does |
|---|---|---|
| `builtin_anomaly` | Question is about network anomaly / intrusion detection | Uses the shipped flow dataset via `from genesis_data import load_dataset` |
| `self_contained` | Everything else | Generates its own deterministic synthetic dataset with numpy (seed 42) that embodies the phenomenon under test |

**Why a keyword rule rather than an LLM call?** Because we tried the LLM way and
it failed. Asking a feature-scaling question produced a correct, general
hypothesis — but the model left `dataset_mode` at its schema default, so the
experiment silently ran against network traffic. A defaulted enum is not
something to trust a model to override. The router is free, deterministic, and
covered by regression tests.

The Scientist is also shown **only** the capability envelope its question routes
to. Describing the network dataset to a general question was biasing the model
into reframing the problem as anomaly detection ("...vs tree-based *anomaly
detection*"). An irrelevant dataset description is pure downside.

---

## 6. The sandbox

AI-generated code is unreviewed code. It is treated as untrusted.

Two backends, selected automatically:

**`DockerSandbox`** — the real boundary. `--network none`, capped CPU / memory /
PIDs, read-only root filesystem, all capabilities dropped, no privilege
escalation, non-root user. The Docker socket is never exposed.

**`SubprocessSandbox`** — the fallback where Docker is unavailable (Windows dev,
Railway). Throwaway working directory, environment scrubbed to an allowlist,
`socket` / `subprocess` / `os.exec*` neutered, hard timeout with process-tree
kill. This is **defence in depth, not a boundary** — in-process patches can be
undone by code running in that same process. It reliably stops the accidental
and the casual; it is not a claim of containment against an adversary.

Set `SANDBOX_BACKEND=docker` to refuse to start rather than silently downgrade.
`/system/status` always reports which backend is live.

### A subtle bug worth knowing about

The bootstrap originally blocked process spawning by replacing
`subprocess.Popen` with a function. That broke *every* scikit-learn import,
because `asyncio.windows_utils` does `class Popen(subprocess.Popen)` — and you
cannot subclass a function. joblib imports asyncio, sklearn imports joblib. The
fix was to block it with a *subclass* that raises on instantiation, keeping it a
class. Blocking mechanisms have to preserve the shape of what they replace.

---

## 7. Why the demo dataset is honest

A synthetic dataset can be rigged to produce any conclusion. This one is
deliberately built so it cannot be:

- **Port scans are invisible per-flow.** Each individual scan flow looks like an
  ordinary short DNS probe. They only become detectable in a time window, via
  the count of distinct destination ports per source. A per-flow model is
  *structurally* blind to them.
- **Benign confusers.** Monitoring sweeps, scheduled backups, and flash crowds
  are labelled **normal** but mimic attacks per-flow. They are why false
  positives exist, and each is separable only by a windowed feature (a flash
  crowd has high source entropy; a DDoS burst collapses it).
- **Measurement jitter.** Without it, a supervised model memorises the exact
  generative signature and scores a meaningless F1 = 1.0. That actually happened
  during development, and the jitter was added to fix it.

So "temporal features help" is something the system **measures**, not something
the dataset was built to announce. Measured spread:

| Approach | Features | F1 | FPR |
|---|---|---|---|
| IsolationForest | base | 0.364 | 4.27% |
| RandomForest | base | 0.848 | 1.98% |
| RandomForest | temporal | 0.984 | 0.24% |

---

## 8. Architecture

```
apps/web     Next.js · TypeScript (strict) · Tailwind · React Flow · Recharts
   │  REST + WebSocket
   ▼
apps/api     FastAPI
   ├── routes/        HTTP + WS endpoints
   ├── orchestrator/  the research loop + state machine
   ├── agents/        the six agents, LLM client, codegen, domain router
   ├── sandbox/       docker + subprocess backends
   ├── literature/    arXiv + curated corpus
   ├── models.py      SQLAlchemy schema
   └── graph.py       research-graph construction
   ▼
PostgreSQL (or SQLite locally)
```

### Threading model

The orchestrator runs in a **background thread** using plain synchronous
SQLAlchemy. It publishes events onto the API's asyncio loop with
`loop.call_soon_threadsafe`, which fans them out to WebSocket subscribers.

This avoids async-DB friction entirely — the loop does ordinary blocking DB
calls — while keeping the UI live. Subscriber queues are bounded; a slow client
drops its oldest events rather than growing memory without limit.

### State machine

```
CREATED → RESEARCHING → HYPOTHESIS_GENERATION → EXPERIMENT_DESIGN
        → CODE_GENERATION → RUNNING → ANALYZING → DECISION → (loop)
        → COMPLETED        (also: PAUSED, FAILED)
```

Every transition is persisted. Pause and stop are **cooperative**: the
orchestrator checks the flags at phase boundaries rather than being killed
mid-experiment. If the backend restarts, interrupted runs are recovered into
`PAUSED` so they can be resumed with all prior experiments intact.

### The research graph

Built from typed nodes (question, hypothesis, experiment, success result,
failed result) and typed edges (`generated_from`, `tested_by`, `improved_from`,
`derived_from`, `produced`). Laid out left-to-right in four columns — a
deterministic layered layout, no layout engine dependency. The current
experiment pulses; the best one is outlined in green.

The frontend keeps the socket payloads small: agent events stream over the
WebSocket, but any *structural* change sends a `graph_update` nudge and the
client re-fetches the authoritative record over REST. The database stays the
single source of truth.

---

## 9. Model configuration and failover

```
LLM_MODEL=deepseek/deepseek-v4-flash-0731
LLM_FALLBACK_MODELS=stealth/ox-alpha,nvidia/nemotron-3-super-120b-a12b
```

Models are tried left to right. A model that errors, is rate-limited, or keeps
returning output that fails schema validation is abandoned in favour of the next
one. Measured latency per structured call:

| Model | Latency |
|---|---|
| deepseek/deepseek-v4-flash-0731 | ~16s |
| nvidia/nemotron-3-super-120b-a12b | ~26s |
| stealth/ox-alpha | ~76s |

A full run makes roughly 16 LLM calls, so model latency — not compute —
dominates the wall clock. Experiments themselves take 3–8 seconds.

**Note:** SDK-level retries are disabled (`max_retries=0`). They multiplied the
120s timeout, letting one slow model stall a whole run for minutes before
failover. `complete_json` already handles retry and failover.

### Structured output validation

Every agent response is validated against a Pydantic schema before it touches
the database. Invalid JSON or a schema violation is fed back to the model with
the error text and retried; after the attempts are exhausted the chain moves to
the next model; after that the agent falls back to its deterministic path.
Unvalidated model output is never persisted.

---

## 10. Operating it

```bash
# check the model config before demoing
apps/api/.venv/Scripts/python.exe apps/api/scripts/check_llm.py

# run the tests
cd apps/api && .venv/Scripts/python.exe -m pytest -q

# start
cd apps/api && .venv/Scripts/python.exe -m uvicorn genesis.main:app --host 0.0.0.0 --port 8000
cd apps/web && npm run dev
```

### Controls in the UI

| Control | What it does |
|---|---|
| Start / Pause / Resume / Stop | Cooperative run control at phase boundaries |
| **Why?** | Every PI decision with its evidence and confidence |
| **View Code** | The exact generated program, plus stdout and stderr |
| **Literature** | Papers found, with relevance and source (arxiv vs curated) |
| **Inject Hypothesis** | Add your own — GENESIS prioritises it for the next experiment |
| Graph / Compare | Research graph, or the metric comparison table and charts |

### Gotchas

- Use `127.0.0.1`, not `localhost`, in `NEXT_PUBLIC_API_URL` on Windows —
  browsers try IPv6 `::1` first while uvicorn binds IPv4 only.
- The API must allow your browser's exact origin; a CORS block looks identical
  to "backend down".
- `NEXT_PUBLIC_*` values are baked in at build time — change one, rebuild.

---

## 11. What it cannot do

Stated plainly, because knowing the edges is part of understanding the system:

- The sandbox has **numpy, scipy and scikit-learn only**, with a 90-second
  budget. It can genuinely research classical ML, statistics, feature
  engineering, model comparison, thresholding, and class imbalance. It cannot
  research anything requiring deep-learning frameworks, real-world datasets, or
  large compute.
- With no LLM configured, the deterministic ladder only covers the
  anomaly-detection domain. Non-anomaly questions need a working model provider.
- The subprocess sandbox is not a containment boundary against a determined
  adversary. Use the Docker backend for untrusted multi-tenant workloads.
- Self-contained experiments are authored from scratch by the model, so they
  carry more risk than the templated anomaly experiments. The repair loop gets
  two attempts; after that the experiment is marked failed.
