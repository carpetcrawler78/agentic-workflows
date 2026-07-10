"""Tests fuer die SQLite-Run-Historie (Teil 2, docs/CC_PROMPT_run_history_log.md)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import orchestrator
from orchestrator import NodeRun, WorkflowRun, _append_run_log, run_workflow


def _node(node_id, command="true", exit_code=0):
    return {
        "id": node_id,
        "goal": f"Goal for {node_id}",
        "acceptance": [{"command": command, "expect": {"exitCode": exit_code}}],
    }


def _workflow(nodes, edges=None, name="Test Workflow"):
    return {
        "version": "1",
        "name": name,
        "nodes": nodes,
        "edges": edges or [],
    }


def _query_all(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        runs = conn.execute("SELECT id, workflow_name, passed, total_cost_usd FROM runs").fetchall()
        node_runs = conn.execute("SELECT run_id, node_id, skipped, passed, cost_usd FROM node_runs").fetchall()
        return runs, node_runs
    finally:
        conn.close()


def test_default_on_relative_to_cwd_root(tmp_path):
    workflow = _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}])
    result = run_workflow(workflow, agent=None, cwd_root=str(tmp_path))

    db_path = tmp_path / ".aw-runs" / "runs.sqlite3"
    assert db_path.exists()
    runs, node_runs = _query_all(db_path)
    assert len(runs) == 1
    assert len(node_runs) == len(result.runs) == 2


def test_explicit_none_disables_run_log(tmp_path):
    workflow = _workflow([_node("a")])
    run_workflow(workflow, agent=None, cwd_root=str(tmp_path), run_log_path=None)

    assert not (tmp_path / ".aw-runs").exists()


def test_multiple_runs_accumulate(tmp_path):
    workflow = _workflow([_node("a")])
    db_path = tmp_path / "runs.sqlite3"

    run_workflow(workflow, agent=None, cwd_root=str(tmp_path), run_log_path=str(db_path))
    run_workflow(workflow, agent=None, cwd_root=str(tmp_path), run_log_path=str(db_path))

    runs, _ = _query_all(db_path)
    assert len(runs) == 2


def test_cost_aggregation(tmp_path):
    db_path = tmp_path / "runs.sqlite3"
    runs_with_cost = [
        NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=0.01),
        NodeRun(node_id="b", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=0.02),
    ]
    _append_run_log(db_path, "with-cost", WorkflowRun(order=["a", "b"], runs=runs_with_cost, passed=True))

    runs, _ = _query_all(db_path)
    assert runs[0][3] == pytest.approx(0.03)

    runs_without_cost = [
        NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=None),
    ]
    _append_run_log(db_path, "without-cost", WorkflowRun(order=["a"], runs=runs_without_cost, passed=True))

    runs, _ = _query_all(db_path)
    assert runs[1][3] is None


def test_failed_run_still_logged(tmp_path):
    workflow = _workflow([_node("a", command="false")])
    result = run_workflow(workflow, agent=None, cwd_root=str(tmp_path))
    assert not result.passed

    db_path = tmp_path / ".aw-runs" / "runs.sqlite3"
    runs, _ = _query_all(db_path)
    assert len(runs) == 1
    assert runs[0][2] == 0


def test_write_failure_does_not_crash(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise sqlite3.Error("disk full")

    monkeypatch.setattr(orchestrator.sqlite3, "connect", boom)

    workflow = _workflow([_node("a")])
    result = run_workflow(workflow, agent=None, cwd_root=str(tmp_path))

    assert result.passed
    assert "WARNUNG" in capsys.readouterr().err


def test_size_warning_above_10mb(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "runs.sqlite3"
    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        if str(self) == str(db_path):
            class FakeStatResult:
                st_size = 11 * 1024 * 1024
            return FakeStatResult()
        return result

    monkeypatch.setattr(Path, "stat", fake_stat)

    runs = [NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True)]
    _append_run_log(db_path, "big", WorkflowRun(order=["a"], runs=runs, passed=True))

    err = capsys.readouterr().err
    assert "WARNUNG" in err
    assert "10 MB" in err


def test_size_no_warning_below_10mb(tmp_path, capsys):
    db_path = tmp_path / "runs.sqlite3"
    runs = [NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True)]
    _append_run_log(db_path, "small", WorkflowRun(order=["a"], runs=runs, passed=True))

    err = capsys.readouterr().err
    assert "WARNUNG" not in err
