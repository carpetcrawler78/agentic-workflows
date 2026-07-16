"""Orchestrator: verdrahtet Validierung, Reihenfolge, Prompt-Rendering und
acceptance-Gate zu einem sequentiellen Workflow-Lauf. Der Agent-Schritt ist ein
injizierbares Callable (Dependency Injection), damit der Kern ohne echten
Claude-Code-Aufruf testbar bleibt."""

import argparse
import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    from .loader import validate_workflow, validate_workflow_file
    from .runner import topological_order, topological_waves
    from .executor import run_node, CheckResult, NodeResult
    from .export import render_node
    from .sandbox import create_worktree, commit_worktree, merge_back, remove_worktree
except ImportError:
    from loader import validate_workflow, validate_workflow_file
    from runner import topological_order, topological_waves
    from executor import run_node, CheckResult, NodeResult
    from export import render_node
    from sandbox import create_worktree, commit_worktree, merge_back, remove_worktree

# (node, gerenderter_prompt) -> Optional[float] (Kosten in USD) oder None.
# Wirft der Agent, gilt der Knoten als fehlgeschlagen.
Agent = Callable[[dict, str], Optional[float]]


@dataclass
class Workspace:
    """Konfiguration fuer den Stufe-2-Workspace-Modus (docker + git-worktree).

    repo_root: Verzeichnis, in dem Worktrees angelegt werden (.aw-worktrees/<node-id>)."""
    repo_root: str


@dataclass
class NodeRun:
    node_id: str
    skipped: bool
    agent_invoked: bool
    result: Optional[NodeResult]
    passed: bool
    cost_usd: Optional[float] = None


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


# Sentinel: "nicht angegeben" -> <cwd_root>/.aw-runs/runs.sqlite3 verwenden.
# None bedeutet dagegen "explizit deaktiviert" (z.B. --no-run-log).
_RUN_LOG_DEFAULT = object()


def _ensure_run_log_schema(conn):
    """Legt die beiden Tabellen an, falls sie noch nicht existieren. Idempotent,
    sicher bei jedem Aufruf ausfuehrbar."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, "
        "workflow_name TEXT NOT NULL, "
        "passed INTEGER NOT NULL, "
        "total_cost_usd REAL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS node_runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id INTEGER NOT NULL REFERENCES runs(id), "
        "node_id TEXT NOT NULL, "
        "skipped INTEGER NOT NULL, "
        "passed INTEGER NOT NULL, "
        "cost_usd REAL"
        ")"
    )


def _append_run_log(run_log_path, workflow_name, workflow_run):
    """Schreibt einen abgeschlossenen Lauf in die SQLite-Run-Historie. Legt Datei und
    Elternverzeichnis bei Bedarf an. Ein Fehlschlag beim Schreiben darf den Workflow-Lauf
    NICHT crashen -- nur eine Warnung auf stderr, der Rueckgabewert von run_workflow bleibt
    unveraendert. Warnt zusaetzlich auf stderr, wenn die Datei nach dem Schreiben > 10 MB
    gross ist (keine automatische Rotation -- Thomas-Entscheidung 2026-07-10)."""
    path = Path(run_log_path)
    total_cost = sum(
        r.cost_usd for r in workflow_run.runs if r.cost_usd is not None
    )
    total_cost = total_cost if any(r.cost_usd is not None for r in workflow_run.runs) else None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        try:
            _ensure_run_log_schema(conn)
            cur = conn.execute(
                "INSERT INTO runs (timestamp, workflow_name, passed, total_cost_usd) "
                "VALUES (?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    workflow_name,
                    1 if workflow_run.passed else 0,
                    total_cost,
                ),
            )
            run_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO node_runs (run_id, node_id, skipped, passed, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (run_id, r.node_id, 1 if r.skipped else 0, 1 if r.passed else 0, r.cost_usd)
                    for r in workflow_run.runs
                ],
            )
            conn.commit()
        finally:
            conn.close()

        size_bytes = path.stat().st_size
        if size_bytes > 10 * 1024 * 1024:
            size_mb = size_bytes / (1024 * 1024)
            print(
                f"WARNUNG: Run-Log '{path}' ist {size_mb:.1f} MB gross (>10 MB). "
                "Keine automatische Rotation -- bei Bedarf manuell aufraeumen/archivieren.",
                file=sys.stderr,
            )
    except (OSError, sqlite3.Error) as exc:
        print(f"WARNUNG: Run-Log konnte nicht geschrieben werden ({exc})", file=sys.stderr)


def _run_one_node_for_wave(node_id, nodes_by_id, defaults, agent, workspace, git_lock):
    """Per-Knoten-Logik fuer den parallelen Wellen-Modus (ohne Merge-Schritt).

    git-mutierende Schritte (create/remove) laufen unter git_lock --
    der eigentliche Agent-Aufruf bleibt nebenlaeufig.
    Gibt (node_id, result, worktree) bei Erfolg zurueck.
    Bei Agent-Fehler: (node_id, None, exc) -- worktree wird entfernt."""
    node = nodes_by_id[node_id]
    prompt = render_node(node, defaults)
    with git_lock:
        worktree = create_worktree(workspace.repo_root, node_id)
    node_ctx = {**node, "_worktree": worktree}
    try:
        cost = agent(node_ctx, prompt)
    except Exception as exc:
        with git_lock:
            remove_worktree(workspace.repo_root, worktree)
        return node_id, None, exc, None
    result = run_node(node, defaults, cwd_root=worktree.path)
    return node_id, result, worktree, cost


def _effective_model(node, defaults):
    """Effektives Modell: Knoten ueberschreibt defaults, defaults ueberschreibt Schema-Default."""
    if node.get("model") is not None:
        return node["model"]
    if defaults.get("model") is not None:
        return defaults["model"]
    return "sonnet"


def _uses_agent(node, defaults):
    """True, wenn dieser Knoten den (kostenpflichtigen) API-Agent-Schritt braucht.

    model == 'local' markiert deterministische/triviale Knoten (Skript-Arbeit, per
    acceptance-Kommando verifiziert). Fuer die ist kein API-Agent noetig -- der Runner
    ueberspringt den Agent-Schritt, das Gate erledigt bzw. prueft die Arbeit. Damit
    greift das Kosten-Routing: --execute billt nur noch bei echten Agent-Knoten
    (model sonnet/planner). Sobald ein lokaler Worker angebunden ist, hier statt
    Skip auf den lokalen Agent routen."""
    return _effective_model(node, defaults) != "local"


def _run_workflow_waves(workflow, agent, workspace, max_parallel, stop_on_failure):
    # TODO: sobald max_parallel>1 implementiert ist, hier ebenfalls _uses_agent(node,
    # defaults) respektieren, damit local-Knoten auch im Parallel-Pfad keinen Agent billen.
    """Parallele Workflow-Ausfuehrung ueber topological_waves + ThreadPoolExecutor.

    Innerhalb jeder Welle laufen Knoten nebenlaeufig (max_workers=max_parallel).
    Merges erfolgen nach jeder Welle in deterministischer Wellen-Reihenfolge.
    stop_on_failure: nach Wellen-Abschluss -- laufende Knoten werden nicht abgebrochen."""
    validate_workflow(workflow)
    waves = topological_waves(workflow)
    defaults = workflow.get("defaults", {})
    nodes_by_id = {node["id"]: node for node in workflow["nodes"]}
    order = [nid for wave in waves for nid in wave]

    all_runs = []
    stopped = False
    # Serialisiert git-mutierende Schritte (worktree add/remove, merge) ueber Threads.
    git_lock = threading.Lock()

    for wave in waves:
        if stopped:
            for nid in wave:
                all_runs.append(
                    NodeRun(node_id=nid, skipped=True, agent_invoked=False, result=None, passed=False)
                )
            continue

        wave_outcomes = {}
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = {
                executor.submit(_run_one_node_for_wave, nid, nodes_by_id, defaults, agent, workspace, git_lock): nid
                for nid in wave
            }
            for future, nid in futures.items():
                try:
                    wave_outcomes[nid] = future.result()
                except Exception as exc:
                    wave_outcomes[nid] = (nid, None, exc, None)

        # Merge in deterministischer Wellen-Reihenfolge (verhindert nicht-reproduzierbare Merge-Sequenz).
        for nid in wave:
            _, result, worktree_or_exc, cost = wave_outcomes[nid]
            if result is None:
                err_result = _agent_error_result(nid, worktree_or_exc)
                all_runs.append(
                    NodeRun(node_id=nid, skipped=False, agent_invoked=True, result=err_result, passed=False)
                )
                if stop_on_failure:
                    stopped = True
            else:
                worktree = worktree_or_exc
                if result.passed:
                    with git_lock:
                        commit_worktree(worktree, f"agent: {nid}")
                        merge_back(workspace.repo_root, worktree.branch, "HEAD")
                        remove_worktree(workspace.repo_root, worktree)
                all_runs.append(
                    NodeRun(node_id=nid, skipped=False, agent_invoked=True, result=result, passed=result.passed, cost_usd=cost)
                )
                if not result.passed and stop_on_failure:
                    stopped = True

    overall_passed = all(run.passed for run in all_runs)
    return WorkflowRun(order=order, runs=all_runs, passed=overall_passed)


def _run_workspace_node(node, prompt, agent, workspace, defaults):
    """Pro-Knoten-Logik im Workspace-Modus: worktree -> agent -> gate -> merge/keep.

    Gibt (NodeResult, Optional[float]) zurueck. Wirft, wenn der Agent wirft
    (der aeussere run_workflow-Handler faengt das dann als _agent_error_result ab)."""
    worktree = create_worktree(workspace.repo_root, node["id"])
    node_ctx = {**node, "_worktree": worktree}
    try:
        cost = agent(node_ctx, prompt)
    except Exception:
        remove_worktree(workspace.repo_root, worktree)
        raise
    result = run_node(node, defaults, cwd_root=worktree.path)
    if result.passed:
        commit_worktree(worktree, f"agent: {node['id']}")
        merge_back(workspace.repo_root, worktree.branch, "HEAD")
        remove_worktree(workspace.repo_root, worktree)
    # Rotes Gate: worktree erhalten fuer Inspektion, kein commit/merge.
    return result, cost


def run_workflow(workflow, agent=None, cwd_root=".", stop_on_failure=True, checkpoint_path=None, resume=False, workspace=None, max_parallel=1, run_log_path=_RUN_LOG_DEFAULT):
    """Validiert den Workflow, bestimmt die Topo-Reihenfolge und fuehrt pro Knoten
    den optionalen Agent-Schritt plus das acceptance-Gate aus. Bei Fehlschlag wird
    per Default gestoppt, die restlichen Knoten werden als skipped markiert.

    Ist checkpoint_path gesetzt, wird nach jedem verarbeiteten Knoten der Fortschritt
    (bestandene node-ids) dorthin geschrieben. Mit resume=True werden bereits darin
    vermerkte Knoten uebersprungen (skipped=True, agent_invoked=False, passed=True)
    und der Lauf setzt beim ersten offenen Knoten fort. Ohne checkpoint_path ist das
    Verhalten exakt wie zuvor.

    run_log_path steuert die SQLite-Run-Historie: ohne Angabe (Default) wird
    <cwd_root>/.aw-runs/runs.sqlite3 verwendet (default-on); explizit None deaktiviert
    das Logging vollstaendig."""
    if run_log_path is _RUN_LOG_DEFAULT:
        resolved_run_log_path = Path(cwd_root) / ".aw-runs" / "runs.sqlite3"
    elif run_log_path is None:
        resolved_run_log_path = None
    else:
        resolved_run_log_path = Path(run_log_path)

    if workspace is not None and max_parallel > 1 and agent is not None:
        return _run_workflow_waves(workflow, agent, workspace, max_parallel, stop_on_failure)

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
        cost = None

        if workspace is not None and agent is not None and _uses_agent(node, defaults):
            # Workspace-Modus: worktree -> agent im Container -> Gate -> merge/keep.
            prompt = render_node(node, defaults)
            agent_invoked = True
            try:
                result, cost = _run_workspace_node(node, prompt, agent, workspace, defaults)
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
        else:
            if agent is not None and _uses_agent(node, defaults):
                prompt = render_node(node, defaults)
                agent_invoked = True
                try:
                    cost = agent(node, prompt)
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
            NodeRun(node_id=node_id, skipped=False, agent_invoked=agent_invoked, result=result, passed=result.passed, cost_usd=cost)
        )
        if result.passed:
            passed_node_ids.append(node_id)
        if not result.passed and stop_on_failure:
            stopped = True

        if checkpoint_path is not None:
            _write_checkpoint(checkpoint_path, passed_node_ids)

    overall_passed = all(run.passed for run in runs)
    workflow_run = WorkflowRun(order=order, runs=runs, passed=overall_passed)

    if resolved_run_log_path is not None:
        _append_run_log(resolved_run_log_path, workflow.get("name", "?"), workflow_run)

    return workflow_run


def run_workflow_file(path, agent=None, cwd_root=".", stop_on_failure=True, checkpoint_path=None, resume=False, workspace=None, max_parallel=1, run_log_path=_RUN_LOG_DEFAULT):
    """Liest+parst die Workflow-Datei (loader.validate_workflow_file) und ruft run_workflow."""
    workflow = validate_workflow_file(path)
    return run_workflow(
        workflow,
        agent=agent,
        cwd_root=cwd_root,
        stop_on_failure=stop_on_failure,
        checkpoint_path=checkpoint_path,
        resume=resume,
        workspace=workspace,
        max_parallel=max_parallel,
        run_log_path=run_log_path,
    )


def make_claude_agent(extra_args=None):
    """Duenne Factory um den echten Claude-Code-Agenten: baut pro Knoten nur das
    Kommando und ruft subprocess.run, ohne Annahme ueber den Output zu treffen.
    Wird NICHT mit echtem Claude Code unit-getestet -- nur die Kommando-Konstruktion.

    HINWEIS: das Flag '-p' fuer Headless-Prompt-Uebergabe ist defensiv gewaehlt und
    muss ggf. an die installierte Claude-Code-CLI-Version angepasst werden.

    Der Prompt wird ueber stdin gereicht, nicht als argv-Argument. Sonst deutet der
    CLI-Parser einen Prompt, der mit '-' oder '---' beginnt (z.B. YAML-Frontmatter
    eines gerenderten Knotens), als unbekannte Option und bricht ab."""
    extra_args = extra_args or []

    def agent(node, prompt):
        command = ["claude", "-p"] + list(extra_args)
        subprocess.run(command, input=prompt, text=True, check=True)

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
    costs = [run.cost_usd for run in workflow_run.runs if run.cost_usd is not None]
    if costs:
        print(f"Gesamtkosten: ${sum(costs):.4f}")


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
