# Security model

GENESIS generates Python with a language model and then executes it. That code
is **untrusted** — not because the model is assumed malicious, but because
generated code is unreviewed code, and an unreviewed program that can reach the
filesystem, the network, or the process environment is a liability regardless of
intent.

## Threat model

| Concern | Handling |
|---|---|
| Generated code reads host secrets | Environment is scrubbed to an allowlist before the process starts; anything matching `KEY`/`SECRET`/`TOKEN`/`PASSWORD`/`DATABASE`/`URL` is dropped again inside the bootstrap. |
| Generated code exfiltrates data | Network is disabled. Under Docker the container runs `--network none`; in the subprocess backend `socket.socket`, `create_connection` and `getaddrinfo` are replaced with raisers. |
| Generated code installs packages / shells out | `subprocess.Popen/run/call/check_output`, `os.system`, `exec*`, `spawn*` and `fork` are blocked. |
| Generated code reads or writes host files | Under Docker: read-only root filesystem, a single writable bind mount that is deleted afterwards. Under subprocess: a throwaway temp working directory. |
| Generated code never terminates | Hard wall-clock timeout with process-tree kill; CPU and memory rlimits on POSIX; cgroup limits under Docker. |
| Generated code escalates privileges | Docker: `--cap-drop ALL`, `--security-opt no-new-privileges`, non-root user `1000:1000`. |
| Docker socket abuse | The socket is never mounted into the sandbox container. |
| Model returns malformed or hostile structured output | Every agent response is validated against a Pydantic schema before it touches the database; invalid output is fed back and retried, then rejected. |
| Model fabricates results | Metrics are only ever read from `result.json` written by the executed process, coerced to float, with non-numeric, NaN and infinite values discarded. A clean exit without that file is a **failure**, not a success. |

## The two backends are not equivalent

**`DockerSandbox` is the security boundary.** It is selected automatically
whenever a Docker daemon and the `genesis-sandbox` image are both available.

**`SubprocessSandbox` is defence in depth, not a boundary.** It exists so the
system runs where Docker is unavailable — local Windows development, and
Railway, which has no Docker-in-Docker. Its protections are in-process monkey
patches, and code executing arbitrary Python in the same interpreter can undo
in-process patches. It reliably stops the accidental and the casual (a script
that tries to `pip install`, phone home, or read the environment); it should not
be relied on against a determined adversary.

Force the boundary explicitly with `SANDBOX_BACKEND=docker` — GENESIS will then
refuse to start rather than silently downgrade:

```
SANDBOX_BACKEND=docker was requested but the Docker daemon or the image
'genesis-sandbox:latest' is unavailable.
```

The UI always shows which backend is live (`/system/status`), so the provenance
of a run is never ambiguous.

## Secrets

- No key is ever hard-coded. Everything comes from the environment.
- `.env` is gitignored; only `.env.example` is committed.
- Keys are never exposed to the frontend. The browser talks only to the GENESIS
  API, which holds the provider credentials server-side.
- `NEXT_PUBLIC_*` variables are public by construction — only the API base URL
  lives there.

## What is deliberately not claimed

- The subprocess backend does not contain a hostile actor. Documented above.
- The curated literature corpus is clearly labelled `curated` in the API and UI
  so a fallback is never presented as a live search result.
- Deterministic agent fallbacks are labelled as such; `/system/status` reports
  `offline` when no model is configured, and the run record stores the provider
  that was actually used.

## Verified by tests

`apps/api/tests/test_sandbox.py` asserts the controls rather than assuming them:

- network access blocked
- zero host secrets visible to generated code
- process spawning blocked
- timeouts enforced
- failures captured with usable errors for the repair loop
- missing / malformed / non-numeric `result.json` treated as failure
