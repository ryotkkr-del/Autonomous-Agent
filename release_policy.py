"""Phase 1 of P0-4: read-only signed-release tag verification.

This tool NEVER installs or executes fetched code. The maintainer's public
signing-key fingerprint must be pinned independently in a trust file outside
the Git checkout. GitHub repository access alone is not the trust root.

Usage:
    python release_policy.py --tag v3.0.0
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = "ryotkkr-del/Autonomous-Agent"
VERSION_TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
FINGERPRINT = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
VALIDSIG = re.compile(r"\[GNUPG:\]\s+VALIDSIG\s+([0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?:\s|$)")


def default_trust_path() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise ValueError("LOCALAPPDATA is unavailable; refusing release verification")
        return Path(local) / "AutonomousAgent" / "release-trust.json"
    return Path.home() / ".config" / "AutonomousAgent" / "release-trust.json"


def read_trust(path: Path, repository_root: Path) -> tuple[str, ...]:
    """Do not accept an attacker-editable trust root inside a Git checkout."""
    path = path.absolute()
    root = repository_root.resolve(strict=True)
    if path.is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError("independent release trust file missing or unsafe")
    if path.stat().st_size > 4096:
        raise ValueError("release trust file exceeds maximum size")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("repository") != REPOSITORY
            or not isinstance(data.get("trusted_fingerprints"), list)
            or not 1 <= len(data["trusted_fingerprints"]) <= 5):
        raise ValueError("invalid release trust configuration")
    fingerprints = data["trusted_fingerprints"]
    if any(not isinstance(x, str) or FINGERPRINT.fullmatch(x) is None for x in fingerprints):
        raise ValueError("invalid release signing-key fingerprint")
    return tuple(x.upper() for x in fingerprints)


def _run_git(root: Path, args: list[str], *, runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(
        ["git", "-C", str(root), "-c", "core.fsmonitor=false",
         "-c", "credential.helper=", "-c", "core.hooksPath=NUL" if os.name == "nt" else "core.hooksPath=/dev/null",
         *args],
        capture_output=True, text=True, errors="replace", timeout=20, check=False,
    )


def verify_signed_tag(
    root: Path, tag: str, trusted_fingerprints: tuple[str, ...],
    *, runner=subprocess.run,
) -> dict[str, str]:
    if not isinstance(tag, str) or VERSION_TAG.fullmatch(tag) is None:
        raise ValueError("release tag must be a stable version like v3.0.0")
    if not trusted_fingerprints:
        raise ValueError("release signing key has not been pinned")
    root = Path(root).resolve(strict=True)
    typ = _run_git(root, ["cat-file", "-t", "refs/tags/" + tag], runner=runner)
    if typ.returncode != 0 or typ.stdout.strip() != "tag":
        raise ValueError("release tag is missing or is not an annotated signed tag")
    result = _run_git(root, ["verify-tag", "--raw", "refs/tags/" + tag], runner=runner)
    if result.returncode != 0:
        raise ValueError("release tag signature verification failed")
    fingerprints = {x.upper() for x in VALIDSIG.findall(result.stderr + "\n" + result.stdout)}
    if not fingerprints.intersection(trusted_fingerprints):
        raise ValueError("release tag was not signed by an independently trusted key")
    peeled = _run_git(root, ["rev-parse", "--verify", "refs/tags/" + tag + "^{commit}"], runner=runner)
    commit = peeled.stdout.strip()
    if peeled.returncode != 0 or SHA.fullmatch(commit) is None:
        raise ValueError("signed release tag does not resolve to a commit")
    return {"tag": tag, "commit": commit, "signature": "verified",
            "trusted_fingerprint": sorted(fingerprints.intersection(trusted_fingerprints))[0],
            "action": "check_only_no_install"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify a signed Git release tag without installing it")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--trust-file", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        trust_path = args.trust_file or default_trust_path()
        trusted = read_trust(trust_path, args.repo)
        result = verify_signed_tag(args.repo, args.tag, trusted)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print("RELEASE REFUSED:", str(exc)[:300], file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("CHECK ONLY: no files, jobs, database, or running app were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
