"""Opt-in local paired evaluation of a single candidate decision-prompt change.

Runs a full baseline followed by the same task suite with a user-selected
decision-only guidance text. Makes no changes to production prompts, agent
code, existing jobs, permissions, or workspace artifacts. No auto-approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

try:
    from benchmarks import real_ollama, compare_ollama
except ImportError:
    import real_ollama
    import compare_ollama

MAX_INSTRUCTION_BYTES = 4000


def read_instruction(path):
    """Bound input size and exclude binary/empty experiment instructions."""
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("instruction must be an existing regular, non-symlink file")
    if path.stat().st_size>MAX_INSTRUCTION_BYTES:
        raise ValueError("experiment instruction exceeds 4000 bytes")
    raw=path.read_bytes()
    if b"\x00" in raw:
        raise ValueError("binary experiment instructions are not supported")
    text=raw.decode("utf-8").strip()
    if not text:
        raise ValueError("experiment instruction is empty")
    if len(text.encode("utf-8"))>MAX_INSTRUCTION_BYTES:
        raise ValueError("experiment instruction exceeds 4000 bytes")
    return text


def evaluate_pair(model,scenarios,steps,trials,instruction,model_info):
    baseline=real_ollama.benchmark(model,scenarios,steps,trials)
    candidate=real_ollama.benchmark(model,scenarios,steps,trials,
                                    decision_instruction=instruction)
    baseline["model_info"]=model_info
    candidate["model_info"]=model_info
    summary=compare_ollama.compare(baseline,candidate)
    summary["comparison_type"]="paired_decision_prompt_experiment"
    summary["same_scenarios"]=True
    summary["same_step_budget"]=True
    summary["same_trial_count"]=True
    summary["approved_experiment_only"]=True
    summary["instruction_sha256"]=hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    summary["verdict"]="Review the experimental results; never auto-apply prompts or code"
    return baseline,candidate,summary


def main(argv=None):
    p=argparse.ArgumentParser(description="Compare real Ollama baseline vs reviewed decision guidance")
    p.add_argument("--instruction-file",type=Path,required=True)
    p.add_argument("--confirm",action="store_true",help="explicitly approve 2 full local Ollama evaluation passes")
    p.add_argument("--model",default="gemma3:4b")
    p.add_argument("--steps",type=int,default=14)
    p.add_argument("--trials",type=int,default=2)
    p.add_argument("--scenarios",default="note,json,python")
    p.add_argument("--output-dir",type=Path,default=Path("benchmark-results/experiment"))
    args=p.parse_args(argv)
    if not args.confirm:
        print("ERROR: explicit --confirm is required for the two full Ollama runs",file=sys.stderr)
        return 2
    names=[x.strip() for x in args.scenarios.split(",")]
    if not names or len(names)!=len(set(names)) or any(x not in real_ollama.CASES for x in names):
        p.error("scenarios must be unique names from note,json,python")
    if not 1<=args.steps<=50 or not 1<=args.trials<=5:
        p.error("steps must be 1-50 and trials 1-5")
    try:
        note=read_instruction(args.instruction_file)
        model_info=real_ollama.check_model(args.model)
        baseline,candidate,comparison=evaluate_pair(
            args.model,names,args.steps,args.trials,note,model_info)
        output_dir=args.output_dir.resolve()
        # Do not overwrite the input instruction, existing outputs, or the
        # model's actual agent workspace. Existing results stay immutable.
        target_names=("baseline.json","candidate.json","comparison.json")
        destinations=[output_dir/name for name in target_names]
        if args.instruction_file.resolve() in destinations:
            raise ValueError("instruction path conflicts with experiment output")
        if any(path.exists() or path.is_symlink() for path in destinations):
            raise ValueError("experiment output files already exist; use a new output directory")
        output_dir.mkdir(parents=True,exist_ok=True)
        for dest,record in zip(destinations,(baseline,candidate,comparison)):
            with dest.open("x",encoding="utf-8") as handle:
                json.dump(record,handle,ensure_ascii=False,indent=2)
                handle.write("\n")
    except (OSError,ValueError,RuntimeError,UnicodeError,KeyError,TypeError) as exc:
        print("ERROR: experiment failed:",str(exc)[:400],file=sys.stderr)
        return 2
    print("Baseline:",f"{baseline['summary']['passed']}/{baseline['summary']['total']}")
    print("Candidate:",f"{candidate['summary']['passed']}/{candidate['summary']['total']}")
    print("Difference:",f"{comparison['rate_delta']:+.1%}")
    print("Results:",args.output_dir)
    print("No production prompt or agent code was changed.")
    return 0


if __name__=="__main__":
    sys.exit(main())
