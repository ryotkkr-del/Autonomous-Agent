"""P0-4 stage 4c: read-only maintenance *check*, never an updater.

The user must first create the existing STOP marker using the documented
agent CLI and have an existing agent.lock. The guard takes the same OS lock
used by agent.single_runner and holds it for the complete context.

This does NOT prove the GUI, background processes, unrelated workers, or
other applications have stopped; it does NOT install or execute a release.
An installer may not rely on a check result after the context has exited.
No arbitrary root is exposed through the command-line interface.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import sys


APP_ROOT = Path(__file__).resolve().parent
MAX_LOCK_BYTES = 4096
MAX_STOP_BYTES = 128


def _plain(path: Path, *, directory: bool) -> os.stat_result:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode) or (
        getattr(st, "st_file_attributes", 0) &
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise ValueError("maintenance path is a symlink or reparse point")
    if directory:
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError("maintenance root has a non-directory component")
    elif not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise ValueError("maintenance marker must be an ordinary, unlinked file")
    return st


def _check_root(root: Path) -> Path:
    raw = Path(root).absolute()
    # Check original path components before resolving them.
    for parent in (raw, *raw.parents):
        _plain(parent, directory=True)
    return raw.resolve(strict=True)


def _check_stop(root: Path) -> None:
    marker = root / "STOP"
    st = _plain(marker, directory=False)
    if st.st_size > MAX_STOP_BYTES:
        raise ValueError("maintenance STOP marker is unexpectedly large")


def _check_lock_path(root: Path) -> os.stat_result:
    path = root / "agent.lock"
    st = _plain(path, directory=False)
    # The running agent writes one byte before locking on Windows.
    # Refuse a missing/empty file instead of modifying the installation.
    if not 1 <= st.st_size <= MAX_LOCK_BYTES:
        raise ValueError("maintenance lock must exist and be nonempty")
    return st


@contextmanager
def hold_stop_lock(root: Path | None = None):
    """Guard is valid ONLY while inside the with block. No writes by design."""
    selected = _check_root(root if root is not None else APP_ROOT)
    _check_stop(selected)
    original = _check_lock_path(selected)
    path = selected / "agent.lock"
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    acquired = False
    try:
        current = os.fstat(fd)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or
                (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)):
            raise ValueError("agent lock was replaced during the check")
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("agent is busy; maintenance refused") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("agent is busy; maintenance refused") from exc
        acquired = True
        # Re-check while holding the lock; reject replaced lock path.
        after = _check_lock_path(selected)
        if (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("agent lock changed while acquiring maintenance guard")
        _check_stop(selected)
        try:
            yield {"status": "held_test_only", "application_changes": False}
            # If STOP was revoked during guarded work, fail closed. This
            # must NOT be interpreted as an atomic app activation boundary.
            _check_stop(selected)
            after = _check_lock_path(selected)
            if (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("agent lock changed during maintenance guard")
        finally:
            pass
    finally:
        if acquired:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check existing STOP and agent.lock; do NOT install or update")
    parser.add_argument("--check", action="store_true", required=True,
                        help="hold lock only during this check")
    args = parser.parse_args(argv)
    try:
        with hold_stop_lock() as result:
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError) as exc:
        print("MAINTENANCE REFUSED:", str(exc)[:260], file=sys.stderr)
        return 2
    print("CHECK ENDED: guard released; result is not a future update permit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
