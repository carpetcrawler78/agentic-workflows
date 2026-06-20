"""Tests fuer das Dogfooding-Artefakt meta-workflow.json. Fuehrt keine Knoten aus,
prueft nur Schema-Gueltigkeit und DAG-Konsistenz."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loader import validate_workflow_file
from runner import topological_order_file

_META_PATH = Path(__file__).resolve().parent.parent / "meta-workflow.json"


def test_meta_workflow_is_schema_valid():
    validate_workflow_file(_META_PATH)


def test_meta_workflow_topological_order_contains_all_nodes():
    with _META_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)
    expected_ids = {node["id"] for node in workflow["nodes"]}

    order = topological_order_file(_META_PATH)

    assert set(order) == expected_ids
    assert len(order) == len(expected_ids)


def test_meta_workflow_nodes_have_executable_acceptance_check():
    with _META_PATH.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    for node in workflow["nodes"]:
        assert node["acceptance"], f"{node['id']}: kein acceptance-Check"
        for check in node["acceptance"]:
            assert check.get("command", "").strip(), f"{node['id']}: leeres command"
