"""Planner-Knoten: Claude gibt strukturierten Plan aus, Engine verarbeitet ihn.

Hauptpfad (Claude CLI >= 2.x): --output-format json --json-schema '<schema>'
liefert validierten JSON-Output nativ -- kein XML-Tag-Scan noetig.
Fallback fuer andere Provider: parse_tagged_output('<plan>...</plan>').

expand_plan(plan) -> (nodes, edges)  baut workflow-Schema-kompatible Listen.
"""

import json

from jsonschema import Draft202012Validator

try:
    from .sandbox import parse_tagged_output, ParseError
except ImportError:
    from sandbox import parse_tagged_output, ParseError


PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["tasks"],
    "additionalProperties": False,
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "prompt"],
                "additionalProperties": False,
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$",
                        "description": "Eindeutige kebab-case Task-ID (wird Knoten-ID im Sub-Workflow).",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Optionaler Branch-Name-Hinweis; Engine entscheidet final.",
                    },
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Aufgabenbeschreibung fuer den Worker-Agenten (wird 'goal').",
                    },
                    "dependsOn": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "IDs von Tasks, die vor diesem Task abgeschlossen sein muessen.",
                    },
                    "model": {
                        "enum": ["planner", "sonnet", "local"],
                        "default": "sonnet",
                        "description": "Kosten-Routing-Hint fuer den Worker.",
                    },
                },
            },
        }
    },
}

_VALIDATOR = Draft202012Validator(PLAN_SCHEMA)


def _validate_plan(data):
    """Wirft ValueError bei Schema-Verstoss."""
    errors = list(_VALIDATOR.iter_errors(data))
    if errors:
        raise ValueError(f"Plan-Schema-Verstoss: {errors[0].message}")


def extract_plan_from_json(json_output):
    """Hauptpfad (Claude --output-format json): validiert strukturierten JSON-Output.

    json_output darf string oder bereits geparste dict sein.
    Gibt den validierten Plan-Dict zurueck. Wirft ValueError bei Schema-Verstoss."""
    if isinstance(json_output, str):
        try:
            data = json.loads(json_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Kein gueltiges JSON: {exc}") from exc
    else:
        data = json_output
    _validate_plan(data)
    return data


def extract_plan_from_tagged(stdout):
    """Fallback (nicht-Claude-Provider): extrahiert <plan>...</plan> aus stdout.

    Gibt den validierten Plan-Dict zurueck. Wirft ParseError bei fehlendem Tag
    oder JSON-Fehler, ValueError bei Schema-Verstoss."""
    return parse_tagged_output(stdout, "plan", schema=PLAN_SCHEMA)


def expand_plan(plan):
    """Uebersetzt einen validierten Plan-Dict in workflow-kompatible (nodes, edges).

    nodes: Liste von Knoten-Dicts (id, goal, acceptance, optional model).
    edges: Liste von Kanten-Dicts (from, to) aus task.dependsOn.

    Acceptance-Placeholder ('true') -- der Worker-Agent setzt echte Checks."""
    nodes = []
    edges = []
    seen_ids = set()

    for task in plan["tasks"]:
        task_id = task["id"]
        if task_id in seen_ids:
            raise ValueError(f"Doppelte Task-ID im Plan: {task_id!r}")
        seen_ids.add(task_id)

        node = {
            "id": task_id,
            "goal": task["prompt"],
            "acceptance": [{"command": "true", "expect": {"exitCode": 0}}],
        }
        if "model" in task:
            node["model"] = task["model"]

        nodes.append(node)
        for dep in task.get("dependsOn", []):
            edges.append({"from": dep, "to": task_id})

    return nodes, edges
