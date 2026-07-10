"""Tests fuer src/cli.py (Subcommand 'run': --checkpoint/--resume, --run-log/--no-run-log)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cli
from cli import main


def _write_workflow(path, nodes, edges=None):
    workflow = {
        "version": "1",
        "name": "CLI Test Workflow",
        "nodes": nodes,
        "edges": edges or [],
    }
    path.write_text(json.dumps(workflow), encoding="utf-8")
    return path


def _node(node_id, command="true", exit_code=0):
    return {
        "id": node_id,
        "goal": f"Goal for {node_id}",
        "acceptance": [{"command": command, "expect": {"exitCode": exit_code}}],
    }


def test_resume_without_checkpoint_errors_and_skips_run(tmp_path, monkeypatch, capsys):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a")])

    called = []
    monkeypatch.setattr(cli, "run_workflow_file", lambda *a, **kw: called.append(1))

    exit_code = main(["run", str(workflow_path), "--resume"])

    assert exit_code == 2
    assert "Fehler" in capsys.readouterr().err
    assert called == []


def test_checkpoint_then_resume_skips_passed_node(tmp_path, capsys):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a"), _node("b", command="false")])
    checkpoint_path = tmp_path / "checkpoint.json"

    exit_code_first = main([
        "run", str(workflow_path), "--cwd", str(tmp_path),
        "--checkpoint", str(checkpoint_path), "--no-run-log",
    ])
    assert exit_code_first == 1
    data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert data["passed_node_ids"] == ["a"]

    # "b" reparieren, danach mit --resume fortsetzen.
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow["nodes"][1]["acceptance"][0]["command"] = "true"
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

    capsys.readouterr()
    exit_code_second = main([
        "run", str(workflow_path), "--cwd", str(tmp_path),
        "--checkpoint", str(checkpoint_path), "--resume", "--no-run-log",
    ])
    out = capsys.readouterr().out
    assert exit_code_second == 0
    assert "a: skipped" in out
    assert "b: passed" in out


def test_no_checkpoint_no_resume_unchanged(tmp_path):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a")])

    exit_code = main(["run", str(workflow_path), "--cwd", str(tmp_path), "--no-run-log"])

    assert exit_code == 0
    assert not (tmp_path / "checkpoint.json").exists()


def test_no_run_log_disables_run_log(tmp_path):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a")])

    main(["run", str(workflow_path), "--cwd", str(tmp_path), "--no-run-log"])

    assert not (tmp_path / ".aw-runs").exists()


def test_run_log_explicit_path(tmp_path):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a")])
    run_log_path = tmp_path / "custom" / "runs.sqlite3"

    main(["run", str(workflow_path), "--cwd", str(tmp_path), "--run-log", str(run_log_path)])

    assert run_log_path.exists()
    assert not (tmp_path / ".aw-runs").exists()


def test_run_log_default_path_relative_to_cwd(tmp_path):
    workflow_path = _write_workflow(tmp_path / "wf.json", [_node("a")])

    main(["run", str(workflow_path), "--cwd", str(tmp_path)])

    assert (tmp_path / ".aw-runs" / "runs.sqlite3").exists()
