"""Orchestrator: verdrahtet Validierung, Reihenfolge, Prompt-Rendering und
acceptance-Gate zu einem sequentiellen Workflow-Lauf. Der Agent-Schritt ist ein
injizierbares Callable (Dependency Injection), damit der Kern ohne echten
Claude-Code-Aufruf testbar bleibt."""

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:
    from .loader import validate_workflow, validate_workflow_file
    from .runner import topological_order
    from .executor import run_node, CheckResult, NodeResult
    from .export import render_node
except ImportError:
    from loader import validate_workflow, validate_workflow_file
    from runner import topological_order
    from executor import run_node, CheckResult, NodeResult
    from export import render_node

# (node, gerenderter_prompt) -> None. Wirft der Agent, gilt der Knoten als fehlgeschlagen.
Agent = Callable[[dict, str], None]


@dataclass
class NodeRun:
    node_id: str
    skipped: bool
    agent_invoked: bool
    result: Optional[NodeResult]
    passed: bool


@dataclass
class WorkflowRun:
    order: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    passed: bool = False


def _agent_error_result(node_id, exc):
    """Synthetisiert ein NodeResult aus einer Agent-Exception, ohne das Gate zu starten --
    der Agent hat seine Arbeit nicht abgeschlossen, also gilt der Knoten als fehlgeschlagen."""
    check_result = CheckResult(
        command="<agent>",
        passed=False,
        exit_code=None,
        stdout="",
        stderr=str(exc),
        timed_out=False,
        reasons=[f"Agent-Fehler: {exc}"],
    )
    return NodeResult(node_id=node_id, passed=False, checks=[check_result])


def _load_checkpoint(checkpoint_path):
    """Liest bereits bestandene node-ids aus der Checkpoint-Datei. Fehlt die Datei,
    gilt das als leerer Fortschritt (frischer Lauf)."""
    path = Path(checkpoint_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("passed_node_ids", [])


def _write_checkpoint(checkpoint_path, passed_node_ids):
    """Schreibt den bisherigen Fortschritt (bestandene node-ids) als JSON."""
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"passed_node_ids": passed_node_ids}, f)


def run_workflow(workflow, agent=None, cwd_root=".", stop_on_failure=True, checkpoint_path=None, resume=False):
    """Validiert den Workflow, bestimmt die Topo-Reihenfolge und fuehrt pro Knoten
    den optionalen Agent-Schritt plus das acceptance-Gate aus. Bei Fehlschlag wird
    per Default gestoppt, die restlichen Knoten werden als skipped markiert.

    Ist checkpoint_path gesetzt, wird nach jedem verarbeiteten Knoten der Fortschritt
    (bestandene node-ids) dorthin geschrieben. Mit resume=True werden bereits darin
    vermerkte Knoten uebersprungen (skipped=True, agent_invoked=False, passed=True)
    und der Lauf setzt beim ersten offenen Knoten fort. Ohne checkpoint_path ist das
    Verhalten exakt wie zuvor."""
    validate_workflow(workflow)
    order = topological_order(workflow)
    defaults = workflow.get("defaults", {})
    nodes_by_id = {node["id"]: node for node in workflow["nodes"]}

    already_passed = set(_load_checkpoint(checkpoint_path)) if (resume and checkpoint_path is not None) else set()
    passed_node_ids = list(already_passed)

    runs = []
    stopped = False

    for node_id in order:
        if node_id in already_passed:
            runs.append(
                NodeRun(node_id=node_id, skipped=True, agent_invoked=False, result=None, passed=True)
            )
            continue

        if stopped:
            runs.append(
                NodeRun(node_id=node_id, skipped=True, agent_invoked=False, result=None, passed=False)
            )
            continue

        node = nodes_by_id[node_id]
        agent_invoked = False

        if agent is not None:
            prompt = render_node(node, defaults)
            agent_invoked = True
            try:
                agent(node, prompt)
            except Exception as exc:
                result = _agent_error_result(node_id, exc)
                runs.append(
                    NodeRun(node_id=node_id, skipped=False, agent_invoked=True, result=result, passed=False)
                )
                if stop_on_failure:
                    stopped = True
                if checkpoint_path is not None:
                    _write_checkpoint(checkpoint_path, passed_node_ids)
                continue

        result = run_node(node, defaults, cwd_root)
        runs.append(
            NodeRun(node_id=node_id, skipped=False, agent_invoked=agent_invoked, result=result, passed=result.passed)
        )
        if result.passed:
            passed_node_ids.append(node_id)
        if not result.passed and stop_on_failure:
            stopped = True

        if checkpoint_path is not None:
            _write_checkpoint(checkpoint_path, passed_node_ids)

    overall_passed = all(run.passed for run in runs)
    return WorkflowRun(order=order, runs=runs, passed=overall_passed)


def run_workflow_file(path, agent=None, cwd_root=".", stop_on_failure=True, checkpoint_path=None, resume=False):
    """Liest+parst die Workflow-Datei (loader.validate_workflow_file) und ruft run_workflow."""
    workflow = validate_workflow_file(path)
    return run_workflow(
        workflow,
        agent=agent,
        cwd_root=cwd_root,
        stop_on_failure=stop_on_failure,
        checkpoint_path=checkpoint_path,
        resume=resume,
    )


def make_claude_agent(extra_args=None):
    """Duenne Factory um den echten Claude-Code-Agenten: baut pro Knoten nur das
    Kommando und ruft subprocess.run, ohne Annahme ueber den Output zu treffen.
    Wird NICHT mit echtem Claude Code unit-getestet -- nur die Kommando-Konstruktion.

    HINWEIS: das Flag '-p' fuer Headless-Prompt-Uebergabe ist defensiv gewaehlt und
    muss ggf. an die installierte Claude-Code-CLI-Version angepasst werden."""
    extra_args = extra_args or []

    def agent(node, prompt):
        command = ["claude", "-p", prompt] + list(extra_args)
        subprocess.run(command, check=True)

    return agent


def _print_summary(workflow_run):
    for run in workflow_run.runs:
        if run.skipped:
            status = "skipped"
        elif run.passed:
            status = "passed"
        else:
            status = "failed"
        print(f"{run.node_id}: {status}")
    total = len(workflow_run.runs)
    passed_count = sum(1 for run in workflow_run.runs if run.passed)
    overall = "passed" if workflow_run.passed else "failed"
    print(f"Gesamt: {passed_count}/{total} Knoten bestanden, Workflow {overall}")


def _main():
    parser = argparse.ArgumentParser(description="Fuehrt einen Workflow sequentiell aus (Verify-Only per Default).")
    parser.add_argument("workflow", help="Pfad zur Workflow-JSON-Datei")
    parser.add_argument("--cwd", default=".", help="Root-Verzeichnis fuer acceptance-Kommandos (Default: .)")
    parser.add_argument("--no-stop", action="store_true", help="Bei Fehlschlag nicht abbrechen")
    parser.add_argument("--execute", action="store_true", help="Echten Claude-Code-Agenten aufrufen")
    args = parser.parse_args()

    agent = None
    if args.execute:
        print("Hinweis: --execute ruft echtes Claude Code auf -- 'claude' muss auf dem PATH sein.")
        agent = make_claude_agent()

    workflow_run = run_workflow_file(
        args.workflow,
        agent=agent,
        cwd_root=args.cwd,
        stop_on_failure=not args.no_stop,
    )
    _print_summary(workflow_run)


if __name__ == "__main__":
    _main()
