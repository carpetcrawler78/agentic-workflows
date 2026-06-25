"""Tests fuer src/executor.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executor import _EXPLICIT_BASH_CANDIDATES, _find_bash, run_check, run_node


def test_success_stdout_matches():
    check = {"command": "echo hallo", "expect": {"stdoutMatches": "hallo"}}
    result = run_check(check)
    assert result.passed
    assert result.reasons == []


def test_exit_code_fail_names_reason():
    check = {"command": "false", "expect": {"exitCode": 0}}
    result = run_check(check)
    assert not result.passed
    assert any("exitCode" in reason for reason in result.reasons)


def test_stdout_not_matches_fail():
    check = {"command": "echo error", "expect": {"stdoutNotMatches": "(?i)error"}}
    result = run_check(check)
    assert not result.passed


def test_stderr_matches_passes():
    check = {"command": "echo boom 1>&2", "expect": {"stderrMatches": "boom"}}
    result = run_check(check)
    assert result.passed


def test_and_semantics_one_violation_fails():
    check = {"command": "echo hallo", "expect": {"stdoutMatches": "hallo", "exitCode": 1}}
    result = run_check(check)
    assert not result.passed
    assert len(result.reasons) == 1


def test_only_present_keys_are_checked():
    check = {"command": "sh -c 'echo x; exit 1'", "expect": {"stdoutMatches": "x"}}
    result = run_check(check)
    assert result.passed
    assert result.exit_code == 1


def test_timeout_marks_timed_out_and_failed():
    check = {"command": "sleep 5", "timeoutSeconds": 1, "expect": {"exitCode": 0}}
    result = run_check(check)
    assert result.timed_out
    assert not result.passed
    assert result.exit_code is None


def test_run_node_passes_only_if_all_checks_pass():
    node = {
        "id": "two-checks",
        "acceptance": [
            {"command": "true", "expect": {"exitCode": 0}},
            {"command": "false", "expect": {"exitCode": 0}},
        ],
    }
    result = run_node(node)
    assert not result.passed
    assert len(result.checks) == 2
    assert result.checks[0].passed
    assert not result.checks[1].passed


def test_run_node_all_pass():
    node = {
        "id": "two-checks-ok",
        "acceptance": [
            {"command": "true", "expect": {"exitCode": 0}},
            {"command": "echo ok", "expect": {"stdoutMatches": "ok"}},
        ],
    }
    result = run_node(node)
    assert result.passed


def test_cwd_resolution(tmp_path):
    subdir = tmp_path / "workdir"
    subdir.mkdir()
    (subdir / "marker.txt").write_text("x", encoding="utf-8")

    check = {"command": "ls", "cwd": "workdir", "expect": {"stdoutMatches": "marker.txt"}}
    result = run_check(check, defaults={}, cwd_root=str(tmp_path))
    assert result.passed


def test_bash_only_syntax_runs():
    check = {"command": "[[ 1 == 1 ]] && echo yes", "expect": {"stdoutMatches": "yes", "exitCode": 0}}
    result = run_check(check)
    assert result.passed


def test_shell_override_is_used():
    check = {"command": "echo ok", "expect": {"stdoutMatches": "ok"}}
    result = run_check(check, shell=["bash", "-c"])
    assert result.passed


def test_missing_shell_fails_cleanly():
    check = {"command": "echo ok", "expect": {"exitCode": 0}}
    result = run_check(check, shell=["definitiv-kein-binary-xyz", "-lc"])
    assert not result.passed
    assert result.exit_code is None
    assert not result.timed_out
    assert any("definitiv-kein-binary-xyz" in reason or "nicht gefunden" in reason for reason in result.reasons)


def test_run_node_passes_shell_through():
    node = {
        "id": "bash-only-node",
        "acceptance": [
            {"command": "[[ 1 == 1 ]] && echo yes", "expect": {"stdoutMatches": "yes"}},
        ],
    }
    result = run_node(node, shell=["bash", "-lc"])
    assert result.passed


# --- Tests fuer _find_bash ---


def test_find_bash_rejects_wsl_stub():
    """WSL-Relay-Stubs (System32/WindowsApps) duerfen nicht geprobt werden."""
    if sys.platform != "win32":
        pytest.skip("WSL-Stub-Check nur auf Windows relevant")
    probed = []

    def fake_run(cmd, **kwargs):
        probed.append(cmd[0])

        class R:
            returncode = 1

        return R()

    _find_bash(
        which_fn=lambda _: r"C:\Windows\System32\bash.EXE",
        run_fn=fake_run,
    )
    assert not any("System32" in p or "WindowsApps" in p for p in probed)


def test_find_bash_returns_first_working_candidate():
    """Erster Kandidat mit returncode 0 wird zurueckgegeben."""
    if not _EXPLICIT_BASH_CANDIDATES:
        pytest.skip("Explizite Kandidaten nur auf Windows relevant")
    expected = _EXPLICIT_BASH_CANDIDATES[0]
    probed = []

    def fake_run(cmd, **kwargs):
        probed.append(cmd[0])

        class R:
            returncode = 0

        return R()

    result = _find_bash(which_fn=lambda _: None, run_fn=fake_run)
    assert result == expected
    assert probed[0] == expected


def test_find_bash_uses_which_when_not_wsl():
    """Nicht-WSL which-Ergebnis wird aufgenommen und bei Erfolg zurueckgegeben."""
    custom = "/usr/local/bin/bash"

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0 if cmd[0] == custom else 1

        return R()

    result = _find_bash(which_fn=lambda _: custom, run_fn=fake_run)
    assert result == custom
