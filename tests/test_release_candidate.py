"""P0-4 stage3 regression tests: fail closed for CI, unsigned code and staging."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import release_candidate as candidate

SIGNER = "A" * 40
SHA = "1" * 40


def ci_record(workflow, commit=SHA, status="completed", conclusion="success",
              branch="main", event="push", run_id=10, repository=None):
    return {
        "path": workflow,  # exact shape returned by the live GitHub Actions API
        "head_sha": commit, "head_branch": branch, "event": event,
        "id": run_id, "run_attempt": 1,
        "status": status, "conclusion": conclusion,
        "repository": {"full_name": repository or candidate.REPOSITORY},
    }


def ci_fixture(commit=SHA):
    return {"workflow_runs": [
        ci_record(path, commit=commit, run_id=i + 1)
        for i, path in enumerate(sorted(candidate.WORKFLOWS))
    ]}


class CandidatePolicyTests(unittest.TestCase):
    def test_three_successful_workflows_for_exact_commit(self):
        info = candidate.verify_ci(SHA, ci_fixture())
        self.assertEqual(set(info), candidate.WORKFLOWS)
        self.assertEqual({x["commit"] for x in info.values()}, {SHA})

    def test_repository_prefixed_workflow_path_also_supported(self):
        data = ci_fixture()
        for entry in data["workflow_runs"]:
            entry["path"] = candidate.REPOSITORY + "/" + entry["path"] + "@refs/heads/main"
        self.assertEqual(set(candidate.verify_ci(SHA, data)), candidate.WORKFLOWS)

    def test_missing_or_failed_ci_refuses(self):
        normal = ci_fixture()
        cases = []
        cases.append({"workflow_runs": normal["workflow_runs"][:2]})
        for key, value in [("head_sha", "2" * 40), ("head_branch", "dev"),
                           ("event", "pull_request"), ("status", "in_progress"),
                           ("conclusion", "failure")]:
            example = json.loads(json.dumps(normal))
            example["workflow_runs"][0][key] = value
            cases.append(example)
        for sample in cases:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                candidate.verify_ci(SHA, sample)

    def test_latest_failed_rerun_takes_precedence_over_old_success(self):
        data = ci_fixture()
        failed = dict(data["workflow_runs"][0])
        failed.update(id=99, conclusion="failure")
        data["workflow_runs"].append(failed)
        with self.assertRaisesRegex(ValueError, "not successful"):
            candidate.verify_ci(SHA, data)

    def test_impostor_workflow_name_does_not_qualify(self):
        data = ci_fixture()
        data["workflow_runs"][0]["path"] = (
            "attacker/other/.github/workflows/tests.yml@refs/heads/main")
        with self.assertRaisesRegex(ValueError, "missing"):
            candidate.verify_ci(SHA, data)

    def test_case_collision_traversal_windows_names_and_runtime_paths(self):
        for path in ("../outside", "/etc/passwd", "src/../file.py",
                     "C:/Windows/system32", "con.py", "LPT1.txt",
                     "file.py.", "normal\\evil.py", "workspace/secret",
                     "state.sqlite3", "benchmark-results/result.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                candidate._tree_path(path)
        self.assertEqual(candidate._tree_path(".github/workflows/tests.yml"),
                         ".github/workflows/tests.yml")

    def test_missing_trust_never_checks_ci_or_stages(self):
        with patch.object(candidate.release_policy, "read_trust",
                          side_effect=ValueError("no independent signing key")), \
             patch.object(candidate, "fetch_ci_json",
                          side_effect=AssertionError("network must not happen")), \
             patch.object(candidate, "stage_release",
                          side_effect=AssertionError("stage must not happen")):
            result = candidate.main(["--tag", "v3.0.0"])
        self.assertEqual(result, 2)

    def test_signature_failure_never_checks_ci_or_stages(self):
        with patch.object(candidate.release_policy, "read_trust",
                          return_value=(SIGNER,)), \
             patch.object(candidate.release_policy, "verify_signed_tag",
                          side_effect=ValueError("GPG signature invalid")), \
             patch.object(candidate, "fetch_ci_json",
                          side_effect=AssertionError("network must not happen")):
            self.assertEqual(candidate.main(["--tag", "v3.0.0", "--stage"]), 2)

    def test_ci_failure_never_stages(self):
        with patch.object(candidate.release_policy, "read_trust",
                          return_value=(SIGNER,)), \
             patch.object(candidate.release_policy, "verify_signed_tag",
                          return_value={"tag": "v3.0.0", "commit": SHA,
                                        "trusted_fingerprint": SIGNER}), \
             patch.object(candidate, "fetch_ci_json", return_value={"workflow_runs": []}), \
             patch.object(candidate, "stage_release",
                          side_effect=AssertionError("stage must not happen")):
            self.assertEqual(candidate.main(["--tag", "v3.0.0", "--stage"]), 2)


@unittest.skipUnless(subprocess.run(["git", "--version"], capture_output=True).returncode == 0,
                     "Git required for signed tree staging smoke tests")
class CandidateStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "app"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        for name, content in (("agent.py", b"# agent\n"),
                              ("gui.py", b"# gui\n"),
                              ("README.md", b"safe\n")):
            (self.repo / name).write_bytes(content)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Tester",
                        "-c", "user.email=test@invalid.example", "commit", "-qm",
                        "fixture"], check=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.stages = self.base / "candidates"

    def tearDown(self):
        self.temp.cleanup()

    def test_authenticated_tree_staged_outside_app_and_unchanged(self):
        source = (self.repo / "agent.py").read_bytes()
        ci = candidate.verify_ci(self.commit, ci_fixture(self.commit))
        output = candidate.stage_release(self.repo, self.commit, "v3.0.0", SIGNER,
                                         ci, self.stages)
        self.assertEqual((output / "app" / "agent.py").read_bytes(), source)
        self.assertEqual((self.repo / "agent.py").read_bytes(), source)
        self.assertFalse((output / "app" / "state.sqlite3").exists())
        manifest = json.loads((output / "release-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "staged_only_never_activated")
        self.assertEqual(manifest["commit"], self.commit)
        self.assertEqual(manifest["files_sha256"]["agent.py"], hashlib.sha256(source).hexdigest())
        self.assertEqual(len(list(self.stages.iterdir())), 1)

    def test_main_check_mode_never_activates_or_writes(self):
        with patch.object(candidate.release_policy, "read_trust",
                          return_value=(SIGNER,)), \
             patch.object(candidate.release_policy, "verify_signed_tag",
                          return_value={"tag": "v3.0.0", "commit": self.commit,
                                        "trusted_fingerprint": SIGNER}), \
             patch.object(candidate, "fetch_ci_json", return_value=ci_fixture(self.commit)), \
             patch.object(candidate, "stage_release",
                          side_effect=AssertionError("no stage for check-only")):
            rc = candidate.main(["--tag", "v3.0.0", "--repo", str(self.repo)])
        self.assertEqual(rc, 0)
        self.assertFalse(self.stages.exists())

    def test_staging_without_complete_ci_evidence_is_refused(self):
        with self.assertRaisesRegex(ValueError, "complete CI"):
            candidate.stage_release(self.repo, self.commit, "v3.0.0", SIGNER,
                                    {}, self.stages)
        self.assertFalse(self.stages.exists())

    def test_isolated_python_launch_parses_command_line(self):
        script = Path(__file__).resolve().parents[1] / "release_candidate.py"
        result = subprocess.run([os.sys.executable, "-I", str(script), "--help"],
                                capture_output=True, text=True, errors="replace", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--stage", result.stdout)
    def test_stage_inside_app_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            candidate.stage_release(self.repo, self.commit, "v3.0.0", SIGNER,
                                    candidate.verify_ci(self.commit, ci_fixture(self.commit)), self.repo / "staging")
        self.assertFalse((self.repo / "staging").exists())

    def test_corrupted_artifact_refused_and_partials_removed(self):
        with patch.object(candidate, "_file_hash_matches_git", return_value=False):
            with self.assertRaisesRegex(ValueError, "differs"):
                candidate.stage_release(self.repo, self.commit, "v3.0.0", SIGNER,
                                        candidate.verify_ci(self.commit, ci_fixture(self.commit)), self.stages)
        self.assertEqual(list(self.stages.iterdir()), [])

    def test_missing_application_files_refused(self):
        with patch.object(candidate, "_expected_tree", return_value={"README.md": ("a" * 40, 5)}):
            with self.assertRaisesRegex(ValueError, "omits|unexpected|differs"):
                candidate.stage_release(self.repo, self.commit, "v3.0.0", SIGNER,
                                        candidate.verify_ci(self.commit, ci_fixture(self.commit)), self.stages)


if __name__ == "__main__":
    unittest.main()
