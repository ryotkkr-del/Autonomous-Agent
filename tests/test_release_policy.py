"""P0-4 unsigned-update rejection and safe launcher regression tests.

No Git fetch, model calls, release installation, or user workspace changes.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_policy_under_test", PROJECT / "release_policy.py")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)
SIGNER = "A" * 40
OTHER_SIGNER = "B" * 40


def fake_git(verified=True, signer=SIGNER, annotated=True, commit="1" * 40):
    commands = []

    def runner(argv, **kwargs):
        commands.append(argv)
        tail = argv[-3:]
        if "cat-file" in tail or "cat-file" in argv:
            return subprocess.CompletedProcess(argv, 0 if annotated else 1,
                                               "tag\n" if annotated else "commit\n", "")
        if "verify-tag" in argv:
            return subprocess.CompletedProcess(
                argv, 0 if verified else 1, "",
                "[GNUPG:] VALIDSIG " + signer + " 2026 0 4 0 1 8 00 " + signer + "\n")
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, commit + "\n", "")
        raise AssertionError("unexpected command: " + str(argv))
    return runner, commands


class ReleasePolicyTests(unittest.TestCase):
    def test_unsigned_tag_is_refused(self):
        runner, calls = fake_git(verified=False)
        with self.assertRaisesRegex(ValueError, "signature"):
            policy.verify_signed_tag(PROJECT, "v3.0.0", (SIGNER,), runner=runner)
        self.assertEqual(len(calls), 2)

    def test_lightweight_tag_is_refused(self):
        runner, calls = fake_git(annotated=False)
        with self.assertRaisesRegex(ValueError, "annotated"):
            policy.verify_signed_tag(PROJECT, "v3.0.0", (SIGNER,), runner=runner)
        self.assertEqual(len(calls), 1)

    def test_unknown_signer_is_refused_even_if_gpg_verifies(self):
        runner, _ = fake_git(signer=OTHER_SIGNER)
        with self.assertRaisesRegex(ValueError, "independently trusted"):
            policy.verify_signed_tag(PROJECT, "v3.0.0", (SIGNER,), runner=runner)

    def test_pinned_signer_verification_returns_only_metadata(self):
        runner, calls = fake_git()
        result = policy.verify_signed_tag(PROJECT, "v3.0.0", (SIGNER,), runner=runner)
        self.assertEqual(result["commit"], "1" * 40)
        self.assertEqual(result["action"], "check_only_no_install")
        self.assertEqual(result["trusted_fingerprint"], SIGNER)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("checkout" not in cmd and "merge" not in cmd for cmd in calls))

    def test_tag_input_is_strictly_validated_before_git(self):
        for invalid in ("main", "refs/tags/v1.2.3", "v1.2.3^{}", "v1.2.3;echo bad",
                        "v01.2.3", "v1.2.3-rc1", "../v1.2.3", "v1.2.3\n"):
            with self.subTest(tag=invalid):
                with self.assertRaisesRegex(ValueError, "release tag"):
                    policy.verify_signed_tag(PROJECT, invalid, (SIGNER,), runner=lambda *a, **k:
                                             self.fail("Git called with invalid tag"))

    def test_trust_is_independent_from_git_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            checkout = root / "repo"
            checkout.mkdir()
            external = root / "trusted.json"
            config = {"repository": policy.REPOSITORY, "trusted_fingerprints": [SIGNER]}
            external.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(policy.read_trust(external, checkout), (SIGNER,))
            internal = checkout / "trust.json"
            internal.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "independent"):
                policy.read_trust(internal, checkout)
            wrong_repo = external
            wrong_repo.write_text(json.dumps({"repository": "attacker/agent",
                                              "trusted_fingerprints": [SIGNER]}))
            with self.assertRaisesRegex(ValueError, "invalid release trust"):
                policy.read_trust(wrong_repo, checkout)

    def test_trust_parent_symlink_into_checkout_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            checkout = root / "repo"
            checkout.mkdir()
            inside = checkout / "trust.json"
            inside.write_text(json.dumps({"repository": policy.REPOSITORY,
                                          "trusted_fingerprints": [SIGNER]}))
            parent_link = root / "alias"
            try:
                parent_link.symlink_to(checkout, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(ValueError, "independent"):
                policy.read_trust(parent_link / "trust.json", checkout)

    def test_no_independent_trust_fails_before_git(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(policy, "default_trust_path", return_value=Path(d) / "missing.json"), \
                 patch.object(policy, "verify_signed_tag",
                              side_effect=AssertionError("must not invoke Git")):
                self.assertEqual(policy.main(["--tag", "v3.0.0", "--repo", str(PROJECT)]), 2)

    def test_developer_update_requires_typed_confirmation(self):
        source = (PROJECT / "sync.ps1").read_text(encoding="utf-8")
        self.assertIn("if ($DevMain)", source)
        self.assertIn("DEV-UPDATE", source)
        self.assertIn("Read-Host", source)
        self.assertIn("merge --ff-only", source)
        self.assertIn("if ($CheckReleaseTag)", source)
        self.assertIn("release_policy.py", source)
        self.assertIn("if ($Launch)", source)
        self.assertIn("mainの自動取得・更新は停止中", source)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell-only safe-launch check")
    def test_powershell_safe_default_does_not_fetch_or_launch(self):
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(PROJECT / "sync.ps1")],
            input="", capture_output=True, timeout=30, text=True, errors="replace"
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("更新しました", proc.stdout)
        self.assertTrue(
            "main" in proc.stdout or "main" in proc.stderr,
            "safe-default message not emitted"
        )


if __name__ == "__main__":
    unittest.main()
