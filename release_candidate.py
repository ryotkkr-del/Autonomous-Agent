"""P0-4 stage 3: verify a release candidate and stage only authenticated source.

Fail-closed prerequisites: independently pinned GPG signing key, signed Git tag,
same-commit successful GitHub Actions for all three security workflows, and
Git tree/file integrity. No branch checkout, installation, automatic update,
code execution, database changes, or activation is performed.

Usage:
  python release_candidate.py --tag v3.0.0
  python release_candidate.py --tag v3.0.0 --stage
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import release_policy

REPOSITORY = release_policy.REPOSITORY
WORKFLOWS = frozenset({
    ".github/workflows/tests.yml",
    ".github/workflows/benchmark.yml",
    ".github/workflows/sandbox-integration.yml",
})
MAX_CI_RESPONSE = 2_000_000
MAX_FILES = 1500
MAX_TREE_BYTES = 50_000_000
MAX_FILE_BYTES = 5_000_000
MAX_ARCHIVE_BYTES = 25_000_000
MAX_PATH_LENGTH = 220
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)
}


def default_stage_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise ValueError("LOCALAPPDATA is required for private staging")
        return Path(base) / "AutonomousAgent" / "release-candidates"
    return Path.home() / ".local" / "share" / "AutonomousAgent" / "release-candidates"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_ci_json(commit: str) -> dict:
    """Fetch bounded, fixed-origin GitHub status data. Never send user content."""
    if release_policy.SHA.fullmatch(commit) is None:
        raise ValueError("invalid commit identifier")
    url = (f"https://api.github.com/repos/{REPOSITORY}/actions/runs"
           "?head_sha=" + urllib.parse.quote(commit, safe="") + "&per_page=100")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutonomousAgent-ReleaseVerification/1",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with opener.open(request, timeout=12) as response:
        if response.status != 200:
            raise ValueError("GitHub CI status API rejected request")
        data = response.read(MAX_CI_RESPONSE + 1)
    if len(data) > MAX_CI_RESPONSE:
        raise ValueError("GitHub CI API response exceeds safety limit")
    return json.loads(data)


def verify_ci(commit: str, response: dict) -> dict[str, dict]:
    """Only completed push-to-main runs for EXACT signed commit are accepted."""
    if not isinstance(response, dict):
        raise ValueError("invalid CI response")
    runs = response.get("workflow_runs")
    if not isinstance(runs, list) or not runs or len(runs) > 100:
        raise ValueError("no bounded GitHub CI runs found")
    relevant = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        path = run.get("path")
        if not isinstance(path, str):
            continue
        workflow = path.split("@", 1)[0]
        if not workflow.startswith(REPOSITORY + "/"):
            continue
        workflow = workflow[len(REPOSITORY) + 1:]
        if workflow not in WORKFLOWS:
            continue
        if (run.get("head_sha") != commit or run.get("head_branch") != "main"
                or run.get("event") != "push"
                or not isinstance(run.get("id"), int)
                or not isinstance(run.get("run_attempt"), int)):
            continue
        # The workflow name alone is not sufficient; avoid impostor runs.
        repository = run.get("repository")
        if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
            continue
        old = relevant.get(workflow)
        if old is None or (run["id"], run["run_attempt"]) > (
            old["id"], old["run_attempt"]):
            relevant[workflow] = run
    if set(relevant) != WORKFLOWS:
        missing = sorted(WORKFLOWS - set(relevant))
        raise ValueError("required CI workflows missing: " + ", ".join(missing))
    results = {}
    for workflow, run in sorted(relevant.items()):
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise ValueError("required CI workflow not successful: " + workflow)
        results[workflow] = {
            "run_id": run["id"], "run_attempt": run["run_attempt"],
            "commit": commit, "conclusion": "success",
        }
    return results


def _tree_path(raw: str) -> str:
    if not raw or len(raw) > MAX_PATH_LENGTH or "\\" in raw or ":" in raw:
        raise ValueError("unsafe Git tree path")
    p = PurePosixPath(raw)
    if p.is_absolute() or p.as_posix() != raw or not p.parts:
        raise ValueError("unsafe Git tree path")
    for part in p.parts:
        if (part in (".", "..") or part.endswith((" ", "."))
                or part.split(".")[0].upper() in WINDOWS_RESERVED
                or any(ord(c) < 32 for c in part)):
            raise ValueError("unsafe Windows Git path")
    if p.parts[0] in {"workspace", "benchmark-results", "state.sqlite3",
                      ".git", "release-candidates", "backups"}:
        raise ValueError("release must not contain runtime data or Git internals")
    return raw


def _git(root: Path, args: list[str], *, stdout=None):
    cmd = ["git", "-C", str(root), "-c", "core.fsmonitor=false",
           "-c", "credential.helper=", "-c",
           "core.hooksPath=NUL" if os.name == "nt" else "core.hooksPath=/dev/null",
           *args]
    return subprocess.run(cmd, stdin=subprocess.DEVNULL,
                          stdout=stdout if stdout is not None else subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=45, check=False)


def _expected_tree(repo: Path, commit: str) -> dict[str, tuple[str, int]]:
    result = _git(repo, ["ls-tree", "-rz", "-l", "--full-tree", commit])
    if result.returncode:
        raise ValueError("cannot read signed release Git tree")
    if len(result.stdout) > 500_000:
        raise ValueError("release tree listing exceeds limit")
    expected = {}
    folded = set()
    total = 0
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            meta, rawname = entry.split(b"\t", 1)
            mode, kind, object_sha, size_text = meta.decode("ascii").split()
            name = _tree_path(rawname.decode("utf-8", errors="strict"))
            size = int(size_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("malformed release tree listing") from exc
        if mode not in ("100644", "100755") or kind != "blob" or size < 0:
            raise ValueError("release tree contains a link, submodule or special entry")
        if size > MAX_FILE_BYTES or release_policy.SHA.fullmatch(object_sha) is None:
            raise ValueError("release blob exceeds limit or has invalid identifier")
        key = name.casefold()
        if name in expected or key in folded:
            raise ValueError("duplicate/case-colliding release file path")
        folded.add(key)
        expected[name] = (object_sha.lower(), size)
        total += size
        if total > MAX_TREE_BYTES or len(expected) > MAX_FILES:
            raise ValueError("release exceeds file or total size limit")
    if not expected or "agent.py" not in expected or "gui.py" not in expected:
        raise ValueError("release is missing essential application files")
    return expected


def _file_hash_matches_git(data: bytes, blob_id: str) -> bool:
    value = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    if len(blob_id) == 40:
        return hashlib.sha1(value).hexdigest() == blob_id
    if len(blob_id) == 64:
        return hashlib.sha256(value).hexdigest() == blob_id
    return False


def _private_stage_root(stage_root: Path, repo: Path) -> Path:
    repo = repo.resolve(strict=True)
    target = stage_root.expanduser().absolute()
    if target.resolve().is_relative_to(repo):
        raise ValueError("release staging must be outside the Git checkout")
    for parent in (target, *target.parents):
        if parent.exists():
            st = parent.lstat()
            if (parent.is_symlink() or
                    os.name == "nt" and st.st_file_attributes &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError("staging path contains a link/reparse point")
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    return target


def stage_release(repo: Path, commit: str, tag: str, signer: str,
                  ci: dict[str, dict], stage_root: Path) -> Path:
    """Create a new code-only candidate, never touching active app or data."""
    repo = Path(repo).resolve(strict=True)
    expected = _expected_tree(repo, commit)
    root = _private_stage_root(Path(stage_root), repo)
    identity = "candidate-" + tag + "-" + commit[:12] + "-" + uuid.uuid4().hex[:8]
    draft = root / (".partial-" + identity)
    final = root / identity
    draft.mkdir(mode=0o700)
    try:
        app = draft / "app"
        app.mkdir()
        digests = {}
        for name, (blob_sha, size) in sorted(expected.items()):
            # Directly read signed Git objects, without checkout/archive
            # conversion (e.g. Windows autocrlf or export attributes).
            result = _git(repo, ["cat-file", "blob", blob_sha])
            if result.returncode != 0:
                raise ValueError("cannot retrieve signed release blob")
            data = result.stdout
            if len(data) != size or not _file_hash_matches_git(data, blob_sha):
                raise ValueError("release artifact differs from signed Git object")
            dest = app.joinpath(*PurePosixPath(name).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("xb") as stream:
                stream.write(data)
            digests[name] = hashlib.sha256(data).hexdigest()
        metadata = {
            "format": "autonomous-agent-staged-release-v1",
            "source": REPOSITORY,
            "tag": tag, "commit": commit, "signing_fingerprint": signer,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ci": ci, "files_sha256": dict(sorted(digests.items())),
            "status": "staged_only_never_activated",
        }
        (draft / "release-metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        draft.rename(final)
        return final
    except Exception:
        shutil.rmtree(draft, ignore_errors=True)
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Verify signed release, CI and code; never activate")
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--trust-file", type=Path)
    p.add_argument("--stage", action="store_true", help="stage verified code, without running it")
    p.add_argument("--stage-root", type=Path)
    args = p.parse_args(argv)
    try:
        repo = args.repo.resolve(strict=True)
        fingerprints = release_policy.read_trust(
            args.trust_file or release_policy.default_trust_path(), repo)
        verified = release_policy.verify_signed_tag(repo, args.tag, fingerprints)
        ci = verify_ci(verified["commit"], fetch_ci_json(verified["commit"]))
        if args.stage:
            destination = stage_release(
                repo, verified["commit"], args.tag, verified["trusted_fingerprint"],
                ci, args.stage_root or default_stage_root())
            print("VERIFIED CANDIDATE STAGED:", destination)
            print("Active app, SQLite, workspace, and Git HEAD were NOT changed.")
        else:
            print(json.dumps({"verification": verified, "ci": ci,
                              "status": "check_only_no_activation"}, indent=2))
            print("CHECK ONLY: no candidate was installed or activated.")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError,
            subprocess.TimeoutExpired, zipfile.BadZipFile,
            urllib.error.URLError) as exc:
        print("RELEASE REFUSED:", str(exc)[:350], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
