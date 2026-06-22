"""Executor: fuehrt acceptance-Checks eines Knotens als Shell-Kommandos aus.

Sicherheitsnotiz: dieser Executor fuehrt beliebige Shell-Kommandos aus dem Workflow-JSON
aus (subprocess mit explizitem bash -lc). Das ist gewollt -- acceptance soll ausfuehrbar
sein -- aber Workflows aus nicht vertrauenswuerdiger Quelle bedeuten damit beliebige
Code-Ausfuehrung auf dieser Maschine. Nur Workflows aus vertrauenswuerdiger Quelle laden.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_TIMEOUT_SECONDS = 120
# Explizite Shell statt globalem subprocess-Shell-Flag: auf Windows waere das sonst cmd.exe,
# acceptance-Checks sind aber bash-Stil (grep, test -f, pytest, Pipes, Globs).
_DEFAULT_SHELL = ["bash", "-lc"]


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


def run_check(check, defaults=None, cwd_root=".", shell=None):
    """Fuehrt ein einzelnes Kommando aus und wertet expect aus."""
    defaults = defaults or {}
    shell = shell or _DEFAULT_SHELL
    command = check["command"]
    timeout_seconds = check.get("timeoutSeconds", _DEFAULT_TIMEOUT_SECONDS)
    resolved_cwd = _resolve_cwd(check, defaults, cwd_root)
    # shutil.which statt rohem Namen: Windows' CreateProcess-Suche prueft System32 vor PATH
    # und faende dort sonst den WSL-Relay-Stub "bash.exe" statt Git Bash.
    executable = shutil.which(shell[0]) or shell[0]

    try:
        result = subprocess.run(
            [executable, *shell[1:], command],
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
    except FileNotFoundError:
        shell_name = " ".join(shell)
        return CheckResult(
            command=command,
            passed=False,
            exit_code=None,
            stdout="",
            stderr="",
            timed_out=False,
            reasons=[f"shell nicht gefunden: {shell_name} -- ist Git Bash installiert und im PATH?"],
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


def run_node(node, defaults=None, cwd_root=".", shell=None):
    """Fuehrt alle acceptance-Checks eines Knotens aus. passed = alle bestanden.
    Fuehrt alle Checks aus (kein early-exit), damit der Report vollstaendig ist."""
    checks = [run_check(check, defaults, cwd_root, shell) for check in node["acceptance"]]
    passed = all(check.passed for check in checks)
    return NodeResult(node_id=node["id"], passed=passed, checks=checks)
