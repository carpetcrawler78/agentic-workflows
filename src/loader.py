"""Lader fuer Workflow-JSON-Dateien: Validierung gegen schema/workflow.schema.json."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "workflow.schema.json"


class WorkflowValidationError(Exception):
    """Enthaelt ALLE Schema-Verstoesse, nicht nur den ersten."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__("\n".join(issues))


def _load_schema():
    with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _format_error(error):
    # json_path nutzt JSONPath-Syntax ('$.nodes[0]'), wir wollen einfache Slashes.
    path = "/" + "/".join(str(p) for p in error.absolute_path)
    if path == "/":
        path = "/"
    return f"{path}: {error.message}"


def validate_workflow(obj):
    """Validiert ein bereits geparstes Objekt gegen schema/workflow.schema.json.
    Gibt das Objekt unveraendert zurueck, oder wirft WorkflowValidationError
    mit ALLEN gesammelten Fehlern."""
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        issues = [_format_error(e) for e in errors]
        raise WorkflowValidationError(issues)
    return obj


def validate_workflow_file(path):
    """Liest die Datei, parst JSON, ruft validate_workflow. Bei JSON-Parse-Fehler
    eine klare Exception mit Dateipfad."""
    file_path = Path(path)
    try:
        with file_path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"{file_path}: ungueltiges JSON ({e})") from e
    return validate_workflow(obj)
