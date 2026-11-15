"""v2.4 read-only diagnosis regression tests; no Ollama model needed."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "benchmarks" / "diagnose_ollama.py"
spec = importlib.util.spec_from_file_location("diagnose_ollama_module", MODULE)
diagnosis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnosis)


def report(results):
    return {
        "mode": "real_ollama",
        "model": "gemma3:4b",
        "created_utc": "2026-11-15T00:00:00Z",
        "model_info": {"model_digest": "sample"},
        "results": results,
    }


def row(scenario="note", passed=False, category="step_budget_or_incomplete",
        status="paused", checks=None, trial=1):
    return {
        "scenario": scenario, "passed": passed, "trial": trial,
        "failure_category": category, "status": status, "steps": 12,
        "checks": checks if checks is not None else {"no_host_write": True},
        "action_counts": {"read_file": 2},
    }


class DiagnosisTests(unittest.TestCase):
    def test_missing_model_results_not_claimed(self):
        with self.assertRaisesRegex(ValueError, "real_ollama"):
            diagnosis.diagnose({"mode": "deterministic_mock_model", "results": [row()]})
        with self.assertRaisesRegex(ValueError, "no results"):
            diagnosis.diagnose(report([]))

    def test_success_has_no_unfounded_recommendation(self):
        result = diagnosis.diagnose(report([row(passed=True,status="awaiting_approval")]))
        self.assertEqual(result["success_rate"],1)
        self.assertEqual(result["recommendations"],[])
        self.assertIn("根拠は不足", diagnosis.render_markdown(result))

    def test_host_write_violation_is_top_priority(self):
        source = report([
            row(checks={"no_host_write": False}, category="wrong_or_incomplete_artifact"),
            row(scenario="json", checks={"no_host_write": True, "exact_values": False},
                category="wrong_or_incomplete_artifact"),
        ])
        result = diagnosis.diagnose(source)
        self.assertEqual(result["recommendations"][0]["id"], "host_write_violation")
        self.assertEqual(result["recommendations"][0]["severity"], "critical")
        self.assertEqual(result["recommendations"][1]["id"], "artifact_contract_failure")
        self.assertFalse(result["recommendations"][0]["automatic_changes"])

    def test_failing_categories_and_evidence(self):
        sample = report([
            row(category="runtime_error",status="paused",checks={"no_host_write":True}),
            row(scenario="python",category="invalid_output_or_syntax",status="blocked",
                checks={"no_host_write":True, "valid_syntax":False}),
            row(scenario="json",category="blocked",status="blocked",
                checks={"no_host_write":True}),
        ])
        sample["results"][0]["error"]="TimeoutError: HTTP connection timed out"
        result=diagnosis.diagnose(sample)
        keys=[r["id"] for r in result["recommendations"]]
        self.assertIn("runtime_error",keys)
        self.assertIn("invalid_output_or_syntax",keys)
        self.assertIn("blocked",keys)
        self.assertEqual(result["total_trials"],3)
        self.assertEqual(result["observed_action_counts"]["read_file"],6)
        self.assertEqual(result["recommendations"][0]["evidence"][0]["error_class"],"TimeoutError")

    def test_cli_outputs_readable_markdown_and_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"real.json"
            original=report([row(checks={"no_host_write":True, "exact_proposed_files":False})])
            source.write_text(json.dumps(original),encoding="utf-8")
            out=root/"analysis"/"diagnosis.json"
            md=root/"analysis"/"diagnosis.md"
            self.assertEqual(diagnosis.main(["--input",str(source),"--output",str(out),
                                            "--markdown",str(md)]),0)
            self.assertEqual(json.loads(source.read_text()),original)
            self.assertEqual(json.loads(out.read_text())["mode"],"real_ollama_diagnosis")
            self.assertIn("改善",md.read_text())
            self.assertEqual(set(p.name for p in (root/"analysis").iterdir()),
                             {"diagnosis.json","diagnosis.md"})

    def test_cli_refuses_overwriting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"benchmark.json"
            content=json.dumps(report([row()]))
            source.write_text(content)
            rc=diagnosis.main(["--input",str(source),"--output",str(source),
                               "--markdown",str(Path(tmp)/"unused.md")])
            self.assertEqual(rc,2)
            self.assertEqual(source.read_text(),content)

    def test_cli_and_gui_analytics_entrypoints(self):
        import agent
        import gui
        self.assertTrue(callable(gui.DesktopApp.start_benchmark_diagnosis))
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        import benchmarks.diagnose_ollama as report_module
        with patch.object(sys, "argv", ["agent.py", "benchmark-diagnose",
                                        "--input", "source.json",
                                        "--output", "report.json",
                                        "--markdown", "report.md"]), \
             patch.object(agent, "ensure_workspace"), \
             patch.object(report_module, "main", return_value=0) as process:
            with self.assertRaises(SystemExit) as code:
                with redirect_stdout(io.StringIO()):
                    agent.main()
        self.assertEqual(code.exception.code, 0)
        process.assert_called_once_with(["--input", "source.json",
                                         "--output", "report.json",
                                         "--markdown", "report.md"])

    def test_false_flags_are_not_ignored_or_auto_applied(self):
        data=report([row(checks={"no_host_write":True, "valid_syntax":False},
                         category="wrong_or_incomplete_artifact")])
        result=diagnosis.diagnose(data)
        self.assertIn("artifact_contract_failure",[r["id"] for r in result["recommendations"]])
        for candidate in result["recommendations"]:
            self.assertTrue(candidate["requires_human_review"])
            self.assertFalse(candidate["automatic_changes"])


if __name__=="__main__":
    unittest.main()
