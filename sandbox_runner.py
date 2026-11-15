"""Fail-closed Docker isolation for executing untrusted generated Python tests.

This is a stronger containment boundary than a Python subprocess, not a proof
of perfect isolation. Requires Docker Desktop in Linux-container mode (Windows)
or Docker Engine (Linux), and the pre-pulled official python:3.11-slim image.
No Docker daemon access, host credentials or writable host files are mounted
into the test container.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import subprocess

IMAGE = "python:3.11-slim"
CONTAINER_TIMEOUT = 45
MAX_OUTPUT = 12000
CONTAINER_PREFIX = "autonomous-agent-test-"


def availability():
    """No auto-install, daemon start or image download."""
    cli = shutil.which("docker")
    if not cli:
        return False, "Docker CLI not found. Install/start Docker Desktop (Linux containers)."
    try:
        # Refuse TCP/SSH Docker daemons: mounts must be on this computer.
        if os.environ.get("DOCKER_HOST","").strip().startswith(("tcp://","ssh://","http://","https://")):
            return False, "Remote Docker hosts are not supported."
        context = subprocess.run(
            [cli, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        endpoint=context.stdout.strip()
        if context.returncode != 0 or not endpoint.startswith(("unix://","npipe://")):
            return False, "Only local Docker sockets/named pipes are supported."
        system = subprocess.run(
            [cli, "info", "--format", "{{.OSType}}"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if system.returncode != 0 or system.stdout.strip().lower()!="linux":
            return False, "Docker must be running Linux containers."
        version = subprocess.run(
            [cli, "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if version.returncode != 0 or not version.stdout.strip():
            return False, "Docker daemon is unavailable. Start Docker Desktop."
        image = subprocess.run(
            [cli, "image", "inspect", IMAGE],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if image.returncode != 0:
            return False, f"Image not present. Run manually: docker pull {IMAGE}"
        return True, "Docker daemon ready and required Python image present."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker preflight failed: {type(exc).__name__}"


def command(workspace, container_name):
    """No shell interpolation; Docker bind mount is explicitly read-only."""
    folder = Path(workspace).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("workspace must be a directory")
    cli = shutil.which("docker")
    if not cli:
        raise RuntimeError("Docker CLI missing")
    return [
        cli, "run", "--rm", "--name", container_name,
        "--pull", "never",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--pids-limit", "64",
        "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1",
        "--user", "65534:65534",
        "--mount", f"type=bind,source={folder},target=/workspace,readonly",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
        "--workdir", "/workspace",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "PYTHONUTF8=1",
        "--env", "PYTHONIOENCODING=utf-8",
        IMAGE,
        "python", "-I", "-m", "unittest", "discover",
        "-s", "/workspace/tests", "-p", "test*.py",
    ]


def _cleanup(container_name):
    """A timed-out Docker client may leave its container running."""
    cli = shutil.which("docker")
    if not cli:
        return
    try:
        subprocess.run([cli, "rm", "-f", container_name],
                       capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_tests(workspace, timeout=CONTAINER_TIMEOUT):
    """Execute only inside Docker, return ERROR instead of host fallback."""
    ready, reason = availability()
    if not ready:
        return "ERROR: sandbox unavailable: " + reason
    name = CONTAINER_PREFIX + secrets.token_hex(10)
    try:
        cmd = command(workspace, name)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, check=False, errors="replace",
        )
        output = (result.stdout + "\n" + result.stderr)[-MAX_OUTPUT:]
        import re
        if result.returncode == 0 and re.search(r"Ran\s+[1-9]\d*\s+tests?", output):
            return "TEST PASS [Docker sandbox]\n" + output
        return f"ERROR: sandbox tests failed or none found (exit={result.returncode})\n" + output
    except subprocess.TimeoutExpired:
        return f"ERROR: sandbox test timed out after {timeout}s"
    except (OSError, ValueError, RuntimeError) as exc:
        return "ERROR: sandbox execution unavailable: " + str(exc)[:400]
    finally:
        _cleanup(name)
