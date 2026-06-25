"""Tests fuer src/planner.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from planner import PLAN_SCHEMA, expand_plan, extract_plan_from_json, extract_plan_from_tagged
from sandbox import ParseError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_plan():
    return {
        "tasks": [
            {"id": "task-a", "prompt": "Implement the feature"},
            {"id": "task-b", "prompt": "Write tests", "dependsOn": ["task-a"], "model": "sonnet"},
        ]
    }


# ---------------------------------------------------------------------------
# extract_plan_from_json -- Hauptpfad
# ---------------------------------------------------------------------------


def test_extract_plan_from_json_happy_path():
    import json
    plan = extract_plan_from_json(json.dumps(_valid_plan()))
    assert len(plan["tasks"]) == 2
    assert plan["tasks"][0]["id"] == "task-a"


def test_extract_plan_from_json_dict_input():
    plan = extract_plan_from_json(_valid_plan())
    assert plan["tasks"][1]["model"] == "sonnet"


def test_extract_plan_from_json_schema_violation():
    bad = {"tasks": [{"id": "bad id with spaces", "prompt": "x"}]}
    with pytest.raises(ValueError, match="Schema"):
        extract_plan_from_json(bad)


def test_extract_plan_from_json_missing_tasks():
    with pytest.raises(ValueError, match="Schema"):
        extract_plan_from_json({"notTasks": []})


def test_extract_plan_from_json_empty_tasks():
    with pytest.raises(ValueError, match="Schema"):
        extract_plan_from_json({"tasks": []})


def test_extract_plan_from_json_broken_json_string():
    with pytest.raises(ValueError, match="JSON"):
        extract_plan_from_json("{not valid}")


# ---------------------------------------------------------------------------
# extract_plan_from_tagged -- Fallback
# ---------------------------------------------------------------------------


def test_extract_plan_from_tagged_happy_path():
    import json
    stdout = f'<plan>{json.dumps(_valid_plan())}</plan>'
    plan = extract_plan_from_tagged(stdout)
    assert len(plan["tasks"]) == 2


def test_extract_plan_from_tagged_missing_tag():
    with pytest.raises(ParseError, match="nicht.*gefunden"):
        extract_plan_from_tagged("no tag here")


def test_extract_plan_from_tagged_schema_violation():
    import json
    bad = {"tasks": [{"id": "Bad-Id", "prompt": "x"}]}  # uppercase not allowed
    stdout = f'<plan>{json.dumps(bad)}</plan>'
    with pytest.raises(ParseError, match="Schema"):
        extract_plan_from_tagged(stdout)


# ---------------------------------------------------------------------------
# expand_plan
# ---------------------------------------------------------------------------


def test_expand_plan_nodes_have_required_fields():
    nodes, edges = expand_plan(_valid_plan())
    assert len(nodes) == 2
    for node in nodes:
        assert "id" in node
        assert "goal" in node
        assert "acceptance" in node
        assert len(node["acceptance"]) >= 1


def test_expand_plan_goal_from_prompt():
    nodes, _ = expand_plan(_valid_plan())
    assert nodes[0]["goal"] == "Implement the feature"
    assert nodes[1]["goal"] == "Write tests"


def test_expand_plan_model_propagated():
    nodes, _ = expand_plan(_valid_plan())
    assert nodes[1].get("model") == "sonnet"


def test_expand_plan_edges_from_depends_on():
    nodes, edges = expand_plan(_valid_plan())
    assert len(edges) == 1
    assert edges[0] == {"from": "task-a", "to": "task-b"}


def test_expand_plan_no_dependencies():
    plan = {"tasks": [{"id": "solo", "prompt": "standalone"}]}
    nodes, edges = expand_plan(plan)
    assert len(nodes) == 1
    assert edges == []


def test_expand_plan_duplicate_id_raises():
    plan = {
        "tasks": [
            {"id": "dup", "prompt": "first"},
            {"id": "dup", "prompt": "second"},
        ]
    }
    with pytest.raises(ValueError, match="Doppelte"):
        expand_plan(plan)


def test_expand_plan_multi_dependency():
    plan = {
        "tasks": [
            {"id": "a", "prompt": "step a"},
            {"id": "b", "prompt": "step b"},
            {"id": "c", "prompt": "step c", "dependsOn": ["a", "b"]},
        ]
    }
    _, edges = expand_plan(plan)
    assert {"from": "a", "to": "c"} in edges
    assert {"from": "b", "to": "c"} in edges
    assert len(edges) == 2
