"""Sandbox contract shared by every execution backend.

AI-generated experiment code is UNTRUSTED. Every backend must guarantee:
  * a scratch working directory the code cannot escape by relative path
  * no inherited environment secrets
  * a hard wall-clock timeout
  * captured stdout / stderr / exit code / execution time
  * a parsed metrics payload, or an explicit failure
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Called with each stdout line as the experiment produces it.
OutputCallback = Callable[[str], None]

# The generated experiment must write this file. It is the only channel through
# which results enter the system -- stdout is captured for display only.
RESULT_FILENAME = "result.json"

# Environment variables allowed through to the sandbox. Everything else --
# including OPENROUTER_API_KEY, DATABASE_URL and the rest of the host env -- is
# stripped.
ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL")

_MAX_CAPTURE_CHARS = 20_000


@dataclass
class SandboxResult:
    """Outcome of one sandbox execution."""

    status: str  # "success" | "failed" | "timeout" | "error"
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: list[dict[str, str]] = field(default_factory=list)
    # Which metric the lab should rank this experiment by, as declared by the
    # experiment itself. None means "fall back to the domain default".
    primary_metric: str | None = None
    metric_direction: str = "maximize"
    execution_time: float = 0.0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    backend: str = "unknown"

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "primary_metric": self.primary_metric,
            "metric_direction": self.metric_direction,
            "execution_time": round(self.execution_time, 3),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "backend": self.backend,
        }


def truncate(text: str, limit: int = _MAX_CAPTURE_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - limit
    return f"{text[:half]}\n...[{omitted} chars omitted]...\n{text[-half:]}"


def extract_error_summary(stderr: str) -> str:
    """Pull the final traceback line out of stderr for the Engineer's repair prompt."""
    if not stderr.strip():
        return "Process failed with no stderr output."
    lines = [ln.rstrip() for ln in stderr.strip().splitlines() if ln.strip()]
    for line in reversed(lines):
        if re.match(r"^\w[\w.]*(Error|Exception|Warning)\b", line) or ":" in line:
            return line[:600]
    return lines[-1][:600]


# Generated code names its metrics itself, and an LLM-written experiment will
# happily emit `auc_roc` where the deterministic template emits `roc_auc`. The
# measurement is identical, so the lab canonicalises the name rather than
# showing a populated metric as an empty cell.
_METRIC_ALIASES = {
    "auc": "roc_auc",
    "auc_roc": "roc_auc",
    "roc_auc_score": "roc_auc",
    "auroc": "roc_auc",
    "f1_score": "f1",
    "f1score": "f1",
    "fscore": "f1",
    "precision_score": "precision",
    "recall_score": "recall",
    "sensitivity": "recall",
    "tpr": "recall",
    "true_positive_rate": "recall",
    "accuracy_score": "accuracy",
    "acc": "accuracy",
    "fpr": "false_positive_rate",
    "false_alarm_rate": "false_positive_rate",
    "pr_auc": "average_precision",
    "auc_pr": "average_precision",
    "average_precision_score": "average_precision",
    "tp": "true_positives",
    "fp": "false_positives",
    "fn": "false_negatives",
    "tn": "true_negatives",
}


def canonical_metric_name(name: str) -> str:
    """Map a metric alias onto the name the rest of the lab ranks and renders."""
    return _METRIC_ALIASES.get(name.strip().lower(), name)


def parse_result_payload(
    raw: str,
) -> tuple[dict[str, float], list[dict[str, str]], dict[str, str] | None, str | None]:
    """Validate a result.json payload emitted by generated code.

    Returns ``(metrics, artifacts, primary, error)``. Metrics are coerced to
    float and non-numeric entries are dropped rather than trusted. ``primary``
    is ``{"name": ..., "direction": ...}`` when the experiment declared how it
    should be ranked, otherwise ``None`` -- deliberately kept out of ``metrics``
    so it is never mistaken for a measurement.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, [], None, f"result.json is not valid JSON: {exc}"

    if not isinstance(payload, dict):
        return {}, [], None, "result.json must contain a JSON object"

    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict):
        return {}, [], None, "result.json is missing a 'metrics' object"

    metrics: dict[str, float] = {}
    for key, value in raw_metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            continue
        name = canonical_metric_name(str(key))
        # An explicit canonical name always wins over an alias for the same
        # measurement, so a payload carrying both cannot lose the real one.
        if name in metrics and str(key) != name:
            continue
        metrics[name] = float(value)

    if not metrics:
        return {}, [], None, "result.json contained no numeric metrics"

    # A self-contained experiment declares what it should be ranked by; the lab
    # cannot assume every domain reports F1. Only honour a name that actually
    # exists in the measured metrics.
    primary: dict[str, str] | None = None
    declared = payload.get("primary_metric")
    # Canonicalised the same way the metrics were, or an experiment declaring
    # `auc_roc` would fail this membership test and silently lose its ranking.
    declared = canonical_metric_name(declared) if isinstance(declared, str) else None
    if declared is not None and declared in metrics:
        direction = payload.get("metric_direction")
        primary = {
            "name": declared,
            "direction": "minimize" if direction == "minimize" else "maximize",
        }

    artifacts: list[dict[str, str]] = []
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list):
        for item in raw_artifacts[:10]:
            if isinstance(item, dict) and "name" in item:
                artifacts.append(
                    {
                        "name": str(item["name"])[:255],
                        "kind": str(item.get("kind", "json"))[:40],
                        "content": str(item.get("content", ""))[:100_000],
                    }
                )
    return metrics, artifacts, primary, None


class SandboxBackend:
    """Interface implemented by DockerSandbox and SubprocessSandbox."""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def run(
        self,
        code: str,
        support_files: dict[str, str],
        timeout: int,
        on_output: OutputCallback | None = None,
    ) -> SandboxResult:
        raise NotImplementedError
