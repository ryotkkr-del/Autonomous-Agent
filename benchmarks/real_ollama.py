"""Real Ollama evaluation: isolated jobs, objective grading, no auto-approval.

Unlike benchmarks/run.py this invokes the actual Ollama model for plans and
decisions. It never grants search, Git, Codex or generated Python execution.
All artifacts and SQLite state exist in a disposable temporary directory.

Usage:
    python benchmarks/real_ollama.py --model gemma3:4b --steps 14
    python benchmarks/real_ollama.py --scenarios note,json,python --trials 2
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


CASES = {
    "note": {
        "goal": (
            "Create exactly one file named study.md containing a short Japanese study "
            "note about reinforcement learning. Include the exact headings "
            "'# 強化学習', '## MDP', '## Q学習', '## DQN' in that order. "
            "Under each section write an explanation rather than only headings. "
            "Do not use web search, tests, or Git. Finish once ready."
        ),
        "path": "study.md",
        "criteria": ["# 強化学習", "## MDP", "## Q学習", "## DQN"],
    },
    "json": {
        "goal": (
            "Create only config.json: valid JSON (not Markdown). It must be an object "
            "containing project='autonomous-agent', enabled=true, max_steps=8, "
            "features=['planning','review','resume'] in this exact order. "
            "Do not use web search, tests or Git. Finish after creating it."
        ),
        "path": "config.json",
    },
    "python": {
        "goal": (
            "Create only calculator.py with a Python function def double(x) that "
            "returns x*2 for numeric inputs, and a function def triple(x) that "
            "returns x*3. Keep the file import-safe: no side effects, imports or "
            "other code outside those function definitions (a module docstring "
            "is allowed). Do not execute tests, browse the web or use Git. "
            "Finish when ready."
        ),
        "path": "calculator.py",
    },
}
MAX_LOG_CHARS = 1200


@contextmanager
def isolated_agent():
    """Do not access or mutate the user's real agent database or workspace."""
    with tempfile.TemporaryDirectory(prefix="agent-real-ollama-") as dirname:
        old = agent.ROOT, agent.WORKSPACE, agent.DB
        agent.ROOT = Path(dirname)
        agent.WORKSPACE = agent.ROOT / "workspace"
        agent.DB = agent.ROOT / "bench.sqlite3"
        try:
            agent.ensure_workspace()
            yield
        finally:
            agent.ROOT, agent.WORKSPACE, agent.DB = old


def check_model(model):
    """Require a local Ollama endpoint. Avoid unintentionally sending task data away."""
    from urllib.parse import urlsplit
    endpoint = urlsplit(agent.OLLAMA_URL)
    if endpoint.scheme != "http" or endpoint.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Real benchmark requires a localhost Ollama HTTP endpoint")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise RuntimeError("Unexpected Ollama endpoint parameters")
    tags_url = f"http://127.0.0.1:{endpoint.port or 11434}/api/tags"
    # IPv6 loopback uses bracketed host syntax.
    if endpoint.hostname == "::1":
        tags_url = f"http://[::1]:{endpoint.port or 11434}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=6) as response:
            obj = json.loads(response.read(1_000_000))
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Ollama is not responding locally; start Ollama") from exc
    known = [m.get("name") for m in obj.get("models", []) if isinstance(m, dict)]
    if model not in known:
        raise RuntimeError(f"Ollama model {model!r} not installed; run: ollama pull {model}")
    return {"endpoint": endpoint.hostname, "model_available": True}


def _text_check(text, markers):
    positions = [text.find(marker) for marker in markers]
    ordered = all(p >= 0 for p in positions) and positions == sorted(positions) and len(set(positions)) == len(positions)
    # Require actual explanation, not just a sequence of headings.
    substantive = len(re.sub(r"(?m)^\s*#+[^\n]*$", "", text).strip()) >= 90
    return ordered and substantive, {
        "headings_present_in_order": ordered,
        "has_explanatory_body": substantive,
    }


def _json_check(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False, {"valid_json": False, "exact_values": False}
    exact = isinstance(data, dict) and data == {
        "project": "autonomous-agent",
        "enabled": True,
        "max_steps": 8,
        "features": ["planning", "review", "resume"],
    }
    return exact, {"valid_json": True, "exact_values": exact}


def _python_check(text):
    """Static contract check only; never execute generated Python on host."""
    try:
        module = ast.parse(text)
    except SyntaxError:
        return False, {"valid_syntax": False, "functions_found": [], "functional_test": "not_run"}
    functions = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    names = sorted(n.name for n in functions)
    allowed = all(
        isinstance(n, ast.FunctionDef) or
        (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
        for n in module.body
    )
    signatures = all(
        len(f.args.args) == 1 and f.args.args[0].arg == "x"
        and not f.args.vararg and not f.args.kwarg and not f.decorator_list
        for f in functions
    )
    complete = allowed and signatures and names == ["double", "triple"]
    # Structural check does not prove correct arithmetic.
    return complete, {
        "valid_syntax": True,
        "functions_found": names,
        "no_top_level_effects": allowed,
        "expected_signatures": signatures,
        "functional_test": "not_run",
    }


def grade(name, pending, workspace):
    spec = CASES[name]
    expected = spec["path"]
    paths = [row["path"] for row in pending]
    exact_paths = paths == [expected]
    workspace_path = workspace / expected
    # The core safety assertion: no candidate work has touched user-visible artifacts.
    no_host_write = not workspace_path.exists()
    if not exact_paths:
        return False, {"exact_proposed_files": False, "no_host_write": no_host_write}
    content = pending[0]["content"]
    if name == "note":
        ok, detail = _text_check(content, spec["criteria"])
    elif name == "json":
        ok, detail = _json_check(content)
    else:
        ok, detail = _python_check(content)
    return bool(ok and exact_paths and no_host_write), {
        "exact_proposed_files": exact_paths, "no_host_write": no_host_write,
        **detail,
    }


def _classify(status, history, passed, error=None):
    if error:
        return "runtime_error"
    if passed:
        return "passed"
    if status == "blocked":
        return "blocked"
    failures = [e for e in history if e["result"].startswith(("ERROR:", "REVIEW FAILED:"))]
    if any("invalid" in x["result"].lower() or "syntax" in x["result"].lower() for x in failures):
        return "invalid_output_or_syntax"
    if any(e["action"] in ("replan_recovery", "review_failed") for e in history):
        return "planning_or_validation"
    if status == "awaiting_approval":
        return "wrong_or_incomplete_artifact"
    return "step_budget_or_incomplete"


def run_case(name, model, steps):
    started = time.perf_counter()
    error = None
    with isolated_agent():
        # Both flags are required: all AI editing stays virtual until human approval.
        job_id = agent.make_job(CASES[name]["goal"], require_approval=True, draft_mode=True)
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                agent.run(job_id, model, budget=steps)
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:250]}"
        with agent.connection() as db:
            job = db.execute("SELECT status,steps,result FROM jobs WHERE id=?", (job_id,)).fetchone()
            history = [
                {"action": r["action"], "result": r["result"]}
                for r in db.execute("SELECT action,result FROM events WHERE job_id=? ORDER BY id", (job_id,))
            ]
            pending = [dict(r) for r in db.execute(
                "SELECT path,content FROM pending_changes WHERE job_id=? AND state='pending' ORDER BY id", (job_id,)
            )]
            root = agent.WORKSPACE / "jobs" / str(job_id)
            passed, checks = grade(name, pending, root)
            status = job["status"]
            # A full evaluation requires explicit model finish/ready signal.
            passed = passed and status == "awaiting_approval" and error is None
            replans = db.execute("SELECT COUNT(*) FROM plan_revisions WHERE job_id=?", (job_id,)).fetchone()[0]
            failure_events = sum(
                r["result"].startswith(("ERROR:", "REVIEW FAILED:")) for r in history
            )
            action_counts = {}
            for event in history:
                action_counts[event["action"]] = action_counts.get(event["action"], 0) + 1
            result = {
                "scenario": name,
                "model": model,
                "passed": bool(passed),
                "grade_scope": "static_contract_only" if name == "python" else "deterministic_content_check",
                "status": status,
                "steps": job["steps"],
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "replans": replans,
                "failure_events": failure_events,
                "action_counts": action_counts,
                "proposed_files": [x["path"] for x in pending],
                "checks": checks,
                "failure_category": _classify(status, history, passed, error),
            }
            if error:
                result["error"] = error
            # Keep logs short, not user file contents, prompts or model reasoning.
            result["log_excerpt"] = output.getvalue()[-MAX_LOG_CHARS:]
            return result


def aggregate(results):
    total = len(results)
    completed = sum(x["passed"] for x in results)
    return {
        "total": total,
        "passed": completed,
        "success_rate": round(completed / total, 4) if total else 0.0,
        "average_steps": round(sum(x["steps"] for x in results) / total, 2) if total else 0,
        "average_seconds": round(sum(x["elapsed_seconds"] for x in results) / total, 2) if total else 0,
        "failure_categories": {
            category: sum(x["failure_category"] == category for x in results)
            for category in sorted({x["failure_category"] for x in results})
            if category != "passed"
        },
    }


def benchmark(model, selected, steps, trials=1):
    report = []
    for name in selected:
        for trial in range(1, trials + 1):
            print(f"Running real Ollama scenario={name} trial={trial}/{trials}", flush=True)
            outcome = run_case(name, model, steps)
            outcome["trial"] = trial
            report.append(outcome)
            print(f"  {'PASS' if outcome['passed'] else 'FAIL'} "
                  f"steps={outcome['steps']} elapsed={outcome['elapsed_seconds']}s "
                  f"reason={outcome['failure_category']}", flush=True)
    return {
        "schema_version": 1,
        "mode": "real_ollama",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "step_budget": steps,
        "trials": trials,
        "no_auto_approval": True,
        "generated_code_executed": False,
        "limitations": [
            "Python scenario checks syntax, function names and signature only, NOT arithmetic correctness.",
            "Note quality beyond required headings and minimum body length is not measured.",
            "Different model inference seeds and device performance may change results.",
            "No execution occurs inside Docker for this benchmark; AI-generated code is never executed.",
        ],
        "summary": aggregate(report),
        "results": report,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Real Ollama, safe virtual-draft benchmark")
    parser.add_argument("--model", default="gemma3:4b")
    parser.add_argument("--scenarios", default="note,json,python", help="comma-separated: note,json,python")
    parser.add_argument("--steps", type=int, default=14)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--output", default="benchmark-results/real-ollama.json")
    args = parser.parse_args(argv)
    selected = [s.strip() for s in args.scenarios.split(",")]
    if not selected or any(s not in CASES for s in selected) or len(selected) != len(set(selected)):
        parser.error("scenarios must be unique names chosen from note,json,python")
    if not 1 <= args.steps <= 50 or not 1 <= args.trials <= 5:
        parser.error("steps must be 1-50 and trials 1-5")
    try:
        check_model(args.model)
    except RuntimeError as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 2
    result = benchmark(args.model, selected, args.steps, args.trials)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Results: {result['summary']['passed']}/{result['summary']['total']} "
          f"({result['summary']['success_rate']:.0%}); file={path}")
    return 0 if result["summary"]["passed"] == result["summary"]["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
