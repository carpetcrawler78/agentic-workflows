"""Exporter: validierte Workflow-Knoten -> Claude-Code-Artefakte (.claude/commands|agents/*.md)."""

import argparse
from pathlib import Path

try:
    from .loader import validate_workflow, validate_workflow_file
except ImportError:
    from loader import validate_workflow, validate_workflow_file

_MODEL_DEFAULT = "sonnet"
_KIND_DEFAULT = "command"


def _resolve(node, defaults, key, schema_default):
    """Effektiver Wert: Knoten ueberschreibt defaults, defaults ueberschreibt Schema-Default."""
    if node.get(key) is not None:
        return node[key]
    if defaults.get(key) is not None:
        return defaults[key]
    return schema_default


def _bullet_list(items):
    return "\n".join(f"- {item}" for item in items)


def _acceptance_lines(acceptance):
    lines = []
    for check in acceptance:
        command_span = f"`{check['command']}`"
        description = check.get("description")
        if description:
            lines.append(f"- {description}: {command_span}")
        else:
            lines.append(f"- {command_span}")
    return "\n".join(lines)


def render_node(node, defaults):
    """Rendert einen einzelnen Knoten zu Markdown (Frontmatter + Prompt-Body).
    Reine Funktion, schreibt nichts."""
    defaults = defaults or {}
    kind = _resolve(node, defaults, "kind", _KIND_DEFAULT)
    model = _resolve(node, defaults, "model", _MODEL_DEFAULT)
    title = node.get("title", node["id"])
    description = node.get("title", node["id"])

    frontmatter_lines = ["---", f"description: {description}", f"model: {model}"]
    if kind == "agent":
        frontmatter_lines.append(f"name: {node['id']}")
    frontmatter_lines.append("---")

    body_sections = [f"# {title}", "## Ziel", node["goal"]]

    inputs = node.get("inputs")
    if inputs:
        body_sections.append("## Inputs")
        body_sections.append(_bullet_list(inputs))

    constraints = node.get("constraints")
    if constraints:
        body_sections.append("## Constraints")
        body_sections.append(_bullet_list(constraints))

    body_sections.append("## Acceptance")
    body_sections.append(_acceptance_lines(node["acceptance"]))

    comments = node.get("comments")
    if comments:
        body_sections.append("## Hinweise")
        body_sections.append(comments)

    return "\n".join(frontmatter_lines) + "\n\n" + "\n\n".join(body_sections) + "\n"


def _mermaid_label(node):
    return node.get("title", node["id"])


def _render_mermaid(workflow):
    """Baut den Mermaid-DAG: erst alle Knoten deklarieren (auch isolierte), dann Kanten."""
    lines = ["```mermaid", "graph TD"]
    for node in workflow["nodes"]:
        lines.append(f'    {node["id"]}["{_mermaid_label(node)}"]')
    for edge in workflow.get("edges", []):
        label = edge.get("label")
        if label:
            lines.append(f'    {edge["from"]} -->|{label}| {edge["to"]}')
        else:
            lines.append(f'    {edge["from"]} --> {edge["to"]}')
    lines.append("```")
    return "\n".join(lines)


def render_workflow_md(workflow, defaults=None):
    """Rendert den gesamten Workflow als Single-File-Markdown: Titel + description,
    Mermaid-DAG aus edges, danach pro Knoten der render_node()-Output.
    Reine Funktion, schreibt nichts."""
    if defaults is None:
        defaults = workflow.get("defaults", {})

    sections = [f"# {workflow['name']}"]
    description = workflow.get("description")
    if description:
        sections.append(description)
    sections.append(_render_mermaid(workflow))
    sections.append("## Knoten")
    sections.append("\n\n".join(render_node(node, defaults) for node in workflow["nodes"]))

    return "\n\n".join(sections) + "\n"


def export_workflow(workflow, out_root="."):
    """Validiert den Workflow (ueber loader.validate_workflow), rendert jeden Knoten
    und schreibt die Dateien unter out_root/.claude/... .
    Gibt die Liste der geschriebenen Pfade zurueck."""
    validate_workflow(workflow)
    defaults = workflow.get("defaults", {})
    out_root_path = Path(out_root)

    # Erst alles rendern (rein, ohne Seiteneffekte), dann erst schreiben.
    targets = []
    for node in workflow["nodes"]:
        kind = _resolve(node, defaults, "kind", _KIND_DEFAULT)
        subdir = "commands" if kind == "command" else "agents"
        content = render_node(node, defaults)
        target_path = out_root_path / ".claude" / subdir / f"{node['id']}.md"
        targets.append((target_path, content))

    written = []
    for target_path, content in targets:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        written.append(str(target_path))
    return written


def export_workflow_file(path, out_root="."):
    """Liest + parst die Workflow-Datei (ueber loader.validate_workflow_file)
    und ruft export_workflow."""
    workflow = validate_workflow_file(path)
    return export_workflow(workflow, out_root)


def export_workflow_md(workflow, out_root="."):
    """Validiert (ueber loader.validate_workflow), rendert und schreibt
    out_root/WORKFLOW.md. Gibt den geschriebenen Pfad zurueck."""
    validate_workflow(workflow)
    content = render_workflow_md(workflow)
    target_path = Path(out_root) / "WORKFLOW.md"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return str(target_path)


def export_workflow_md_file(path, out_root="."):
    """Liest+parst die Workflow-Datei (ueber loader.validate_workflow_file)
    und ruft export_workflow_md."""
    workflow = validate_workflow_file(path)
    return export_workflow_md(workflow, out_root)


def _main():
    parser = argparse.ArgumentParser(description="Exportiert einen Workflow zu Claude-Code-Artefakten.")
    parser.add_argument("workflow", help="Pfad zur Workflow-JSON-Datei")
    parser.add_argument("--out", default=".", help="Ziel-Root-Verzeichnis (Default: .)")
    parser.add_argument(
        "--spec",
        action="store_true",
        help="WORKFLOW.md statt der Pro-Knoten-Artefakte schreiben",
    )
    args = parser.parse_args()

    if args.spec:
        print(export_workflow_md_file(args.workflow, args.out))
    else:
        written = export_workflow_file(args.workflow, args.out)
        for path in written:
            print(path)


if __name__ == "__main__":
    _main()
