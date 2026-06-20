"""Tests fuer src/loader.py."""

import copy
import json
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loader import WorkflowValidationError, validate_workflow, validate_workflow_file

_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "example-workflow.json"


@pytest.fixture
def example_workflow():
    with _EXAMPLE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_example_workflow_file_validates():
    result = validate_workflow_file(str(_EXAMPLE_PATH))
    assert result["name"] == "Add JSON-Schema validation to workflow loader"


def test_node_without_acceptance_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    del wf["nodes"][0]["acceptance"]
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_empty_acceptance_array_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    wf["nodes"][0]["acceptance"] = []
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_check_with_empty_expect_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    wf["nodes"][0]["acceptance"][0]["expect"] = {}
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_node_id_camel_case_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    wf["nodes"][0]["id"] = "ImplementValidator"
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_unknown_model_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    wf["nodes"][0]["model"] = "gpt"
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_unknown_top_level_key_fails(example_workflow):
    wf = copy.deepcopy(example_workflow)
    wf["unknownKey"] = "value"
    with pytest.raises(WorkflowValidationError):
        validate_workflow(wf)


def test_multiple_errors_collected(example_workflow):
    wf = copy.deepcopy(example_workflow)
    del wf["nodes"][0]["acceptance"]
    wf["nodes"][1]["model"] = "gpt"
    with pytest.raises(WorkflowValidationError) as exc_info:
        validate_workflow(wf)
    assert len(exc_info.value.issues) > 1
