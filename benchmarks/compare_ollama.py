"""Compare two saved real Ollama benchmark reports, no external requests.

Usage:
    python benchmarks/compare_ollama.py old.json new.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _validate(report):
    if not isinstance(report, dict) or report.get("mode") != "real_ollama":
        raise ValueError("both inputs must be real_ollama benchmark reports")
    if not isinstance(report.get("results"), list):
        raise ValueError("missing scenario results")
    return report


def compare(baseline, candidate):
    old = _validate(baseline)
    new = _validate(candidate)

    def scores(report):
        grouped = {}
        for result in report["results"]:
            name = result["scenario"]
            grouped.setdefault(name, []).append(result)
        return grouped

    a = scores(old)
    b = scores(new)
    names = sorted(set(a) | set(b))
    details = []
    for name in names:
        before = a.get(name, [])
        after = b.get(name, [])
        before_rate = sum(bool(x["passed"]) for x in before) / len(before) if before else None
        after_rate = sum(bool(x["passed"]) for x in after) / len(after) if after else None
        delta = round(after_rate - before_rate, 4) if before_rate is not None and after_rate is not None else None
        details.append({
            "scenario": name,
            "baseline_pass_rate": round(before_rate, 4) if before_rate is not None else None,
            "candidate_pass_rate": round(after_rate, 4) if after_rate is not None else None,
            "pass_rate_delta": delta,
            "baseline_trials": len(before),
            "candidate_trials": len(after),
        })

    return {
        "baseline_model": old.get("model"),
        "candidate_model": new.get("model"),
        "baseline_digest": old.get("model_info", {}).get("model_digest"),
        "candidate_digest": new.get("model_info", {}).get("model_digest"),
        "baseline_success_rate": old["summary"]["success_rate"],
        "candidate_success_rate": new["summary"]["success_rate"],
        "rate_delta": round(new["summary"]["success_rate"] - old["summary"]["success_rate"], 4),
        "baseline_average_steps": old["summary"]["average_steps"],
        "candidate_average_steps": new["summary"]["average_steps"],
        "scenario_results": details,
        "warning": "Different trial counts, task sets, device load, or decoding settings can make comparisons misleading.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare real Ollama benchmark reports")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare(
            json.loads(args.baseline.read_text(encoding="utf-8")),
            json.loads(args.candidate.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: cannot compare reports: {exc}", file=sys.stderr)
        return 2
    for x in result["scenario_results"]:
        delta = x["pass_rate_delta"]
        print(f"{x['scenario']}: {x['baseline_pass_rate']} -> {x['candidate_pass_rate']} "
              f"(delta {delta if delta is not None else 'n/a'})")
    print(f"Overall: {result['baseline_success_rate']:.1%} -> {result['candidate_success_rate']:.1%} "
          f"(delta {result['rate_delta']:+.1%})")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Comparison saved: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
