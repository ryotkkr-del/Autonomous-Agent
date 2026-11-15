"""Compare-script regression tests without any Ollama dependency."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "benchmarks" / "compare_ollama.py"
spec = importlib.util.spec_from_file_location("ollama_comparison", path)
compare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_module)


class ComparisonTests(unittest.TestCase):
    def _report(self, model, passes):
        entries = [
            {
                "scenario": name,
                "passed": passed,
            }
            for name, passed in passes.items()
        ]
        return {
            "mode": "real_ollama",
            "model": model,
            "model_info": {"model_digest": "test-" + model},
            "summary": {
                "success_rate": sum(x["passed"] for x in entries) / len(entries),
                "average_steps": 6,
            },
            "results": entries,
        }

    def test_same_scenarios_compare(self):
        a = self._report("a", {"note": False, "json": True})
        b = self._report("b", {"note": True, "json": True})
        result = compare_module.compare(a, b)
        self.assertEqual(result["baseline_success_rate"], 0.5)
        self.assertEqual(result["candidate_success_rate"], 1)
        self.assertEqual(result["rate_delta"], 0.5)
        self.assertEqual(result["scenario_results"][1]["pass_rate_delta"], 1.0)

    def test_missing_scenario_is_visible(self):
        a = self._report("a", {"json": True})
        b = self._report("b", {"note": False})
        report = compare_module.compare(a, b)
        self.assertEqual(len(report["scenario_results"]), 2)
        self.assertIsNone(report["scenario_results"][0]["pass_rate_delta"])

    def test_mock_benchmark_not_misreported_as_real(self):
        with self.assertRaisesRegex(ValueError, "real_ollama"):
            compare_module.compare({"mode": "deterministic_mock_model"}, self._report("b", {"note": True}))


if __name__ == "__main__":
    unittest.main()
