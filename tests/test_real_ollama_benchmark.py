"""Contract tests for v2.3 real Ollama benchmark (model mocked only here).

Real Ollama measurements are deliberately opt-in on the user's own computer.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent

MODULE_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "real_ollama.py"
spec = importlib.util.spec_from_file_location("real_ollama_benchmark", MODULE_PATH)
real = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = real
spec.loader.exec_module(real)


def action(operation, path="", content=""):
    return {"action": operation, "path": path, "content": content, "reason": "test"}


class RealBenchmarkTests(unittest.TestCase):
    def test_schema_checks(self):
        content = ("# 強化学習\n学習の目標と報酬を使う方法を説明する。\n"
                   "## MDP\n状態と行動の遷移を定義し、方策から価値を推定する。\n"
                   "## Q学習\n価値を逐次更新し、試行錯誤でよい行動を学習する。\n"
                   "## DQN\n深層ニューラルネットワークでQ値を近似する。\n"
                   "行動を評価するときは学習データの偏りを観察する。\n")
        self.assertTrue(real._text_check(content, real.CASES["note"]["criteria"])[0])
        self.assertFalse(real._text_check("# 強化学習\n## DQN\n## MDP\n## Q学習", real.CASES["note"]["criteria"])[0])
        self.assertTrue(real._json_check(json.dumps({
            "project": "autonomous-agent", "enabled": True, "max_steps": 8,
            "features": ["planning", "review", "resume"]}))[0])
        self.assertFalse(real._json_check('{"max_steps": "8"}')[0])
        self.assertTrue(real._python_check("def double(x):\n return 2*x\ndef triple(x):\n return 3*x\n")[0])
        self.assertFalse(real._python_check("print('untrusted')\ndef double(x):return x*2\ndef triple(x):return x*3")[0])
        self.assertEqual(real._python_check("def double(x): return x*2\ndef triple(x): return x*3")[1]["functional_test"], "not_run")

    def test_run_case_uses_actual_agent_loop_and_keeps_host_unchanged(self):
        config = json.dumps({
            "project": "autonomous-agent", "enabled": True, "max_steps": 8,
            "features": ["planning", "review", "resume"],
        })
        initial = agent.ROOT, agent.WORKSPACE, agent.DB
        original_run = agent.run

        def guarded_run(job_id, model, budget):
            with agent.connection() as db:
                row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                self.assertEqual(row["allow_tests"], 0)
                self.assertEqual(row["allow_git"], 0)
                self.assertTrue(agent.draft_enabled(db, job_id))
            self.assertEqual(model, "test-model")
            return original_run(job_id, model, budget)

        options = iter([action("write_file", "config.json", config), action("finish")])
        with patch.object(agent, "make_plan", return_value={"tasks": ["write JSON"], "deliverables": ["config.json"]}), \
             patch.object(agent, "decide", side_effect=lambda *args, **kwargs: next(options)), \
             patch.object(agent, "run", side_effect=guarded_run), \
             patch.object(agent, "ollama", side_effect=AssertionError("not needed for fake test")), \
             patch.object(agent, "execute", wraps=agent.execute) as execute:
            result = real.run_case("json", "test-model", steps=3)
        self.assertEqual((agent.ROOT, agent.WORKSPACE, agent.DB), initial)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertTrue(result["checks"]["no_host_write"])
        self.assertFalse(any(c.args[0].get("action") == "write_file" for c in execute.call_args_list))

    def test_failure_classification_and_aggregation(self):
        self.assertEqual(real._classify("paused", [], False), "step_budget_or_incomplete")
        self.assertEqual(real._classify("blocked", [], False), "blocked")
        report = real.aggregate([
            {"passed": True, "steps": 3, "elapsed_seconds": 1, "failure_category": "passed"},
            {"passed": False, "steps": 7, "elapsed_seconds": 5, "failure_category": "blocked"},
        ])
        self.assertEqual(report["success_rate"], 0.5)
        self.assertEqual(report["average_steps"], 5)
        self.assertEqual(report["failure_categories"], {"blocked": 1})

    def test_model_check_rejects_remote_endpoint_without_network(self):
        with patch.object(agent, "OLLAMA_URL", "https://remote.example/api/chat"), \
             patch.object(real.urllib.request, "urlopen", side_effect=AssertionError("no remote requests")):
            with self.assertRaisesRegex(RuntimeError, "localhost"):
                real.check_model("gemma3:4b")

    def test_preflight_rejects_missing_model(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                return False
            def read(self, limit):
                return b'{"models":[{"name":"other:latest"}]}'
        with patch.object(real.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                real.check_model("gemma3:4b")

    def test_cli_does_not_evaluate_without_ollama(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "no-output.json"
            with patch.object(real, "check_model", side_effect=RuntimeError("Ollama off")), \
                 patch.object(real, "benchmark", side_effect=AssertionError("should not call")):
                code = real.main(["--output", str(target)])
            self.assertEqual(code, 2)
            self.assertFalse(target.exists())

    def test_cli_dispatch_and_gui_entrypoint(self):
        import gui
        self.assertTrue(callable(gui.DesktopApp.start_real_benchmark))
        import benchmarks.real_ollama as cli_real
        with patch.object(sys, "argv", ["agent.py", "benchmark-real",
                                       "--model", "gemma3:4b", "--steps", "3", "--trials", "2",
                                       "--scenarios", "note,json"]), \
             patch.object(cli_real, "main", return_value=0) as invoked:
            with self.assertRaises(SystemExit) as done:
                agent.main()
        self.assertEqual(done.exception.code, 0)
        invoked.assert_called_once_with(["--model", "gemma3:4b", "--steps", "3",
                                         "--trials", "2", "--scenarios", "note,json"])

    def test_fixture_output_isolated_from_user_workspace(self):
        before = agent.ROOT, agent.WORKSPACE, agent.DB
        with real.isolated_agent():
            self.assertNotEqual(agent.ROOT, before[0])
            self.assertNotEqual(agent.DB, before[2])
            self.assertNotEqual(agent.WORKSPACE, before[1])
        self.assertEqual((agent.ROOT, agent.WORKSPACE, agent.DB), before)


if __name__ == "__main__":
    unittest.main()
