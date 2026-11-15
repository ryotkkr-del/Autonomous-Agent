"""Deterministic end-to-end agent scenarios using the real task loop.

No external LLM/network calls, no arbitrary user code. These benchmarks measure
orchestration reliability, NOT real Ollama intelligence or multi-day endurance.
Run: python benchmarks/run.py
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent

ACTION_KEYS = ("action", "path", "content", "reason")


def action(op, path="", content="", reason="benchmark"):
    return dict(zip(ACTION_KEYS, (op, path, content, reason)))


@contextmanager
def isolated_agent():
    with tempfile.TemporaryDirectory(prefix="agent-bench-") as tmp:
        old = agent.ROOT, agent.WORKSPACE, agent.DB
        agent.ROOT = Path(tmp)
        agent.WORKSPACE = agent.ROOT / "workspace"
        agent.DB = agent.ROOT / "state.sqlite3"
        try:
            agent.ensure_workspace()
            yield
        finally:
            agent.ROOT, agent.WORKSPACE, agent.DB = old


def events_for(job):
    with agent.connection() as db:
        status = db.execute("SELECT status,steps,result FROM jobs WHERE id=?", (job,)).fetchone()
        rows = db.execute("SELECT action,result FROM events WHERE job_id=? ORDER BY id", (job,)).fetchall()
        control = db.execute("SELECT stall_recoveries FROM job_controls WHERE job_id=?", (job,)).fetchone()
    return dict(status), [dict(r) for r in rows], control[0] if control else 0


def scenario_report():
    goal = "Create a structured study note"
    plan = {"tasks": ["outline", "write note", "review"], "deliverables": ["lesson.md"]}
    steps = iter([
        action("write_file", "lesson.md", "# Lesson\n\nSummary: finished.\n"),
        action("finish"),
    ])
    job = agent.make_job(goal)
    agent.set_criteria(job, ["lesson.md"], ["lesson.md::Summary"])
    with patch.object(agent, "make_plan", return_value=plan), \
         patch.object(agent, "decide", side_effect=lambda *a, **kw: next(steps)), \
         patch.object(agent, "review", return_value=(True, "verified")):
        agent.run(job, "benchmark", budget=3)
    status, events, retries = events_for(job)
    return {"passed": status["status"] == "done",
            "assertions": ["report created", "criteria checked", "completed"],
            "steps": status["steps"], "replans": retries,
            "events": [e["action"] for e in events]}


def scenario_code():
    goal = "Create a Python function and a passing test"
    plan = {"tasks": ["create module", "add test", "verify"], "deliverables": ["mathutil.py"]}
    test_source = ("import unittest\n"
                   "class T(unittest.TestCase):\n"
                   "    def test_double(self):\n"
                   "        self.assertEqual(2*3, 6)\n")
    steps = iter([
        action("write_file", "mathutil.py", "def double(x):\n    return x * 2\n"),
        action("write_file", "tests/test_mathutil.py", test_source),
        action("finish"),
    ])
    job = agent.make_job(goal)
    with agent.connection() as db:
        db.execute("UPDATE jobs SET allow_tests=1 WHERE id=?", (job,))
    with patch.object(agent, "make_plan", return_value=plan), \
         patch.object(agent, "decide", side_effect=lambda *a, **kw: next(steps)), \
         patch.object(agent, "review", return_value=(True, "verified")):
        agent.run(job, "benchmark", budget=5)
    status, events, retries = events_for(job)
    tests_ok = any(e["action"] == "auto_tests" and e["result"].startswith("TEST PASS") for e in events)
    return {"passed": status["status"] == "done" and tests_ok,
            "assertions": ["module written", "real unittest subprocess passed", "completed"],
            "steps": status["steps"], "replans": retries,
            "events": [e["action"] for e in events]}


def scenario_recovery():
    goal = "Recover from a repetitive stall and produce output"
    plan = {"tasks": ["explore"], "deliverables": ["result.txt"]}
    steps = iter([
        action("list_files"), action("list_files"), action("list_files"),
        action("write_file", "result.txt", "Recovered after a stalled plan."),
        action("finish"),
    ])
    job = agent.make_job(goal)
    with patch.object(agent, "make_plan", return_value=plan), \
         patch.object(agent, "decide", side_effect=lambda *a, **kw: next(steps)), \
         patch.object(agent, "revise_plan", return_value={"tasks": ["try alternate approach"], "deliverables": ["result.txt"]}), \
         patch.object(agent, "review", return_value=(True, "verified")):
        agent.run(job, "benchmark", budget=8)
    status, events, retries = events_for(job)
    return {"passed": status["status"] == "done" and retries == 1,
            "assertions": ["stall detected", "one recovery", "completed"],
            "steps": status["steps"], "replans": retries,
            "events": [e["action"] for e in events]}


def scenario_resume():
    goal = "Write a note across two independent run calls"
    plan = {"tasks": ["write", "review"], "deliverables": ["note.txt"]}
    steps = iter([action("write_file", "note.txt", "Persisted note"), action("finish")])
    job = agent.make_job(goal)
    with patch.object(agent, "make_plan", return_value=plan), \
         patch.object(agent, "decide", side_effect=lambda *a, **kw: next(steps)), \
         patch.object(agent, "review", return_value=(True, "verified")):
        agent.run(job, "benchmark", budget=1)
        first, _, _ = events_for(job)
        # Re-open the database in the next run, exactly as the scheduler does.
        agent.run(job, "benchmark", budget=2)
    status, events, retries = events_for(job)
    return {"passed": first["status"] == "paused" and status["status"] == "done",
            "assertions": ["paused after bounded run", "SQLite state retained", "completed on resume"],
            "steps": status["steps"], "replans": retries,
            "events": [e["action"] for e in events]}


SCENARIOS = {
    "study_note": scenario_report,
    "python_with_tests": scenario_code,
    "stall_recovery": scenario_recovery,
    "resume": scenario_resume,
}


def run_benchmark():
    results = []
    for name, func in SCENARIOS.items():
        started = time.perf_counter()
        try:
            with isolated_agent():
                outcome = func()
            outcome = {"name": name, **outcome}
        except Exception as exc:
            outcome = {"name": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        outcome["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        results.append(outcome)
    return {"schema_version": 1, "mode": "deterministic_mock_model",
            "note": "Measures orchestration only; no Ollama/Codex, real web, or multi-day execution.",
            "total": len(results), "passed": sum(bool(x["passed"]) for x in results),
            "results": results}


def main():
    parser = argparse.ArgumentParser(description="Autonomous Agent benchmark")
    parser.add_argument("--output", default="benchmark-results.json")
    args = parser.parse_args()
    result = run_benchmark()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in result["results"]:
        print(("PASS" if item["passed"] else "FAIL"), item["name"],
              f"steps={item.get('steps', '?')}", item.get("error", ""))
    print(f"{result['passed']}/{result['total']} scenarios; saved to {output}")
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
