"""Tests fuer src/export.py."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from export import (
    export_workflow,
    export_workflow_file,
    export_workflow_md,
    export_workflow_md_file,
    render_node,
    render_workflow_md,
)
from loader import WorkflowValidationError

_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "example-workflow.json"


@pytest.fixture
def example_workflow():
    with _EXAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_render_node_command_contains_acceptance_and_command(example_workflow):
    node = example_workflow["nodes"][0]
    defaults = example_workflow["defaults"]
    rendered = render_node(node, defaults)
    assert "## Acceptance" in rendered
    assert "python -m py_compile src/loader.py" in rendered


def test_export_workflow_file_writes_expected_paths(tmp_path):
    written = export_workflow_file(str(_EXAMPLE_PATH), out_root=str(tmp_path))
    expected = {
        str(tmp_path / ".claude" / "commands" / "implement-validator.md"),
        str(tmp_path / ".claude" / "commands" / "test-validator.md"),
        str(tmp_path / ".claude" / "agents" / "document-schema.md"),
    }
    assert set(written) == expected
    assert len(written) == 3
    for path in expected:
        assert Path(path).is_file()


def test_node_inherits_default_model(example_workflow):
    wf = copy.deepcopy(example_workflow)
    node = wf["nodes"][1]
    del node["model"]
    rendered = render_node(node, wf["defaults"])
    assert "model: sonnet" in rendered


def test_invalid_workflow_raises_before_writing(example_workflow, tmp_path):
    wf = copy.deepcopy(example_workflow)
    del wf["nodes"][0]["acceptance"]
    with pytest.raises(WorkflowValidationError):
        export_workflow(wf, out_root=str(tmp_path))
    assert not (tmp_path / ".claude").exists()


def test_render_workflow_md_contains_mermaid_block(example_workflow):
    rendered = render_workflow_md(example_workflow)
    assert "```mermaid" in rendered
    assert "graph TD" in rendered


def test_render_workflow_md_contains_all_edges(example_workflow):
    rendered = render_workflow_md(example_workflow)
    assert "implement-validator -->|Code muss stehen| test-validator" in rendered
    assert "test-validator -->|erst gruen, dann doku| document-schema" in rendered


def test_render_workflow_md_contains_all_node_ids_and_titles(example_workflow):
    rendered = render_workflow_md(example_workflow)
    for node in example_workflow["nodes"]:
        assert node["id"] in rendered
        assert node.get("title", node["id"]) in rendered


def test_export_workflow_md_file_writes_single_file(tmp_path):
    written = export_workflow_md_file(str(_EXAMPLE_PATH), out_root=str(tmp_path))
    expected = str(tmp_path / "WORKFLOW.md")
    assert written == expected
    assert Path(expected).is_file()


def test_export_workflow_md_invalid_workflow_raises_before_writing(example_workflow, tmp_path):
    wf = copy.deepcopy(example_workflow)
    del wf["nodes"][0]["acceptance"]
    with pytest.raises(WorkflowValidationError):
        export_workflow_md(wf, out_root=str(tmp_path))
    assert not (tmp_path / "WORKFLOW.md").exists()
