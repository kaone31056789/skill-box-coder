"""API contract tests against an isolated SQLite database."""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["LLM_PROVIDER"] = "offline"

from fastapi.testclient import TestClient  # noqa: E402

from genesis.db import init_db, session_scope  # noqa: E402
from genesis.graph import build_comparison, build_graph  # noqa: E402
from genesis.main import app  # noqa: E402
from genesis.models import (  # noqa: E402
    Experiment,
    ExperimentStatus,
    Metric,
    ResearchRun,
)

QUESTION = "Can we improve network anomaly detection while reducing false positives?"


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def run_id(client) -> str:
    response = client.post("/research-runs", json={"question": QUESTION, "max_experiments": 2})
    assert response.status_code == 201
    return response.json()["id"]


def test_health_and_status(client) -> None:
    assert client.get("/health").json()["status"] == "ok"
    status = client.get("/system/status").json()
    assert status["llm_provider"] == "offline"
    assert status["sandbox_backend"] in ("docker", "subprocess")


def test_create_and_fetch_run(client, run_id: str) -> None:
    detail = client.get(f"/research-runs/{run_id}").json()
    assert detail["state"] == "CREATED"
    assert detail["question"] == QUESTION
    assert detail["experiments"] == []
    assert detail["is_running"] is False


def test_unknown_run_returns_404(client) -> None:
    assert client.get("/research-runs/does-not-exist").status_code == 404


def test_question_validation_rejects_empty(client) -> None:
    assert client.post("/research-runs", json={"question": "hi"}).status_code == 422


def test_max_experiments_is_bounded(client) -> None:
    assert client.post(
        "/research-runs", json={"question": QUESTION, "max_experiments": 999}
    ).status_code == 422


def test_inject_hypothesis(client, run_id: str) -> None:
    response = client.post(
        "/hypotheses",
        json={
            "run_id": run_id,
            "title": "Temporal features reduce false positives",
            "approach": "random_forest",
            "feature_set": "temporal",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "user"
    assert body["status"] == "PROPOSED"

    hypotheses = client.get(f"/research-runs/{run_id}/hypotheses").json()
    assert len(hypotheses) == 1


def test_pause_stop_are_idempotent(client, run_id: str) -> None:
    assert client.post(f"/research-runs/{run_id}/pause").json()["state"] in {"CREATED", "PAUSED"}
    assert client.post(f"/research-runs/{run_id}/stop").status_code == 200


def test_graph_and_comparison_are_empty_before_running(client, run_id: str) -> None:
    graph = client.get(f"/research-runs/{run_id}/graph").json()
    assert len(graph["nodes"]) == 1  # the question node
    assert graph["edges"] == []

    comparison = client.get(f"/research-runs/{run_id}/comparison").json()
    assert comparison["rows"] == []


def test_events_endpoint_supports_cursor(client, run_id: str) -> None:
    assert client.get(f"/research-runs/{run_id}/events", params={"after": 0}).json() == []


def test_graph_reflects_experiments(client, run_id: str) -> None:
    """A succeeded experiment must produce experiment + result nodes."""
    with session_scope() as session:
        run = session.get(ResearchRun, run_id)
        experiment = Experiment(
            run_id=run_id,
            index=1,
            name="EXP-001",
            status=ExperimentStatus.SUCCEEDED.value,
            is_baseline=True,
            design={"approach": "isolation_forest", "feature_set": "base"},
        )
        session.add(experiment)
        session.flush()
        session.add(Metric(experiment_id=experiment.id, name="f1", value=0.42))
        session.add(
            Metric(experiment_id=experiment.id, name="false_positive_rate", value=0.07)
        )
        run.best_experiment_id = experiment.id
        session.commit()

        graph = build_graph(session, run)
        kinds = [n["kind"] for n in graph["nodes"]]
        assert "experiment" in kinds
        assert "result_success" in kinds

        comparison = build_comparison(run)
        assert len(comparison["rows"]) == 1
        assert comparison["best"]["metrics"]["f1"] == 0.42


def test_websocket_sends_snapshot(client, run_id: str) -> None:
    with client.websocket_connect(f"/ws/research-runs/{run_id}") as socket:
        message = socket.receive_json()
        assert message["type"] == "snapshot"
        assert "state" in message


def test_websocket_rejects_unknown_run(client) -> None:
    with client.websocket_connect("/ws/research-runs/nope") as socket:
        assert socket.receive_json()["type"] == "error"
