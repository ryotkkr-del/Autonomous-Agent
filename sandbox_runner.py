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
import tempfile

IMAGE = "python:3.11-slim"
CONTAINER_TIMEOUT = 45
MAX_OUTPUT = 12000
CONTAINER_PREFIX = "autonomous-agent-test-"


def availability(require_image=True):
    """Check local Docker Linux engine; never install, start or download."""
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
        if require_image:
            image = subprocess.run(
                [cli, "image", "inspect", IMAGE],
                capture_output=True, text=True, timeout=8, check=False,
            )
            if image.returncode != 0:
                return False, f"Image not present. Run manually: docker pull {IMAGE}"
        return True, "Docker Linux engine is ready" + (" and required Python image is present." if require_image else ".")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker preflight failed: {type(exc).__name__}"



def setup_diagnosis():
    """Return a structured, readable report for GUI and CLI setup."""
    ready, detail=availability()
    if ready:
        return {'ready':True,'stage':'ready','message':'Dockerの隔離実行環境を利用できます。',
                'detail':detail,'next_step':'Pythonテストを実行できます。'}
    if "CLI not found" in detail:
        stage="missing_cli"
        advice="Docker Desktopを公式サイトからインストールしてください。アプリが勝手にインストールすることはありません。"
    elif "Image not present" in detail:
        stage="missing_image"
        advice="「Pythonイメージを準備」を押すか、docker pull python:3.11-slim を実行してください。"
    elif "Linux containers" in detail:
        stage="wrong_container_mode"
        advice="Docker Desktopの設定をLinuxコンテナに変更してから再診断してください。"
    elif "Remote Docker" in detail or "local Docker sockets" in detail:
        stage="remote_daemon"
        advice="ローカルのDocker Desktopコンテキストに変更してください。外部サーバーには接続しません。"
    else:
        stage="daemon_unavailable"
        advice="Docker Desktopを起動し、WSL 2と仮想化が利用できるか確認してください。"
    return {'ready':False,'stage':stage,'message':'隔離環境はまだ利用できません。',
            'detail':detail,'next_step':advice}


def prepare_image(confirmed=False):
    """User-initiated Docker Hub download, never unattended and never host execution."""
    if not confirmed:
        return "ERROR: user confirmation is required to download the Python image."
    ready, detail=availability(require_image=False)
    if not ready:
        return "ERROR: Docker setup is incomplete: "+detail
    cli=shutil.which("docker")
    try:
        result=subprocess.run([cli,"pull",IMAGE],capture_output=True,text=True,
                              timeout=300,check=False,errors="replace")
    except (OSError,subprocess.TimeoutExpired) as exc:
        return "ERROR: image download failed: "+str(exc)[:300]
    if result.returncode!=0:
        return "ERROR: Docker image pull failed: "+(result.stderr or result.stdout)[-900:]
    ready,detail=availability()
    if not ready:
        return "ERROR: image download finished but verification failed: "+detail
    return "Docker image ready: "+IMAGE


def command(workspace, container_name):
    """No shell interpolation; Docker bind mount is explicitly read-only."""
    folder = Path(workspace).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("workspace must be a directory")
    cli = shutil.which("docker")
    if not cli:
        raise RuntimeError("Docker CLI missing")
    if os.name == "nt":
        user = "65534:65534"
    elif hasattr(os, "getuid") and os.getuid() != 0:
        user = f"{os.getuid()}:{os.getgid()}"
    else:
        user = "65534:65534"
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
        "--user", user,
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



def snapshot_workspace(source, destination, max_files=200, max_bytes=10_000_000):
    """Stage a read-only copy without symlinks, special files or Git internals."""
    root=Path(source).resolve(strict=True)
    target=Path(destination)
    count=0
    total=0
    for p in root.rglob("*"):
        rel=p.relative_to(root)
        if ".git" in rel.parts:
            continue
        if p.is_symlink():
            raise ValueError("sandbox snapshot refuses symbolic links")
        if p.is_dir():
            continue
        if not p.is_file():
            raise ValueError("sandbox snapshot refuses special files")
        if any(x.startswith(".") for x in rel.parts) or p.name.endswith((".agent-backup", ".agent-tmp")):
            continue
        count+=1
        total+=p.stat().st_size
        if count>max_files or total>max_bytes:
            raise ValueError("sandbox workspace exceeds snapshot size limits")
        copy_to=target/rel
        copy_to.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,copy_to)
    if count==0:
        raise ValueError("sandbox workspace has no regular files")
    if os.name!="nt" and hasattr(os,"getuid") and os.getuid()==0:
        for directory in [target,*[p for p in target.rglob("*") if p.is_dir()]]:
            directory.chmod(0o755)
        for file in (p for p in target.rglob("*") if p.is_file()):
            file.chmod(0o644)


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
        with tempfile.TemporaryDirectory(prefix="agent-sandbox-snapshot-") as stage:
            snapshot_workspace(workspace, stage)
            cmd = command(stage, name)
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
