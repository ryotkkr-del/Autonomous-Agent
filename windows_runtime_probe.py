"""P0-6 Windows manual-trial runtime probes: explicit, bounded, non-destructive.

Only when --probe-runtime is supplied:
* Send a GET to http://127.0.0.1:11434/api/tags with Python's direct
  HTTPConnection (no proxy, authentication, request body, or redirect).
* Invoke existing sandbox_runner.setup_diagnosis() (read-only Docker CLI
  context/info/version/image inspect; NEVER pull, run, build, or start).
* Run trial_readiness's static checks (no DB/workspace contents read).

No agent, GUI, or generated code is launched. No updates, configuration writes,
file creation, model requests, or output file writes. Results are sanitized:
no local paths, environment variables, model lists, or Docker output.
Passing is NOT an end-to-end or security certification.
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import platform
import sys

# python -I removes the script directory from import paths.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sandbox_runner
import trial_readiness

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
EXPECTED_MODEL = "gemma3:4b"
MAX_OLLAMA_BYTES = 128 * 1024
DOCKER_STAGES = {
    "ready", "missing_cli", "missing_image", "wrong_container_mode",
    "remote_daemon", "daemon_unavailable",
}


def probe_ollama(*, connection_factory=None) -> dict:
    """GET tags via loopback only; never send prompts or reveal model names."""
    factory = connection_factory or http.client.HTTPConnection
    conn = None
    try:
        conn = factory(OLLAMA_HOST, OLLAMA_PORT, timeout=3)
        conn.request("GET", "/api/tags", headers={"Accept": "application/json"})
        response = conn.getresponse()
        # No redirects: do not follow arbitrary server-selected targets.
        if response.status != 200:
            return {"status": "unavailable", "reason": "non_200_response"}
        data = response.read(MAX_OLLAMA_BYTES + 1)
        if len(data) > MAX_OLLAMA_BYTES:
            return {"status": "unavailable", "reason": "response_too_large"}
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("models"), list):
            return {"status": "unavailable", "reason": "invalid_model_list"}
        models = parsed["models"]
        if len(models) > 4096 or any(
            not isinstance(model, dict) or not isinstance(model.get("name"), str)
            for model in models
        ):
            return {"status": "unavailable", "reason": "invalid_model_list"}
        found = any(model["name"] == EXPECTED_MODEL for model in models)
        return {"status": "ready" if found else "model_missing",
                "expected_model": EXPECTED_MODEL,
                "model_count": len(models)}
    except (OSError, TimeoutError, ValueError, UnicodeError,
            http.client.HTTPException):
        return {"status": "unavailable", "reason": "loopback_probe_failed"}
    finally:
        if conn is not None:
            conn.close()


def probe_docker(*, diagnosis=None) -> dict:
    """Existing diagnosis checks local Linux Docker without creating containers."""
    try:
        report = (diagnosis or sandbox_runner.setup_diagnosis)()
        if not isinstance(report, dict):
            return {"status": "unavailable", "stage": "unknown"}
        stage = report.get("stage")
        if stage not in DOCKER_STAGES or type(report.get("ready")) is not bool:
            return {"status": "unavailable", "stage": "unknown"}
        if report["ready"] and stage == "ready":
            return {"status": "ready", "stage": "ready"}
        if not report["ready"] and stage != "ready":
            return {"status": "unavailable", "stage": stage}
    except (OSError, ValueError, RuntimeError, TypeError):
        pass
    return {"status": "unavailable", "stage": "unknown"}


def inspect_runtime(*, static_check=None, ollama_check=None,
                    docker_check=None, system_name=None) -> dict:
    """Must be explicitly called; passing indicates prerequisites, NOT E2E."""
    static = (static_check or trial_readiness.assess)()
    platform_name = system_name if system_name is not None else platform.system()
    ollama = (ollama_check or probe_ollama)()
    docker = (docker_check or probe_docker)()
    blockers = list(static.get("blockers", []))
    if platform_name != "Windows":
        blockers.append("windows_device_required_for_windows_e2e")
    if ollama["status"] != "ready":
        blockers.append("ollama_runtime_or_required_model_missing")
    if docker["status"] != "ready":
        blockers.append("local_linux_docker_runtime_or_image_missing")
    # Do not claim the GUI was opened or the model actually generated tokens.
    return {
        "assessment": "runtime_prerequisites_found_not_e2e" if not blockers else "not_ready",
        "blockers": blockers,
        "static_assessment": static.get("assessment", "unknown"),
        "ollama": ollama,
        "docker": docker,
        "manual_checks_still_required": [
            "windows_11_standard_user",
            "real_gui_launch_and_close",
            "real_model_generation_with_dummy_goal",
            "docker_isolation_negative_tests_on_local_desktop",
            "stop_resume_and_restart",
            "recovery_with_disposable_data_only",
        ],
        "updates_enabled": False,
        "actual_e2e_verified": False,
        "guarantees": "none",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit local Ollama + Docker read-only runtime readiness probe")
    parser.add_argument("--probe-runtime", action="store_true", required=True,
                        help="perform bounded loopback Ollama GET and local Docker CLI checks")
    parser.add_argument("--json", action="store_true", help="print sanitized JSON")
    args = parser.parse_args(argv)
    report = inspect_runtime()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Windows 実機検証準備（モデル推論・GUI操作は行いません）")
        print("判定:", report["assessment"])
        print("Ollama:", report["ollama"]["status"])
        print("Docker:", report["docker"]["status"])
        for blocker in report["blockers"]:
            print("BLOCK:", blocker)
        print("署名・更新・Windows実機E2E・安全性の合格証明ではありません。")
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
