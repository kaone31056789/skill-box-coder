# Model routing

GENESIS makes six different kinds of model call, and they do not want the same
model. Code generation is long-form and needs a competent coder; hypothesis and
decision calls are short, schema-bound, and reward speed. One model for all six
means paying the slowest common denominator on every step.

So each agent has its own **route**: an ordered chain tried left to right, with
a free model at the end so a run degrades to zero cost rather than failing when
a paid provider is rate limited.

## Measured

Benchmarked on this project's real workload — a `HypothesisSet` call (3
hypotheses against the Pydantic schema) and a `GeneratedCode` call (a complete
self-contained experiment). Times are end-to-end including schema validation.

| Model | Hypotheses | Code | Input $/M | Verdict |
|---|---|---|---|---|
| `deepseek/deepseek-v4-flash-0731` | **11.0s** | **21.3s** | 0.08 | Fastest and most reliable on both |
| `qwen/qwen3.7-flash` | 14.5s | 47.1s | 0.03 | Great for short calls, slow at code |
| `nvidia/nemotron-3-super-120b-a12b:free` | 28.0s | 29.2s | **free** | Solid free fallback |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 30.5s | 44.6s | **free** | Free, strongest judgement |
| `openai/gpt-oss-120b` | 39.6s | 48.0s | 0.03 | Works, no reason to prefer it |
| `stealth/ox-alpha` | 32.9s | **fails** | — | See below |
| `nvidia/nemotron-3-nano-30b-a3b:free` | **fails** | — | free | Cannot hold the schema |
| `google/gemma-4-31b-it:free` | 429 | — | free | Rate limited on the shared pool |

### On `stealth/ox-alpha`

It handles hypothesis generation (32.9s — usable but ~3× slower than deepseek)
and **consistently fails code generation**: it does not return a program that
satisfies the `GeneratedCode` schema. It is therefore excluded from the
`engineer` route by default. It remains available and can be set as any other
route's primary if you want it.

This is a measurement on this specific workload — long structured code inside a
JSON envelope — not a general statement about the model.

## Default routes

| Agent | Route |
|---|---|
| `scout` | qwen3.7-flash → deepseek-v4-flash → nemotron-super:free → nemotron-ultra:free |
| `scientist` | deepseek-v4-flash → qwen3.7-flash → nemotron-super:free → nemotron-ultra:free |
| `experimentalist` | deepseek-v4-flash → qwen3.7-flash → nemotron-super:free → nemotron-ultra:free |
| `engineer` | deepseek-v4-flash → nemotron-super:free → nemotron-ultra:free |
| `analyst` | deepseek-v4-flash → qwen3.7-flash → nemotron-super:free → nemotron-ultra:free |
| `pi` | deepseek-v4-flash → nemotron-ultra:free → nemotron-super:free |

Scout gets the cheapest capable model because it only summarises abstracts. The
PI gets the largest free model as its second opinion because its job is
judgement over evidence.

## Overriding

Any route can be replaced from the environment with a comma-separated chain:

```bash
LLM_ROUTE_ENGINEER=deepseek/deepseek-v4-flash-0731,nvidia/nemotron-3-super-120b-a12b:free
LLM_ROUTE_PI=stealth/ox-alpha
LLM_ROUTE_SCOUT=qwen/qwen3.7-flash
```

`LLM_MODEL` and `LLM_FALLBACK_MODELS` are appended to every resolved chain as a
last resort, so no task can end up with nothing to try.

## Running it entirely free

```bash
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
LLM_FALLBACK_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free
LLM_ROUTE_SCOUT=
LLM_ROUTE_SCIENTIST=
LLM_ROUTE_EXPERIMENTALIST=
LLM_ROUTE_ENGINEER=
LLM_ROUTE_ANALYST=
LLM_ROUTE_PI=
```

Clearing the routes makes every agent fall through to `LLM_MODEL`. Expect a run
to take roughly twice as long; the measured results are unaffected, because
metrics come from sandbox execution rather than from the model.

## Reasoning budget

`LLM_REASONING_EFFORT` (default `low`) maps to OpenRouter's unified reasoning
control. This matters: with no cap, a reasoning model deliberated for **359
seconds** on a single code-generation call. Constraining it, plus a
task-appropriate token budget, brought the same call to ~21s.

Set `medium` or `high` if you want richer hypotheses and can afford the latency,
or `none` to disable reasoning entirely on models that support it.

## Re-running the benchmark

The routes above are measurements, not opinions — re-measure when providers
change:

```bash
apps/api/.venv/Scripts/python.exe apps/api/scripts/bench_models.py
```
