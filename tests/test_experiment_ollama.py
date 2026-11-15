"""v2.5 offline tests: prompt comparison is explicit, isolated and non-mutating."""
import importlib.util
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import agent

script=Path(__file__).resolve().parents[1]/"benchmarks"/"experiment_ollama.py"
spec=importlib.util.spec_from_file_location("experiment_ollama_tests",script)
ex=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=ex
spec.loader.exec_module(ex)


def fake_report(model, instruction=""):
    passed=bool(instruction)
    return {
        "mode":"real_ollama",
        "model":model,
        "model_info":{"model_digest":"same"},
        "summary":{"success_rate":float(passed),"passed":int(passed),"total":1,"average_steps":4},
        "results":[{"scenario":"json","passed":passed}],
    }


class ExperimentTests(unittest.TestCase):
    def test_no_confirmation_never_calls_ollama(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"note.txt"
            source.write_text("check the file before finish",encoding="utf-8")
            with patch.object(ex.real_ollama,"check_model",side_effect=AssertionError("Ollama called")):
                self.assertEqual(ex.main(["--instruction-file",str(source)]),2)

    def test_validate_user_instruction(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"note.txt"
            source.write_text("compare every output field",encoding="utf-8")
            self.assertEqual(ex.read_instruction(source),"compare every output field")
            source.write_bytes(b"\x00bad")
            with self.assertRaisesRegex(ValueError,"binary"):
                ex.read_instruction(source)
            source.write_text("x"*4001,encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"exceeds"):
                ex.read_instruction(source)

    def test_evaluate_pair_changes_only_decision_instruction(self):
        observations=[]
        def fake_bench(model,scenarios,steps,trials,decision_instruction=""):
            observations.append((model,tuple(scenarios),steps,trials,decision_instruction))
            return fake_report(model,decision_instruction)
        with patch.object(ex.real_ollama,"benchmark",side_effect=fake_bench):
            baseline,candidate,comparison=ex.evaluate_pair(
                "gemma3:4b",["json"],8,2,"validate every JSON field",{"model_digest":"x"})
        self.assertEqual([x[-1] for x in observations],["","validate every JSON field"])
        self.assertEqual(observations[0][:4],observations[1][:4])
        self.assertFalse(baseline["results"][0]["passed"])
        self.assertTrue(candidate["results"][0]["passed"])
        self.assertEqual(comparison["rate_delta"],1.0)
        self.assertTrue(comparison["approved_experiment_only"])

    def test_experiment_writes_only_new_reports(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            instruction=root/"instruction.txt"
            instruction.write_text("Review JSON types before finish",encoding="utf-8")
            output=root/"output"
            initial=(agent.ROOT,agent.WORKSPACE,agent.DB)
            with patch.object(ex.real_ollama,"check_model",return_value={"model_digest":"modeldigest"}), \
                 patch.object(ex.real_ollama,"benchmark",side_effect=lambda m,s,st,t,
                              decision_instruction="":fake_report(m,decision_instruction)):
                rc=ex.main(["--instruction-file",str(instruction),
                            "--confirm","--scenarios","json","--output-dir",str(output)])
            self.assertEqual(rc,0)
            self.assertEqual((agent.ROOT,agent.WORKSPACE,agent.DB),initial)
            self.assertEqual({f.name for f in output.iterdir()},
                             {"baseline.json","candidate.json","comparison.json"})
            self.assertEqual(instruction.read_text(),"Review JSON types before finish")
            self.assertEqual(json.loads((output/"comparison.json").read_text())["rate_delta"],1.0)
            with patch.object(ex.real_ollama,"check_model",return_value={"model_digest":"modeldigest"}), \
                 patch.object(ex.real_ollama,"benchmark",side_effect=AssertionError("should precheck output")):
                rc2=ex.main(["--instruction-file",str(instruction),
                             "--confirm","--scenarios","json","--output-dir",str(output)])
            self.assertEqual(rc2,2)

    def test_decision_appendix_scoped_only_to_model_decision(self):
        from benchmarks import real_ollama
        got=[]
        plan={"tasks":["write file"],"deliverables":["config.json"]}
        valid=json.dumps({"project":"autonomous-agent","enabled":True,
                          "max_steps":8,"features":["planning","review","resume"]})
        actions=iter([{"action":"write_file","path":"config.json","content":valid,"reason":"create"},
                      {"action":"finish","path":"","content":"","reason":"done"}])
        def capture_decide(goal,*args,**kwargs):
            got.append(goal)
            return next(actions)
        with patch.object(agent,"make_plan",return_value=plan), \
             patch.object(agent,"decide",side_effect=capture_decide):
            result=real_ollama.run_case("json","test-model",3,decision_instruction="Check fields carefully.")
        self.assertTrue(result["passed"],result)
        self.assertEqual(len(got),2)
        self.assertTrue(all("Check fields carefully." in x for x in got))
        self.assertTrue(result["checks"]["no_host_write"])

    def test_invalid_scenario_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"note.txt"
            f.write_text("review constraints")
            with self.assertRaises(SystemExit):
                ex.main(["--confirm","--instruction-file",str(f),"--scenarios","invalid"])


if __name__=="__main__":
    unittest.main()
