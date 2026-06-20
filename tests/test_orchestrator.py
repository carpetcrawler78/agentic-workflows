"""Tests fuer src/orchestrator.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import orchestrator
from orchestrator import make_claude_agent, run_workflow
from loader import WorkflowValidationError
from runner import topological_order


def _node(node_id, command="true", exit_code=0):
    return {
        "id": node_id,
        "goal": f"Goal for {node_id}",
        "acceptance": [{"command": command, "expect": {"exitCode": exit_code}}],
    }


def _workflow(nodes, edges=None):
    return {
        "version": "1",
        "name": "Test Workflow",
        "nodes": nodes,
        "edges": edges or [],
    }


def test_happy_path_agent_called_in_topo_order():
    workflow = _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}])
    calls = []

    def fake_agent(node, prompt):
        calls.append(node["id"])

    result = run_workflow(workflow, agent=fake_agent)

    assert calls == ["a", "b"] == result.order
    assert result.passed


def test_agent_receives_rendered_prompt_with_goal():
    workflow = _workflow([_node("a")])
    prompts = {}

    def fake_agent(node, prompt):
        prompts[node["id"]] = prompt

    run_workflow(workflow, agent=fake_agent)

    assert "Goal for a" in prompts["a"]


def test_gate_failure_stops_and_skips_next():
    workflow = _workflow(
        [_node("a", command="false"), _node("b")],
        [{"from": "a", "to": "b"}],
    )
    result = run_workflow(workflow, agent=None)

    assert not result.runs[0].passed
    assert result.runs[0].skipped is False
    assert result.runs[1].skipped is True
    assert not result.passed


def test_stop_on_failure_false_runs_remaining_nodes():
    workflow = _workflow(
        [_node("a", command="false"), _node("b")],
        [{"from": "a", "to": "b"}],
    )
    result = run_workflow(workflow, agent=None, stop_on_failure=False)

    assert not result.runs[0].passed
    assert result.runs[1].skipped is False
    assert result.runs[1].passed is True
    assert not result.passed


def test_verify_only_mode_skips_agent_but_runs_gate():
    workflow = _workflow([_node("a")])
    result = run_workflow(workflow, agent=None)

    assert result.runs[0].agent_invoked is False
    assert result.runs[0].result is not None
    assert result.passed


def test_agent_exception_marks_node_failed_without_crashing():
    workflow = _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}])

    def bad_agent(node, prompt):
        if node["id"] == "a":
            raise RuntimeError("boom")

    result = run_workflow(workflow, agent=bad_agent)

    assert result.runs[0].agent_invoked is True
    assert not result.runs[0].passed
    assert "boom" in result.runs[0].result.checks[0].reasons[0]
    assert result.runs[1].skipped is True
    assert not result.passed


def test_order_follows_topological_order_not_nodes_array():
    workflow = _workflow([_node("b"), _node("a")], [{"from": "a", "to": "b"}])
    calls = []

    def fake_agent(node, prompt):
        calls.append(node["id"])

    result = run_workflow(workflow, agent=fake_agent)

    assert result.order == ["a", "b"]
    assert calls == ["a", "b"]
    assert result.order == topological_order(workflow)


def test_invalid_workflow_raises_validation_error():
    workflow = {"version": "1", "name": "Invalid", "nodes": [{"id": "a", "goal": "x"}], "edges": []}
    with pytest.raises(WorkflowValidationError):
        run_workflow(workflow)


def test_make_claude_agent_builds_command(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)

        class FakeCompleted:
            returncode = 0

        return FakeCompleted()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    agent = make_claude_agent(extra_args=["--foo"])
    agent({"id": "a"}, "the prompt")

    assert calls[0][:2] == ["claude", "-p"]
    assert "the prompt" in calls[0]
    assert "--foo" in calls[0]
