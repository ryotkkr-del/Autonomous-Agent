"""P0-4 isolated upgrade/rollback fault-injection model (NOT an updater).

All writes are to a newly created TemporaryDirectory containing synthetic code
and data. No user-provided path, signed candidate, live agent, or running code is
accepted. This exercises the transaction protocol without activating releases.

On POSIX, file and directory fsync is attempted. On Windows, os.replace only
models same-directory replacement; power-loss durability remains unproven.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import uuid


class SimulatedInterruption(RuntimeError):
    """Injected stop: caller must explicitly invoke recover()."""


class Trial:
    """A disposable switch model; cannot target an existing install."""

    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="autonomous-agent-switch-trial-")
        self.root = Path(self._temp.name)
        self._initialize()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._temp.cleanup()

    @property
    def data(self) -> Path:
        return self.root / "data"

    def _initialize(self):
        versions = self.root / "versions"
        versions.mkdir()
        for generation, text in (("old", "# old, never execute\n"),
                                 ("new", "# new, never execute\n")):
            directory = versions / generation
            directory.mkdir()
            files = {"agent.py": text.encode(), "gui.py": b"# synthetic GUI\n"}
            for name, contents in files.items():
                (directory / name).write_bytes(contents)
            manifest = {name: hashlib.sha256(contents).hexdigest()
                        for name, contents in files.items()}
            (directory / "checksums.json").write_text(
                json.dumps(manifest, sort_keys=True), encoding="utf-8")
        self.data.mkdir()
        with sqlite3.connect(self.data / "state.sqlite3") as db:
            db.execute("CREATE TABLE progress (value TEXT NOT NULL)")
            db.execute("INSERT INTO progress VALUES ('keep me')")
        (self.data / "workspace").mkdir()
        (self.data / "workspace" / "note.txt").write_text("unchanged", encoding="utf-8")
        self._atomic_json("current.json", {"generation": "old"})

    def _plain(self, path: Path, *, directory=False):
        # All names are fixed code-defined paths; check links and reparse points.
        st = path.lstat()
        if (stat.S_ISLNK(st.st_mode) or
            getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("trial path is a link or reparse point")
        if directory and not stat.S_ISDIR(st.st_mode):
            raise ValueError("trial path is not a directory")
        if not directory and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1):
            raise ValueError("trial path is not an independent ordinary file")
        return st

    def _read(self, name: str) -> dict:
        path = self.root / name
        self._plain(path)
        if path.stat().st_size > 4096:
            raise ValueError("trial metadata exceeds size limit")
        def unique(pairs):
            d = {}
            for key, value in pairs:
                if key in d:
                    raise ValueError("duplicate trial metadata")
                d[key] = value
            return d
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise ValueError("malformed trial metadata")
        return value

    def _sync_parent(self):
        if os.name != "nt":
            fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _atomic_json(self, name: str, obj: dict):
        if name not in {"current.json", "transaction.json"}:
            raise ValueError("invalid trial metadata name")
        path = self.root / name
        if path.exists() or os.path.lexists(path):
            self._plain(path)
        scratch = self.root / (".tmp-" + uuid.uuid4().hex)
        try:
            with scratch.open("xb") as stream:
                stream.write((json.dumps(obj, sort_keys=True) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(scratch, path)
            self._sync_parent()
        finally:
            scratch.unlink(missing_ok=True)

    def _verify_generation(self, generation: str):
        if generation not in {"old", "new"}:
            raise ValueError("unknown code generation")
        root = self.root / "versions" / generation
        self._plain(self.root / "versions", directory=True)
        self._plain(root, directory=True)
        if {p.name for p in root.iterdir()} != {"agent.py", "gui.py", "checksums.json"}:
            raise ValueError("synthetic code files added or missing")
        manifest = root / "checksums.json"
        self._plain(manifest)
        checksums = json.loads(manifest.read_text(encoding="utf-8"))
        if (not isinstance(checksums, dict) or
                set(checksums) != {"agent.py", "gui.py"}):
            raise ValueError("synthetic code manifest is invalid")
        for name, expected in checksums.items():
            file = root / name
            self._plain(file)
            if file.stat().st_size > 1024 * 1024:
                raise ValueError("synthetic code file too large")
            if not isinstance(expected, str) or len(expected) != 64 or (
                    hashlib.sha256(file.read_bytes()).hexdigest() != expected):
                raise ValueError("synthetic code does not match manifest")

    def current(self):
        value = self._read("current.json")
        if set(value) != {"generation"} or value["generation"] not in {"old", "new"}:
            raise ValueError("invalid active generation")
        return value["generation"]

    def _transaction(self):
        value = self._read("transaction.json")
        if (set(value) != {"before", "after", "phase"} or
                value["before"] != "old" or value["after"] != "new" or
                value["phase"] not in {"prepared", "verified"}):
            raise ValueError("invalid journal; refusing unsafe recovery")
        return value

    def _remove_journal(self):
        path = self.root / "transaction.json"
        self._plain(path)
        path.unlink()
        self._sync_parent()

    def switch(self, fail_at: str | None = None):
        """Trial only: alter a synthetic generation pointer, never execute code."""
        if fail_at not in {None, "after_prepare", "after_pointer", "after_verify"}:
            raise ValueError("unsupported fault-injection phase")
        if os.path.lexists(self.root / "transaction.json"):
            raise ValueError("pending journal requires explicit recovery")
        if self.current() != "old":
            raise ValueError("trial is not on the old generation")
        self._verify_generation("old")
        self._verify_generation("new")
        self._atomic_json("transaction.json", {"before": "old", "after": "new", "phase": "prepared"})
        if fail_at == "after_prepare":
            raise SimulatedInterruption("synthetic crash after journal preparation")
        try:
            self._atomic_json("current.json", {"generation": "new"})
            if fail_at == "after_pointer":
                raise SimulatedInterruption("synthetic crash after pointer replacement")
            self._verify_generation("new")
            if fail_at == "after_verify":
                raise SimulatedInterruption("synthetic crash before commit marker")
            self._atomic_json("transaction.json", {"before": "old", "after": "new", "phase": "verified"})
            self._remove_journal()
        except SimulatedInterruption:
            # A process kill cannot recover inline; exercise restart separately.
            raise
        except Exception:
            self.recover()
            raise

    def recover(self):
        """Conservatively undo uncommitted updates. Never touches trial data."""
        if not os.path.lexists(self.root / "transaction.json"):
            self._verify_generation(self.current())
            return self.current()
        tx = self._transaction()
        # Keep the new version only when the verified intent is durable and
        # its bytes remain valid; all interrupted uncommitted moves revert.
        selected = "new" if tx["phase"] == "verified" else "old"
        self._verify_generation(selected)
        self._atomic_json("current.json", {"generation": selected})
        self._remove_journal()
        return selected


if __name__ == "__main__":
    # Do not expose a CLI action resembling activation to avoid misuse.
    raise SystemExit("P0-4 experiment only: run python -m unittest discover -s tests")