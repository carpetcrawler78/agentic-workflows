"""Executor: fuehrt acceptance-Checks eines Knotens als Shell-Kommandos aus.

Sicherheitsnotiz: dieser Executor fuehrt beliebige Shell-Kommandos aus dem Workflow-JSON
aus (subprocess mit shell=True). Das ist gewollt -- acceptance soll ausfuehrbar sein --
aber Workflows aus nicht vertrauenswuerdiger Quelle bedeuten damit beliebige
Code-Ausfuehrung auf dieser Maschine. Nur Workflows aus vertrauenswuerdiger Quelle laden.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_TIMEOUT_SECONDS = 120


@dataclass
class CheckResult:
    command: str
    passed: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class NodeResult:
    node_id: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)


def _resolve_cwd(check, defaults, cwd_root):
    """check.cwd > defaults.cwd > cwd_root, relative Pfade gegen cwd_root aufgeloest."""
    cwd = check.get("cwd")
    if cwd is None:
        cwd = defaults.get("cwd")
    if cwd is None:
        return Path(cwd_root)
    return Path(cwd_root) / cwd


def _evaluate_expect(expect, exit_code, stdout, stderr):
    """Nur die tatsaechlich gesetzten expect-Schluessel pruefen, UND-verknuepft."""
    reasons = []

    if "exitCode" in expect:
        expected = expect["exitCode"]
        if exit_code != expected:
            reasons.append(f"exitCode: erwartet {expected}, war {exit_code}")

    if "stdoutMatches" in expect:
        pattern = expect["stdoutMatches"]
        if re.search(pattern, stdout) is None:
            reasons.append(f"stdoutMatches '{pattern}': kein Treffer")

    if "stdoutNotMatches" in expect:
        pattern = expect["stdoutNotMatches"]
        if re.search(pattern, stdout) is not None:
            reasons.append(f"stdoutNotMatches '{pattern}': unerwarteter Treffer")

    if "stderrMatches" in expect:
        pattern = expect["stderrMatches"]
        if re.search(pattern, stderr) is None:
            reasons.append(f"stderrMatches '{pattern}': kein Treffer")

    return reasons


def run_check(check, defaults=None, cwd_root="."):
    """Fuehrt ein einzelnes Kommando aus und wertet expect aus."""
    defaults = defaults or {}
    command = check["command"]
    timeout_seconds = check.get("timeoutSeconds", _DEFAULT_TIMEOUT_SECONDS)
    resolved_cwd = _resolve_cwd(check, defaults, cwd_root)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(resolved_cwd),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            command=command,
            passed=False,
            exit_code=None,
            stdout="",
            stderr="",
            timed_out=True,
            reasons=[f"timeout nach {timeout_seconds}s"],
        )

    reasons = _evaluate_expect(check["expect"], result.returncode, result.stdout, result.stderr)
    return CheckResult(
        command=command,
        passed=not reasons,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=False,
        reasons=reasons,
    )


def run_node(node, defaults=None, cwd_root="."):
    """Fuehrt alle acceptance-Checks eines Knotens aus. passed = alle bestanden.
    Fuehrt alle Checks aus (kein early-exit), damit der Report vollstaendig ist."""
    checks = [run_check(check, defaults, cwd_root) for check in node["acceptance"]]
    passed = all(check.passed for check in checks)
    return NodeResult(node_id=node["id"], passed=passed, checks=checks)
