"""Tests fuer src/runner.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from runner import (
    WorkflowCycleError,
    WorkflowGraphError,
    topological_order,
    topological_order_file,
    topological_waves,
)
from loader import WorkflowValidationError

_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "example-workflow.json"


@pytest.fixture
def example_workflow():
    with _EXAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _node(node_id):
    """Minimaler gueltiger Knoten fuer Inline-Fixtures."""
    return {
        "id": node_id,
        "goal": f"Ziel von {node_id}",
        "acceptance": [{"command": "true", "expect": {"exitCode": 0}}],
    }


def _workflow(node_ids, edges):
    return {
        "version": "1",
        "name": "Test-Workflow",
        "nodes": [_node(node_id) for node_id in node_ids],
        "edges": edges,
    }


def test_example_workflow_order():
    order = topological_order_file(str(_EXAMPLE_PATH))
    assert order == ["implement-validator", "test-validator", "document-schema"]


def test_repeated_calls_are_deterministic(example_workflow):
    first = topological_order(example_workflow)
    second = topological_order(example_workflow)
    assert first == second


def test_independent_sources_ordered_by_nodes_position():
    workflow = _workflow(
        ["b", "a", "c"],
        [{"from": "b", "to": "c"}, {"from": "a", "to": "c"}],
    )
    assert topological_order(workflow) == ["b", "a", "c"]


def test_isolated_node_appears_in_output():
    workflow = _workflow(
        ["a", "b", "isolated"],
        [{"from": "a", "to": "b"}],
    )
    assert topological_order(workflow) == ["a", "b", "isolated"]


def test_unknown_edge_id_raises_graph_error():
    workflow = _workflow(["a"], [{"from": "a", "to": "missing"}])
    with pytest.raises(WorkflowGraphError):
        topological_order(workflow)


def test_cycle_raises_cycle_error():
    workflow = _workflow(
        ["a", "b"],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    )
    with pytest.raises(WorkflowCycleError) as exc_info:
        topological_order(workflow)
    assert set(exc_info.value.cycle) == {"a", "b"}


def test_invalid_workflow_raises_validation_error():
    workflow = {
        "version": "1",
        "name": "Invalid",
        "nodes": [{"id": "a", "goal": "x"}],
        "edges": [],
    }
    with pytest.raises(WorkflowValidationError):
        topological_order(workflow)


def test_example_workflow_waves():
    with _EXAMPLE_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)
    waves = topological_waves(workflow)
    assert waves == [["implement-validator"], ["test-validator"], ["document-schema"]]


def test_independent_sources_share_first_wave():
    workflow = _workflow(
        ["b", "a", "c"],
        [{"from": "b", "to": "c"}, {"from": "a", "to": "c"}],
    )
    waves = topological_waves(workflow)
    assert waves == [["b", "a"], ["c"]]


def test_waves_isolated_node_forms_own_wave_position():
    workflow = _workflow(
        ["a", "b", "isolated"],
        [{"from": "a", "to": "b"}],
    )
    waves = topological_waves(workflow)
    assert waves == [["a", "isolated"], ["b"]]


def test_waves_unknown_edge_id_raises_graph_error():
    workflow = _workflow(["a"], [{"from": "a", "to": "missing"}])
    with pytest.raises(WorkflowGraphError):
        topological_waves(workflow)


def test_waves_cycle_raises_cycle_error():
    workflow = _workflow(
        ["a", "b"],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    )
    with pytest.raises(WorkflowCycleError) as exc_info:
        topological_waves(workflow)
    assert set(exc_info.value.cycle) == {"a", "b"}


def test_waves_invalid_workflow_raises_validation_error():
    workflow = {
        "version": "1",
        "name": "Invalid",
        "nodes": [{"id": "a", "goal": "x"}],
        "edges": [],
    }
    with pytest.raises(WorkflowValidationError):
        topological_waves(workflow)
