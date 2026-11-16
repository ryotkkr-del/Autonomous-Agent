"""Offline P0-4 stage 4: candidate preflight must fail closed."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import release_candidate as staging
import release_preflight as preflight

SIGNER = "A" * 40


def ci_fixture(commit):
    return {"workflow_runs": [
        {
            "path": name, "head_sha": commit, "head_branch": "main",
            "event": "push", "id": i + 1, "run_attempt": 1,
            "status": "completed", "conclusion": "success",
            "repository": {"full_name": staging.REPOSITORY},
        } for i, name in enumerate(sorted(staging.WORKFLOWS))
    ]}


@unittest.skipUnless(
    subprocess.run(["git", "--version"], capture_output=True).returncode == 0,
    "Git required to check signed Git object bytes",
)
class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "-C", str(self.repo), "init", "-q"], check=True)
        (self.repo / "agent.py").write_text("print('hello')\n", encoding="utf-8")
        (self.repo / "gui.py").write_text("# gui\n", encoding="utf-8")
        (self.repo / "README.md").write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Tester",
                        "-c", "user.email=test@invalid.example",
                        "commit", "-qm", "fixture"], check=True)
        self.commit = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True).strip()
        self.ci = ci_fixture(self.commit)
        self.stage = staging.stage_release(
            self.repo, self.commit, "v3.0.0", SIGNER,
            staging.verify_ci(self.commit, self.ci),
            self.base / "stages")
        self.manifest = self.stage / "release-metadata.json"
        self.app = self.stage / "app"

    def check(self, *, ci=None, trusted=True):
        with patch.object(preflight.release_policy, "read_trust",
                          return_value=(SIGNER,) if trusted else ()), \
             patch.object(preflight.release_policy, "verify_signed_tag",
                          return_value={"tag": "v3.0.0", "commit": self.commit,
                                        "trusted_fingerprint": SIGNER}), \
             patch.object(preflight.candidate, "fetch_ci_json",
                          return_value=ci if ci is not None else self.ci):
            return preflight.verify_staged_candidate(self.stage, self.repo)

    def test_clean_staging_passes_without_modifying_app_or_manifest(self):
        original = {p.name: p.read_bytes() for p in self.app.iterdir() if p.is_file()}
        metadata = self.manifest.read_bytes()
        result = self.check()
        self.assertEqual(result["status"], "verified_read_only_not_activated")
        self.assertEqual(result["files_verified"], 3)
        self.assertEqual(self.manifest.read_bytes(), metadata)
        self.assertEqual(original, {p.name: p.read_bytes()
                                    for p in self.app.iterdir() if p.is_file()})

    def test_tampered_code_is_blocked_even_if_manifest_digest_is_rewritten(self):
        self.app.joinpath("agent.py").write_text("print('tampered')\n", encoding="utf-8")
        m = json.loads(self.manifest.read_text(encoding="utf-8"))
        m["files_sha256"]["agent.py"] = hashlib.sha256(
            self.app.joinpath("agent.py").read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(m), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "signed Git object"):
            self.check()

    def test_missing_file_extra_file_and_empty_directory_rejected(self):
        with self.subTest("missing"):
            (self.app / "README.md").unlink()
            with self.assertRaisesRegex(ValueError, "added, missing"):
                self.check()
        (self.app / "README.md").write_text("original\n", encoding="utf-8")
        with self.subTest("extra"):
            (self.app / "payload.py").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "added, missing"):
                self.check()
        (self.app / "payload.py").unlink()
        with self.subTest("extra folder"):
            (self.app / "extra").mkdir()
            with self.assertRaisesRegex(ValueError, "added, missing"):
                self.check()

    def test_manifest_metadata_and_duplicate_json_keys_rejected(self):
        m = json.loads(self.manifest.read_text(encoding="utf-8"))
        m["commit"] = "2" * 40
        self.manifest.write_text(json.dumps(m), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "signed tag"):
            self.check()
        self.manifest.write_text('{"status":"ok","status":"bad"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.check()

    def test_missing_trust_prevents_ci_lookup(self):
        with patch.object(preflight.release_policy, "read_trust",
                          side_effect=ValueError("independent trust missing")), \
             patch.object(preflight.candidate, "fetch_ci_json",
                          side_effect=AssertionError("must not fetch CI")):
            with self.assertRaisesRegex(ValueError, "independent trust"):
                preflight.verify_staged_candidate(self.stage, self.repo)

    def test_ci_rerun_failure_prevents_activation_eligibility(self):
        bad = ci_fixture(self.commit)
        bad["workflow_runs"][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "not successful"):
            self.check(ci=bad)

    def test_manifest_CI_evidence_mutation_rejected(self):
        m = json.loads(self.manifest.read_text(encoding="utf-8"))
        first = next(iter(m["ci"]))
        m["ci"][first]["run_id"] = 999
        self.manifest.write_text(json.dumps(m), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CI evidence"):
            self.check()

    def test_candidate_must_be_outside_repo(self):
        relocated = self.repo / "copied-stage"
        shutil.copytree(self.stage, relocated)
        with patch.object(preflight.release_policy, "read_trust",
                          side_effect=AssertionError("do not verify trust")):
            with self.assertRaisesRegex(ValueError, "outside"):
                preflight.verify_staged_candidate(relocated, self.repo)

    def test_staged_symlink_rejected(self):
        path = self.app / "README.md"
        path.unlink()
        try:
            path.symlink_to(self.repo / "README.md")
        except OSError:
            self.skipTest("symlink creation unavailable on this Windows runner")
        with self.assertRaisesRegex(ValueError, "symlink|non-hardlinked"):
            self.check()

    def test_unexpected_outer_file_refused(self):
        (self.stage / "execute.bat").write_text("echo unsafe", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected contents"):
            self.check()


if __name__ == "__main__":
    unittest.main()
