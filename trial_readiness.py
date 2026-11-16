"""Read-only, offline first-run preflight for limited manual trials.

This is NOT a security audit, full runtime verification, or production approval.
It never imports the agent, launches Docker/Ollama, touches SQLite contents,
creates directories, fetches code, opens sockets, or writes any files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys

APP_DIR = Path(__file__).resolve().parent
REQUIRED = (
    "agent.py", "gui.py", "sandbox_runner.py", "safety_backup.py",
    "sync.ps1", "安全に起動.bat",
)
MAX_SOURCE_FILE = 20_000_000


def _kind(path: Path, *, max_file_bytes: int | None = None) -> str:
    """Classify without following a link, including Windows reparse points."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        return "link"
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink > 1:
            return "hardlink"
        if max_file_bytes is not None and info.st_size > max_file_bytes:
            return "oversized"
        return "file"
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    return "special"


def assess(root: Path = APP_DIR, *, commands=None, tk_available=None,
           py_version=None, system_name=None) -> dict:
    """Return status categories, never filenames from workspace contents."""
    root = Path(root).absolute()
    commands = commands if commands is not None else shutil.which
    py_version = py_version if py_version is not None else sys.version_info
    system_name = system_name if system_name is not None else platform.system()
    if tk_available is None:
        try:
            tk_available = importlib.util.find_spec("tkinter") is not None
        except (ImportError, ValueError):
            tk_available = False

    blockers: list[str] = []
    warnings: list[str] = []
    facts: dict[str, object] = {}

    if any(_kind(part) != "directory" for part in (root, *root.parents)):
        blockers.append("application_root_missing_or_unsafe")
        # Do not probe through a symlink/junction or an invalid directory.
        return {
            "assessment": "not_ready",
            "blockers": blockers, "warnings": warnings,
            "observations": facts,
            "guarantees": "none",
        }

    if (py_version.major, py_version.minor) < (3, 11):
        blockers.append("python_3_11_or_later_required")
    facts["python_version"] = f"{py_version.major}.{py_version.minor}"
    facts["platform"] = system_name
    if system_name != "Windows":
        warnings.append("windows_11_manual_test_not_performed_here")

    facts["tkinter_import_discoverable"] = bool(tk_available)
    if not tk_available:
        blockers.append("tkinter_unavailable_for_gui")

    bad_sources = []
    for name in REQUIRED:
        kind = _kind(root / name, max_file_bytes=MAX_SOURCE_FILE)
        if kind != "file":
            bad_sources.append(name)
    facts["required_source_files_present_as_regular_files"] = not bad_sources
    if bad_sources:
        blockers.append("required_source_files_missing_or_unsafe")
        # This list contains only fixed, known, non-sensitive program filenames.
        facts["required_files_not_regular"] = bad_sources

    facts["git_cli_on_path"] = commands("git") is not None
    facts["ollama_cli_on_path"] = commands("ollama") is not None
    facts["docker_cli_on_path"] = commands("docker") is not None
    if not facts["git_cli_on_path"]:
        warnings.append("git_unavailable_for_source_updates")
    if not facts["ollama_cli_on_path"]:
        warnings.append("ollama_cli_not_found_ai_work_not_ready")
    if not facts["docker_cli_on_path"]:
        warnings.append("docker_cli_not_found_generated_tests_must_remain_disabled")
    else:
        warnings.append("docker_cli_found_runtime_is_not_verified")

    stop = _kind(root / "STOP")
    facts["stop_marker"] = stop
    if stop in {"link", "hardlink", "oversized", "special", "unreadable", "directory"}:
        blockers.append("unsafe_stop_marker")
    elif stop == "file":
        warnings.append("stop_marker_present_tasks_will_not_run")

    lock = _kind(root / "agent.lock")
    facts["agent_lock"] = lock
    if lock in {"link", "hardlink", "oversized", "special", "unreadable", "directory"}:
        blockers.append("unsafe_agent_lock")
    warnings.append("active_process_and_agent_lock_ownership_not_checked")

    db = _kind(root / "state.sqlite3")
    facts["existing_database"] = "present" if db == "file" else db
    if db not in {"file", "missing"}:
        blockers.append("existing_database_path_unsafe")
    elif db == "file":
        warnings.append("existing_database_not_opened_or_integrity_checked")

    workspace = _kind(root / "workspace")
    facts["workspace"] = "present" if workspace == "directory" else workspace
    if workspace not in {"missing", "directory"}:
        blockers.append("workspace_path_unsafe")
    elif workspace == "directory":
        warnings.append("existing_workspace_contents_not_inspected")

    warnings += [
        "no_network_or_model_or_docker_runtime_check_performed",
        "no_automatic_update_or_release_signature_verified",
        "run_only_as_standard_user_with_test_data",
        "do_not_enable_scheduled_or_unattended_tasks_during_trial",
    ]
    return {
        "assessment": "manual_trial_prerequisites_found" if not blockers else "not_ready",
        "blockers": blockers, "warnings": warnings, "observations": facts,
        "guarantees": "none",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline read-only preflight; does not start the agent")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = assess()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Autonomous Agent: 読み取り専用・初回試用チェック")
        print("結果:", result["assessment"])
        for item in result["blockers"]:
            print("BLOCK:", item)
        for item in result["warnings"]:
            print("NOTE:", item)
        print("この結果は安全性・実際の起動・正式運用を保証しません。")
    return 0 if not result["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
