"""End-to-end acceptance test against a live GENESIS API.

Exercises the product the way the UI does and asserts what actually matters:
real measured metrics, correct domain routing, honest verdicts, a connected
research graph, working controls, and refusal where the system cannot answer.
"""
import json
import sys
import time
import urllib.request

import os
B = os.environ.get("GENESIS_API", "http://127.0.0.1:8000")
FAILURES: list[str] = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{('  - ' + detail) if detail else ''}", flush=True)
    if not ok:
        FAILURES.append(label)
    return ok


def get(path):
    return json.load(urllib.request.urlopen(B + path, timeout=60))


def post(path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        B + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    return json.load(urllib.request.urlopen(req, timeout=120))


def run_to_completion(question, budget, demo, limit):
    run_id = post("/research-runs", {
        "question": question, "max_experiments": budget, "demo_mode": demo})["id"]
    post(f"/research-runs/{run_id}/start")
    started, seen = time.time(), 0
    while time.time() - started < limit:
        for event in get(f"/research-runs/{run_id}/events?after={seen}"):
            seen = event["seq"]
            if event["status"] == "error":
                print(f"        ! {event['agent']}: {event['message'][:92]}", flush=True)
        detail = get(f"/research-runs/{run_id}")
        if detail["state"] in ("COMPLETED", "FAILED"):
            detail["_elapsed"] = time.time() - started
            return detail
        time.sleep(3)
    detail = get(f"/research-runs/{run_id}")
    detail["_elapsed"] = time.time() - started
    return detail


print("=" * 78)
print("GENESIS end-to-end acceptance")
print("=" * 78)

for _ in range(90):
    try:
        urllib.request.urlopen(B + "/health", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    print("  [FAIL] API never became healthy")
    sys.exit(1)

st = get("/system/status")
print(f"\nSYSTEM  llm={st['llm_provider']}/{st['llm_model']}  "
      f"sandbox={st['sandbox_backend']}  db={st['database']}\n")

ANOMALY = "Can we improve network anomaly detection while reducing false positives?"
GENERAL = "Does feature scaling matter more for distance-based models than tree-based models?"

# ------------------------------------------------------------------- 1
print("SCENARIO 1 - demo mode, anomaly domain, deterministic agents")
run = run_to_completion(ANOMALY, 3, True, 400)
check("run completes", run["state"] == "COMPLETED", f"{run['state']} in {run['_elapsed']:.0f}s")
check("experiments executed", run["experiments_completed"] >= 2,
      f"{run['experiments_completed']}/{run['max_experiments']}")
check("literature retrieved", len(run["papers"]) > 0, f"{len(run['papers'])} papers")

cmp1 = get(f"/research-runs/{run['id']}/comparison")
rows = cmp1["rows"]
check("every experiment has real metrics",
      all(r["metrics"] and any(v != 0 for v in r["metrics"].values()) for r in rows),
      f"{len(rows)} rows")
check("no polluted metric keys",
      not any(k.startswith("__") for r in rows for k in r["metrics"]))
check("baseline and best identified", bool(cmp1["baseline"]) and bool(cmp1["best"]),
      f"best={cmp1['best']['name'][:32]}" if cmp1["best"] else "none")
check("improvement is real", len(rows) < 2 or rows[-1]["metrics"].get("f1", 0) > rows[0]["metrics"].get("f1", 0),
      f"f1 {rows[0]['metrics'].get('f1', 0):.4f} -> {rows[-1]['metrics'].get('f1', 0):.4f}")

graph = get(f"/research-runs/{run['id']}/graph")
kinds = [n["kind"] for n in graph["nodes"]]
check("graph is populated and typed",
      all(k in kinds for k in ("question", "hypothesis", "experiment")),
      f"{len(graph['nodes'])} nodes / {len(graph['edges'])} edges")
linked = sum(1 for e in run["experiments"] if e["hypothesis_id"])
check("experiments link to hypotheses", linked == len(run["experiments"]),
      f"{linked}/{len(run['experiments'])}")

summary = run.get("final_summary") or {}
check("final summary produced", bool(summary.get("recommendation")))
check("improvement computed from measurements", "improvement_pct" in summary,
      f"{summary.get('improvement_pct')}%")
check("decisions carry evidence",
      bool(run["decisions"]) and all(d["evidence"] for d in run["decisions"]),
      f"{len(run['decisions'])} decisions")

code = get(f"/experiments/{rows[0]['id']}/code")["code"]
check("generated code retrievable", "result.json" in code, f"{len(code.splitlines())} lines")
res = get(f"/experiments/{rows[0]['id']}/results")
check("stdout captured for replay", len(res["stdout"]) > 0,
      f"{len(res['stdout'].splitlines())} lines")

# ------------------------------------------------------------------- 2
print("\nSCENARIO 2 - user-injected hypothesis")
rid2 = post("/research-runs", {"question": ANOMALY, "max_experiments": 2, "demo_mode": True})["id"]
inj = post("/hypotheses", {
    "run_id": rid2, "title": "Gradient boosting on temporal features beats random forest",
    "approach": "gradient_boosting", "feature_set": "temporal"})
check("hypothesis injected", inj["origin"] == "user")
check("structured fields stored", inj.get("approach") == "gradient_boosting")

# ------------------------------------------------------------------- 3
print("\nSCENARIO 3 - demo mode refuses a domain it cannot honestly cover")
run3 = run_to_completion(GENERAL, 1, True, 180)
check("refuses instead of running the wrong experiment",
      run3["state"] == "FAILED" and "anomaly detection" in (run3.get("error") or ""),
      (run3.get("error") or run3["state"])[:60])

# ------------------------------------------------------------------- 4
print("\nSCENARIO 4 - real model run on that same non-anomaly domain")
run4 = run_to_completion(GENERAL, 1, False, 900)
check("completes with a model", run4["state"] == "COMPLETED",
      f"{run4['state']} in {run4['_elapsed']:.0f}s")
designs = [e["design"] for e in run4["experiments"]]
if designs:
    check("routed to a self-contained experiment",
          designs[0].get("dataset_mode") == "self_contained",
          f"mode={designs[0].get('dataset_mode')} approach={designs[0].get('approach')}")
    cmp4 = get(f"/research-runs/{run4['id']}/comparison")
    if cmp4["rows"]:
        m = cmp4["rows"][0]["metrics"]
        check("measured real metrics for its own domain",
              bool(m) and any(v != 0 for v in m.values()),
              ", ".join(f"{k}={v:.4g}" for k, v in list(m.items())[:3]))
        check("ranked on a metric it measured", cmp4.get("primaryMetric") in m,
              f"primary={cmp4.get('primaryMetric')}")
    else:
        check("experiment produced metrics", False, "no rows")
else:
    check("an experiment was designed", False, "none created")

# ------------------------------------------------------------------- 5
print("\nSCENARIO 5 - run controls")
rid5 = post("/research-runs", {"question": ANOMALY, "max_experiments": 3, "demo_mode": True})["id"]
post(f"/research-runs/{rid5}/start")
time.sleep(4)
post(f"/research-runs/{rid5}/pause")
for _ in range(40):
    if get(f"/research-runs/{rid5}")["state"] == "PAUSED":
        break
    time.sleep(2)
check("pause reaches PAUSED", get(f"/research-runs/{rid5}")["state"] == "PAUSED")
post(f"/research-runs/{rid5}/resume")
time.sleep(3)
check("resume leaves PAUSED", get(f"/research-runs/{rid5}")["state"] != "PAUSED")
post(f"/research-runs/{rid5}/stop")
check("stop accepted", True)

print("\n" + "=" * 78)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILED -> " + "; ".join(FAILURES))
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
