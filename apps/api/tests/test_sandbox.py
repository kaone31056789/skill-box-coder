"""Sandbox security and result-handling tests.

These are the tests that matter most: the sandbox is the boundary between
AI-generated code and the host.
"""
from __future__ import annotations

import pytest

from genesis.sandbox.base import extract_error_summary, parse_result_payload
from genesis.sandbox.runner import execute

pytestmark = pytest.mark.sandbox


def test_successful_experiment_returns_real_metrics() -> None:
    code = """
import json
from genesis_data import load_dataset
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score

X_train, X_test, y_train, y_test, names = load_dataset(feature_set="base", seed=42)
model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=1).fit(X_train, y_train)
f1 = float(f1_score(y_test, model.predict(X_test)))
json.dump({"status": "success", "metrics": {"f1": f1}}, open("result.json", "w"))
"""
    result = execute(code, timeout=180)
    assert result.ok, result.error
    assert 0.0 < result.metrics["f1"] <= 1.0
    assert result.execution_time > 0


def test_network_access_is_blocked() -> None:
    code = """
import urllib.request
urllib.request.urlopen("http://example.com", timeout=5)
"""
    result = execute(code, timeout=60)
    assert not result.ok
    assert "network access is disabled" in (result.stderr + (result.error or ""))


def test_host_secrets_are_not_visible() -> None:
    """The sandbox env is scrubbed, so API keys never reach generated code."""
    code = """
import json, os
leaked = [k for k in os.environ if "KEY" in k.upper() or "DATABASE" in k.upper()]
json.dump({"status": "success", "metrics": {"leaked": float(len(leaked))}}, open("result.json", "w"))
"""
    result = execute(code, timeout=60)
    assert result.ok, result.error
    assert result.metrics["leaked"] == 0.0


def test_process_spawning_is_blocked() -> None:
    code = """
import subprocess
subprocess.run(["python", "-c", "print(1)"])
"""
    result = execute(code, timeout=60)
    assert not result.ok


def test_failure_captures_error_for_repair() -> None:
    code = 'raise ValueError("deliberate failure")'
    result = execute(code, timeout=60)
    assert not result.ok
    assert result.exit_code != 0
    assert "deliberate failure" in result.stderr
    assert result.error


def test_missing_result_file_is_a_failure() -> None:
    """Exiting cleanly without metrics must not count as success."""
    result = execute('print("no results written")', timeout=60)
    assert not result.ok
    assert "result.json" in (result.error or "")


def test_timeout_is_enforced() -> None:
    code = """
import time
time.sleep(30)
"""
    result = execute(code, timeout=5)
    assert result.status == "timeout"


# ------------------------------------------------------------- unit helpers
def test_parse_result_rejects_non_numeric_metrics() -> None:
    metrics, _, _, error = parse_result_payload('{"metrics": {"f1": "high", "p": null}}')
    assert error is not None
    assert metrics == {}


def test_parse_result_drops_nan_and_keeps_numbers() -> None:
    metrics, _, _, error = parse_result_payload('{"metrics": {"f1": 0.9, "bad": NaN}}')
    assert error is None
    assert metrics == {"f1": 0.9}


def test_parse_result_rejects_invalid_json() -> None:
    _, _, _, error = parse_result_payload("not json at all")
    assert error is not None


def test_extract_error_summary_finds_exception_line() -> None:
    stderr = 'Traceback (most recent call last):\n  File "x"\nValueError: bad shape (3, 4)'
    assert "ValueError: bad shape" in extract_error_summary(stderr)


def test_blas_thread_pools_are_bounded_to_the_allocation() -> None:
    """Unpinned BLAS threads sized themselves from the HOST core count and
    exhausted the memory cap in production ("OpenBLAS error: Memory allocation
    still failed after 10 retries"). They must track SANDBOX_CPUS instead --
    pinning to 1 would make the CPU setting meaningless.
    """
    import os as _os

    from genesis.config import get_settings
    from genesis.sandbox.runner import get_backend

    expected = getattr(get_backend(), "threads", 1)
    assert expected == max(1, int(get_settings().sandbox_cpus))

    code = """
import json, os
names = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
values = {n: int(os.environ[n]) for n in names}
assert len(set(values.values())) == 1, values
json.dump({"status": "success", "metrics": {"threads": float(values["OMP_NUM_THREADS"])}},
          open("result.json", "w"))
"""
    result = execute(code, timeout=90)
    assert result.ok, result.error
    assert result.metrics["threads"] == expected
    # The whole point: bounded by the allocation, not by the host.
    assert result.metrics["threads"] < (_os.cpu_count() or 2) or expected >= (_os.cpu_count() or 2)


def test_declared_primary_metric_never_pollutes_the_metrics() -> None:
    """Result metadata must sit beside the metrics, not inside them -- these
    keys would otherwise persist as Metric rows and render as measurements."""
    raw = (
        '{"status":"success","metrics":{"rmse":0.42,"r2":0.88},'
        '"primary_metric":"rmse","metric_direction":"minimize"}'
    )
    metrics, _, primary, error = parse_result_payload(raw)
    assert error is None
    assert set(metrics) == {"rmse", "r2"}
    assert not any(k.startswith("__") for k in metrics)
    assert primary == {"name": "rmse", "direction": "minimize"}


def test_primary_metric_is_ignored_when_it_names_nothing_measured() -> None:
    raw = '{"status":"success","metrics":{"f1":0.9},"primary_metric":"nonexistent"}'
    metrics, _, primary, error = parse_result_payload(raw)
    assert error is None
    assert primary is None
    assert set(metrics) == {"f1"}
