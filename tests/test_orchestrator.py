"""Tests fuer src/orchestrator.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import orchestrator
from orchestrator import Workspace, make_claude_agent, run_workflow
from loader import WorkflowValidationError
from runner import topological_order
from sandbox import MergeResult, Worktree


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


def test_checkpoint_file_written_after_each_node(tmp_path):
    workflow = _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}])
    checkpoint_path = tmp_path / "checkpoint.json"

    result = run_workflow(workflow, agent=None, checkpoint_path=str(checkpoint_path))

    assert result.passed
    assert checkpoint_path.exists()
    with checkpoint_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["passed_node_ids"] == ["a", "b"]


def test_resume_after_abort_skips_passed_nodes(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    workflow = _workflow(
        [_node("a"), _node("b", command="false"), _node("c")],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )

    first = run_workflow(workflow, agent=None, checkpoint_path=str(checkpoint_path))
    assert not first.passed
    assert first.runs[0].passed is True
    assert first.runs[2].skipped is True

    # "b" reparieren, danach mit resume=True fortsetzen.
    workflow["nodes"][1]["acceptance"][0]["command"] = "true"
    second = run_workflow(
        workflow, agent=None, checkpoint_path=str(checkpoint_path), resume=True
    )

    assert second.passed
    # "a" war beim ersten Lauf bereits gruen -> diesmal uebersprungen.
    run_a = next(r for r in second.runs if r.node_id == "a")
    assert run_a.skipped is True
    assert run_a.agent_invoked is False
    assert run_a.passed is True
    run_b = next(r for r in second.runs if r.node_id == "b")
    assert run_b.skipped is False
    assert run_b.passed is True
    run_c = next(r for r in second.runs if r.node_id == "c")
    assert run_c.skipped is False
    assert run_c.passed is True


# ---------------------------------------------------------------------------
# Workspace-Integration: FAKE-Workspace (kein echter docker/git)
# ---------------------------------------------------------------------------


def _patch_workspace(monkeypatch, tmp_path):
    """Ersetzt create_worktree / merge_back / remove_worktree durch Fakes.
    Gibt merge_calls-Liste zurueck fuer Assertions."""
    merge_calls = []

    def fake_create_worktree(repo_root, node_id, base="HEAD", **kwargs):
        return Worktree(path=str(tmp_path), branch=f"agent/{node_id}", base=base)

    def fake_merge_back(repo_root, branch, base, **kwargs):
        merge_calls.append(branch)
        return MergeResult(merged=True, conflict=False, stdout="", stderr="")

    def fake_remove_worktree(repo_root, worktree, **kwargs):
        pass

    monkeypatch.setattr(orchestrator, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(orchestrator, "merge_back", fake_merge_back)
    monkeypatch.setattr(orchestrator, "remove_worktree", fake_remove_worktree)
    return merge_calls


def test_workspace_merge_on_green_gate(monkeypatch, tmp_path):
    """Gruenes Gate im workspace-Modus -> merge_back wird aufgerufen."""
    merge_calls = _patch_workspace(monkeypatch, tmp_path)

    def fake_agent(node, prompt):
        pass

    result = run_workflow(
        _workflow([_node("a")]),
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
    )
    assert result.passed
    assert "agent/a" in merge_calls


def test_workspace_no_merge_on_red_gate(monkeypatch, tmp_path):
    """Rotes Gate im workspace-Modus -> kein merge_back."""
    merge_calls = _patch_workspace(monkeypatch, tmp_path)

    def fake_agent(node, prompt):
        pass

    result = run_workflow(
        _workflow([_node("a", command="false")]),
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
    )
    assert not result.passed
    assert merge_calls == []


def test_workspace_none_unchanged(monkeypatch, tmp_path):
    """workspace=None -> bisheriges Verhalten unveraendert (kein worktree)."""
    calls = []

    def fake_agent(node, prompt):
        calls.append(node["id"])

    result = run_workflow(
        _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}]),
        agent=fake_agent,
        workspace=None,
    )
    assert calls == ["a", "b"]
    assert result.passed


def test_parallel_wave_merges_in_deterministic_order(monkeypatch, tmp_path):
    """max_parallel=2: b und c (gleiche Welle) werden gemergt; Merge-Reihenfolge deterministisch."""
    merge_calls = []

    def fake_create_worktree(repo_root, node_id, **kwargs):
        return Worktree(path=str(tmp_path), branch=f"agent/{node_id}", base="HEAD")

    def fake_merge_back(repo_root, branch, base, **kwargs):
        merge_calls.append(branch)
        return MergeResult(merged=True, conflict=False, stdout="", stderr="")

    def fake_remove_worktree(repo_root, worktree, **kwargs):
        pass

    monkeypatch.setattr(orchestrator, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(orchestrator, "merge_back", fake_merge_back)
    monkeypatch.setattr(orchestrator, "remove_worktree", fake_remove_worktree)

    def fake_agent(node, prompt):
        pass

    # Workflow: a -> b, a -> c (b + c in gleicher Welle nach a)
    workflow = _workflow(
        [_node("a"), _node("b"), _node("c")],
        [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}],
    )
    result = run_workflow(
        workflow,
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
        max_parallel=2,
    )
    assert result.passed
    assert set(merge_calls) == {"agent/a", "agent/b", "agent/c"}
    # b erscheint vor c in nodes[] -> b vor c gemergt
    assert merge_calls.index("agent/b") < merge_calls.index("agent/c")


def test_parallel_max1_same_as_sequential(monkeypatch, tmp_path):
    """max_parallel=1 -> sequenzieller Pfad (unveraendert gegenueber Phase 2)."""
    merge_calls = _patch_workspace(monkeypatch, tmp_path)

    def fake_agent(node, prompt):
        pass

    result = run_workflow(
        _workflow([_node("a"), _node("b")], [{"from": "a", "to": "b"}]),
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
        max_parallel=1,
    )
    assert result.passed
    assert "agent/a" in merge_calls
    assert "agent/b" in merge_calls


def test_parallel_red_gate_no_merge(monkeypatch, tmp_path):
    """Rotes Gate in paralleler Welle: kein merge fuer diesen Knoten."""
    merge_calls = []

    def fake_create_worktree(repo_root, node_id, **kwargs):
        return Worktree(path=str(tmp_path), branch=f"agent/{node_id}", base="HEAD")

    def fake_merge_back(repo_root, branch, base, **kwargs):
        merge_calls.append(branch)
        return MergeResult(merged=True, conflict=False, stdout="", stderr="")

    monkeypatch.setattr(orchestrator, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(orchestrator, "merge_back", fake_merge_back)
    monkeypatch.setattr(orchestrator, "remove_worktree", lambda *a, **kw: None)

    def fake_agent(node, prompt):
        pass

    workflow = _workflow([_node("a", command="false")], [])
    result = run_workflow(
        workflow,
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
        max_parallel=2,
    )
    assert not result.passed
    assert merge_calls == []


def test_workspace_agent_exception_kept_no_merge(monkeypatch, tmp_path):
    """Agent-Exception im workspace-Modus: kein merge, remove_worktree aufgerufen."""
    merge_calls = []
    remove_calls = []

    def fake_create_worktree(repo_root, node_id, **kwargs):
        return Worktree(path=str(tmp_path), branch=f"agent/{node_id}", base="HEAD")

    def fake_merge_back(repo_root, branch, base, **kwargs):
        merge_calls.append(branch)
        return MergeResult(merged=True, conflict=False, stdout="", stderr="")

    def fake_remove_worktree(repo_root, worktree, **kwargs):
        remove_calls.append(worktree.branch)

    monkeypatch.setattr(orchestrator, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(orchestrator, "merge_back", fake_merge_back)
    monkeypatch.setattr(orchestrator, "remove_worktree", fake_remove_worktree)

    def bad_agent(node, prompt):
        raise RuntimeError("container crash")

    result = run_workflow(
        _workflow([_node("a")]),
        agent=bad_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
    )
    assert not result.passed
    assert merge_calls == []
    assert "agent/a" in remove_calls


# ---------------------------------------------------------------------------


def test_parallel_wave_create_worktree_serialized(monkeypatch, tmp_path):
    """create_worktree-Aufrufe laufen nie gleichzeitig (Lock-Serialisierung, Fix C)."""
    import threading

    concurrent_count = [0]
    max_concurrent = [0]
    count_lock = threading.Lock()

    def fake_create_worktree(repo_root, node_id, **kwargs):
        with count_lock:
            concurrent_count[0] += 1
            if concurrent_count[0] > max_concurrent[0]:
                max_concurrent[0] = concurrent_count[0]
        # Kurze Pause simuliert echte git-Arbeit
        import time
        time.sleep(0.02)
        with count_lock:
            concurrent_count[0] -= 1
        return Worktree(path=str(tmp_path), branch=f"agent/{node_id}", base="HEAD")

    def fake_merge_back(repo_root, branch, base, **kwargs):
        return MergeResult(merged=True, conflict=False, stdout="", stderr="")

    monkeypatch.setattr(orchestrator, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(orchestrator, "merge_back", fake_merge_back)
    monkeypatch.setattr(orchestrator, "remove_worktree", lambda *a, **kw: None)

    def fake_agent(node, prompt):
        pass

    workflow = _workflow(
        [_node("a"), _node("b"), _node("c")],
        [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}],
    )
    result = run_workflow(
        workflow,
        agent=fake_agent,
        workspace=Workspace(repo_root=str(tmp_path)),
        max_parallel=3,
    )
    assert result.passed
    # create_worktree darf nie von >1 Thread gleichzeitig gehalten werden
    assert max_concurrent[0] == 1


def test_cost_propagated_from_agent_to_node_run():
    """Agent gibt float zurueck -> NodeRun.cost_usd gesetzt (Fix A)."""
    workflow = _workflow([_node("a")])

    def costing_agent(node, prompt):
        return 0.0042

    result = run_workflow(workflow, agent=costing_agent)
    assert result.runs[0].cost_usd == pytest.approx(0.0042)


def test_print_summary_shows_total_cost(capsys):
    """_print_summary druckt Gesamtkosten wenn mindestens ein Knoten Kosten gemeldet hat."""
    from orchestrator import _print_summary, NodeRun, WorkflowRun
    runs = [
        NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=0.01),
        NodeRun(node_id="b", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=0.005),
    ]
    wf_run = WorkflowRun(order=["a", "b"], runs=runs, passed=True)
    _print_summary(wf_run)
    out = capsys.readouterr().out
    assert "Gesamtkosten" in out
    assert "0.0150" in out


def test_print_summary_no_cost_line_when_none(capsys):
    """Ohne Kosten-Daten erscheint keine Kostenzeile."""
    from orchestrator import _print_summary, NodeRun, WorkflowRun
    runs = [
        NodeRun(node_id="a", skipped=False, agent_invoked=True, result=None, passed=True, cost_usd=None),
    ]
    wf_run = WorkflowRun(order=["a"], runs=runs, passed=True)
    _print_summary(wf_run)
    out = capsys.readouterr().out
    assert "Gesamtkosten" not in out


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
