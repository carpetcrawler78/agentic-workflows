"""Tests fuer src/executor.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executor import run_check, run_node


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
