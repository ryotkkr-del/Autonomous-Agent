"""P0-4 stage 4, read-only pre-activation integrity check.

This script deliberately DOES NOT install, switch, execute or roll back an app.
It revalidates independently trusted signed source, current CI, and EVERY
staged byte immediately before a future separate activation mechanism.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_candidate as candidate
import release_policy

MAX_MANIFEST_BYTES = 2_000_000


def _require_plain(path: Path, *, directory: bool) -> os.stat_result:
    """Reject links, junctions/reparse points, special files, and hardlinks."""
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or (
        st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        if hasattr(st, "st_file_attributes") else False
    ):
        raise ValueError("symlink or reparse point in candidate")
    if directory:
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError("expected ordinary candidate directory")
    elif not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise ValueError("expected ordinary, non-hardlinked candidate file")
    return st


def _validated_location(path: Path, repo: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("candidate must have a canonical absolute path")
    # Inspect every original path component BEFORE resolving: resolve() alone
    # would silently follow junctions or symlinks.
    for parent in (path, *path.parents):
        _require_plain(parent, directory=True)
    resolved = path.resolve(strict=True)
    if resolved.is_relative_to(repo.resolve(strict=True)):
        raise ValueError("candidate must be outside the Git checkout")
    return resolved


def _read_plain(path: Path, *, maximum: int) -> bytes:
    before = _require_plain(path, directory=False)
    if before.st_size > maximum:
        raise ValueError("candidate file exceeds size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError("candidate changed during verification")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        after = os.fstat(fd)
        if (len(data) > maximum or len(data) != opened.st_size
                or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns,
                    opened.st_ino) !=
                   (after.st_size, after.st_mtime_ns, after.st_ctime_ns,
                    after.st_ino)):
            raise ValueError("candidate changed during verification")
        return data
    finally:
        os.close(fd)


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field in release metadata")
        result[key] = value
    return result


def _inventory(app: Path) -> tuple[set[str], set[str]]:
    files, directories = set(), set()
    stack = [(app, "")]
    while stack:
        current, prefix = stack.pop()
        _require_plain(current, directory=True)
        for entry in current.iterdir():
            name = prefix + entry.name
            candidate._tree_path(name)
            st = entry.lstat()
            if stat.S_ISDIR(st.st_mode):
                _require_plain(entry, directory=True)
                directories.add(name)
                stack.append((entry, name + "/"))
            else:
                _require_plain(entry, directory=False)
                files.add(name)
                if len(files) > candidate.MAX_FILES:
                    raise ValueError("too many candidate files")
    return files, directories


def verify_staged_candidate(staged: Path, repo: Path,
                            trust_file: Path | None = None) -> dict:
    """Read-only recheck. Output is evidence, NOT approval to run code."""
    repo = Path(repo).resolve(strict=True)
    staged = _validated_location(Path(staged), repo)
    if {item.name for item in staged.iterdir()} != {"app", "release-metadata.json"}:
        raise ValueError("unexpected contents beside staged application")
    manifest_bytes = _read_plain(staged / "release-metadata.json",
                                 maximum=MAX_MANIFEST_BYTES)
    metadata = json.loads(manifest_bytes.decode("utf-8"),
                          object_pairs_hook=_unique_json_pairs)
    if (not isinstance(metadata, dict)
            or metadata.get("format") != "autonomous-agent-staged-release-v1"
            or metadata.get("status") != "staged_only_never_activated"
            or metadata.get("source") != release_policy.REPOSITORY):
        raise ValueError("invalid staged release metadata")
    tag, commit, signer = (metadata.get(k) for k in
                           ("tag", "commit", "signing_fingerprint"))
    if (not isinstance(tag, str) or release_policy.VERSION_TAG.fullmatch(tag) is None
            or not isinstance(commit, str) or release_policy.SHA.fullmatch(commit) is None
            or not isinstance(signer, str)
            or release_policy.FINGERPRINT.fullmatch(signer) is None):
        raise ValueError("invalid staged release identity")

    # Trust and signed-tag verification are repeated, not copied from manifest.
    fingerprints = release_policy.read_trust(
        trust_file or release_policy.default_trust_path(), repo)
    signed = release_policy.verify_signed_tag(repo, tag, fingerprints)
    if signed["commit"] != commit or signed["trusted_fingerprint"] != signer:
        raise ValueError("staged identity differs from independently signed tag")
    actual_ci = candidate.verify_ci(commit, candidate.fetch_ci_json(commit))
    if metadata.get("ci") != actual_ci:
        raise ValueError("CI evidence differs from current exact-commit result")

    expected = candidate._expected_tree(repo, commit)
    recorded = metadata.get("files_sha256")
    if not isinstance(recorded, dict) or set(recorded) != set(expected):
        raise ValueError("staged manifest file list differs from signed Git tree")
    app = staged / "app"
    found, dirs = _inventory(app)
    expected_dirs = set()
    for name in expected:
        parts = PurePosixPath(name).parts
        expected_dirs.update("/".join(parts[:n]) for n in range(1, len(parts)))
    if found != set(expected) or dirs != expected_dirs:
        raise ValueError("staged tree contains added, missing or unexpected paths")

    bytes_checked = 0
    for name, (blob_sha, expected_size) in sorted(expected.items()):
        data = _read_plain(app.joinpath(*PurePosixPath(name).parts),
                           maximum=candidate.MAX_FILE_BYTES)
        digest = hashlib.sha256(data).hexdigest()
        if (len(data) != expected_size
                or not candidate._file_hash_matches_git(data, blob_sha)
                or recorded[name] != digest):
            raise ValueError("staged code differs from signed Git object: " + name)
        bytes_checked += len(data)
        if bytes_checked > candidate.MAX_TREE_BYTES:
            raise ValueError("candidate size exceeds safety limit")
    return {
        "status": "verified_read_only_not_activated",
        "tag": tag, "commit": commit, "files_verified": len(expected),
        "bytes_verified": bytes_checked,
        "next_step": "activation remains disabled pending safe switching and rollback tests",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only staged release integrity preflight")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--trust-file", type=Path)
    args = parser.parse_args(argv)
    try:
        outcome = verify_staged_candidate(args.candidate, args.repo, args.trust_file)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError,
            subprocess.TimeoutExpired, urllib.error.URLError) as exc:
        print("PREFLIGHT REFUSED:", str(exc)[:300], file=sys.stderr)
        return 2
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    print("READ ONLY: nothing installed, executed, switched or rolled back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
