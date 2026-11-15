"""Offline, read-only diagnosis of measured real-Ollama benchmark failures.

No model calls, no automatic prompt edits, no code execution, no web access.
Outputs recommendations tied to observed checks and action counts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ALLOWED_CATEGORIES = {
    "passed", "runtime_error", "blocked", "invalid_output_or_syntax",
    "planning_or_validation", "wrong_or_incomplete_artifact",
    "step_budget_or_incomplete",
}
# Each recommendation is a reviewable *experiment*, not a software mutation.
RULES = (
    ("host_write_violation", "critical", "Host workspace changed during virtual drafting",
     "Stop using the benchmark until the virtual draft boundary is audited.",
     "Add a regression case that checks all workspace paths and rerun in disposable directories."),
    ("runtime_error", "high", "Model invocation or orchestration raised an exception",
     "Inspect Ollama availability, model digest, timeout and JSON schema handling.",
     "Repeat the failed case with the same model and step limit; record the exception class."),
    ("blocked", "high", "Agent reached a blocked state",
     "Inspect repeated decisions and bounded recovery. Consider a targeted recovery-policy experiment.",
     "Count repeated actions and errors before changing a single recovery parameter."),
    ("invalid_output_or_syntax", "high", "Output was invalid or Python syntax failed",
     "Consider a narrower structured-output prompt with a static syntax check before finish.",
     "Repeat the same task and verify syntax-error frequency decreases."),
    ("artifact_contract_failure", "medium", "Proposed artifact failed objective content checks",
     "Consider making deliverable paths and required fields explicit in the prompt or pre-finish validator.",
     "Repeat the same task and compare per-field assertion outcomes."),
    ("planning_or_validation", "medium", "Agent failed validation or needed replanning",
     "Inspect whether task decomposition or acceptance feedback was ambiguous.",
     "Change one plan instruction and measure step count, failures and success rate."),
    ("step_budget_or_incomplete", "medium", "Agent did not finish within its step budget",
     "Inspect redundant actions and step use before increasing the budget.",
     "Keep the original budget as baseline and compare trials after a single change."),
)


def validate_report(report):
    if not isinstance(report, dict) or report.get("mode") != "real_ollama":
        raise ValueError("expected a real_ollama benchmark report, not a mock report")
    if not isinstance(report.get("results"), list) or not report["results"]:
        raise ValueError("benchmark contains no results")
    for index, item in enumerate(report["results"]):
        if not isinstance(item, dict) or not isinstance(item.get("scenario"), str) or not item["scenario"]:
            raise ValueError(f"invalid scenario at index {index}")
        if type(item.get("passed")) is not bool:
            raise ValueError(f"invalid passed flag at index {index}")
        if not isinstance(item.get("checks"), dict):
            raise ValueError(f"missing deterministic checks at index {index}")
    return report


def _issue_ids(item):
    if item["passed"]:
        return []
    checks = item["checks"]
    if checks.get("no_host_write") is False:
        # Do not bury a host-write violation under ordinary performance faults.
        return ["host_write_violation"]
    issues = []
    category = item.get("failure_category")
    if category in ("runtime_error", "blocked", "invalid_output_or_syntax",
                    "planning_or_validation", "step_budget_or_incomplete"):
        issues.append(category)
    if any(value is False for key, value in checks.items() if key != "no_host_write"):
        issues.append("artifact_contract_failure")
    if not issues:
        issues.append("step_budget_or_incomplete" if item.get("status") != "awaiting_approval"
                      else "artifact_contract_failure")
    return list(dict.fromkeys(issues))


def diagnose(report):
    report = validate_report(report)
    findings = defaultdict(lambda: {"occurrences": 0, "scenarios": Counter(), "evidence": []})
    action_counts = Counter()
    failures_by_scenario = defaultdict(lambda: {"attempts": 0, "passed": 0, "issues": Counter()})

    for item in report["results"]:
        scenario = item["scenario"]
        entry = failures_by_scenario[scenario]
        entry["attempts"] += 1
        entry["passed"] += int(item["passed"])
        for action, count in item.get("action_counts", {}).items():
            if isinstance(action, str) and type(count) is int and 0 <= count <= 100000:
                action_counts[action] += count
        for issue in _issue_ids(item):
            f = findings[issue]
            f["occurrences"] += 1
            f["scenarios"][scenario] += 1
            entry["issues"][issue] += 1
            if len(f["evidence"]) < 6:
                f["evidence"].append({
                    "scenario": scenario,
                    "trial": item.get("trial"),
                    "status": item.get("status"),
                    "failed_checks": [key for key, value in item["checks"].items()
                                      if value is False][:8],
                    "steps": item.get("steps"),
                    "error_class": (str(item.get("error", "")).split(":", 1)[0][:50]
                                    if issue == "runtime_error" else None),
                })

    recommendations = []
    for issue, severity, title, suggestion, verification in RULES:
        if issue not in findings:
            continue
        f = findings[issue]
        recommendations.append({
            "id": issue, "severity": severity, "priority": len(recommendations) + 1,
            "title": title, "observations": f["occurrences"],
            "scenario_counts": dict(sorted(f["scenarios"].items())),
            "evidence": f["evidence"],
            "suggested_experiment": suggestion,
            "verification_plan": verification,
            "automatic_changes": False,
            "requires_human_review": True,
        })
    totals = sum(x["attempts"] for x in failures_by_scenario.values())
    completed = sum(x["passed"] for x in failures_by_scenario.values())
    return {
        "schema_version": 1, "mode": "real_ollama_diagnosis",
        "source_created_utc": report.get("created_utc"),
        "model": report.get("model"),
        "model_digest": report.get("model_info", {}).get("model_digest"),
        "total_trials": totals,
        "passed": completed,
        "success_rate": round(completed / totals, 4),
        "scenario_summary": [{
            "name": name, "attempts": x["attempts"], "passed": x["passed"],
            "failure_counts": dict(sorted(x["issues"].items())),
        } for name, x in sorted(failures_by_scenario.items())],
        "observed_action_counts": dict(sorted(action_counts.items())),
        "recommendations": recommendations,
        "notes": [
            "Recommendations are rule-based hypotheses, not proven root causes.",
            "No prompts, code, permissions, scheduled jobs or user workspace files are changed.",
            "Benchmark measures deterministic checks, not comprehensive correctness or security.",
            "Use comparable scenario sets, budgets and multiple trials to validate improvements.",
        ],
    }


def render_markdown(report):
    lines = [
        "# Autonomous Agent — 実AI評価の失敗分析",
        "",
        f"- モデル: {report.get('model') or 'unknown'}",
        f"- 試行: {report['total_trials']} / 成功: {report['passed']}",
        f"- 成功率: {report['success_rate']:.1%}",
        "",
        "## タスク別の結果",
        "",
        "| タスク | 成功 / 試行 |", "|---|---:|",
    ]
    for item in report["scenario_summary"]:
        lines.append(f"| {item['name']} | {item['passed']} / {item['attempts']} |")
    lines.extend(["", "## 根拠に基づく改善候補", ""])
    if not report["recommendations"]:
        lines.append("記録された失敗はありません。現時点で改善案を自動生成する根拠は不足しています。")
    for item in report["recommendations"]:
        lines.extend([
            f"### {item['priority']}. {item['title']}",
            f"- 重要度: {item['severity']} / 観測回数: {item['observations']}",
            "- 観測タスク: " + ", ".join(f"{name} ({count})" for name, count in item["scenario_counts"].items()),
            f"- 改善仮説: {item['suggested_experiment']}",
            f"- 検証方法: {item['verification_plan']}",
            "- **変更の自動適用なし。人間によるレビューが必要。**",
            "",
        ])
    lines.extend(["## 解釈上の限界", ""])
    lines.extend("- " + note for note in report["notes"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only diagnosis of real Ollama evaluation")
    parser.add_argument("--input", type=Path, default=Path("benchmark-results/real-ollama.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/diagnosis.json"))
    parser.add_argument("--markdown", type=Path, default=Path("benchmark-results/diagnosis.md"))
    args = parser.parse_args(argv)
    try:
        source = json.loads(args.input.read_text(encoding="utf-8"))
        result = diagnose(source)
        markdown = render_markdown(result)
        paths=[args.output.resolve(),args.markdown.resolve()]
        if args.input.resolve() in paths or paths[0] == paths[1]:
            raise ValueError("output paths must be distinct and cannot overwrite input benchmark")
        for path, content in ((args.output, json.dumps(result, ensure_ascii=False, indent=2) + "\n"),
                              (args.markdown, markdown)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: diagnosis failed: {exc}", file=sys.stderr)
        return 2
    print(f"Diagnosed {result['total_trials']} trials, {len(result['recommendations'])} improvement hypotheses.")
    print("Review:", args.markdown)
    print("No changes were applied to the agent or benchmark files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
