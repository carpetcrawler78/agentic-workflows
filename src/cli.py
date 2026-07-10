"""Gemeinsamer Entrypoint: buendelt validate/export/run hinter 'python -m src.cli ...'."""

import argparse
import sys

try:
    from .loader import validate_workflow_file, WorkflowValidationError
    from .export import export_workflow_file, export_workflow_md_file
    from .orchestrator import run_workflow_file, make_claude_agent, _print_summary
except ImportError:
    from loader import validate_workflow_file, WorkflowValidationError
    from export import export_workflow_file, export_workflow_md_file
    from orchestrator import run_workflow_file, make_claude_agent, _print_summary


def _cmd_validate(args):
    try:
        validate_workflow_file(args.workflow)
    except WorkflowValidationError as exc:
        for issue in exc.issues:
            print(issue, file=sys.stderr)
        return 1
    print(f"OK: {args.workflow} ist gueltig")
    return 0


def _cmd_export(args):
    if args.spec:
        path = export_workflow_md_file(args.workflow, args.out)
        print(path)
    else:
        written = export_workflow_file(args.workflow, args.out)
        for path in written:
            print(path)
    return 0


def _cmd_run(args):
    if args.resume and not args.checkpoint_path:
        print("Fehler: --resume erfordert --checkpoint <PATH> (gleicher Pfad wie beim Lauf, "
              "der fortgesetzt werden soll).", file=sys.stderr)
        return 2

    run_log_kwargs = {}
    if args.no_run_log:
        if args.run_log_path:
            print("Hinweis: --no-run-log gesetzt, --run-log wird ignoriert.", file=sys.stderr)
        run_log_kwargs["run_log_path"] = None
    elif args.run_log_path:
        run_log_kwargs["run_log_path"] = args.run_log_path

    agent = None
    workspace = None

    if args.sandbox:
        try:
            from .sandbox_agent import make_sandbox_agent
            from .orchestrator import Workspace
        except ImportError:
            from sandbox_agent import make_sandbox_agent
            from orchestrator import Workspace
        agent = make_sandbox_agent(image=args.image, memory_limit=args.memory)
        workspace = Workspace(repo_root=args.cwd)
    elif args.execute:
        print("Hinweis: --execute ruft echtes Claude Code auf -- 'claude' muss auf dem PATH sein.")
        agent = make_claude_agent()

    workflow_run = run_workflow_file(
        args.workflow,
        agent=agent,
        cwd_root=args.cwd,
        stop_on_failure=not args.no_stop,
        checkpoint_path=args.checkpoint_path,
        resume=args.resume,
        workspace=workspace,
        max_parallel=args.max_parallel,
        **run_log_kwargs,
    )
    _print_summary(workflow_run)
    return 0 if workflow_run.passed else 1


def main(argv=None):
    """Parst argv, dispatcht auf das Subcommand, gibt den Exit-Code zurueck."""
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Gemeinsamer Entrypoint fuer agentic-workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_validate = subparsers.add_parser("validate", help="Workflow-Datei gegen das Schema validieren")
    parser_validate.add_argument("workflow", help="Pfad zur Workflow-JSON-Datei")
    parser_validate.set_defaults(func=_cmd_validate)

    parser_export = subparsers.add_parser("export", help="Claude-Code-Artefakte aus dem Workflow exportieren")
    parser_export.add_argument("workflow", help="Pfad zur Workflow-JSON-Datei")
    parser_export.add_argument("--out", default=".", help="Ziel-Root-Verzeichnis (Default: .)")
    parser_export.add_argument(
        "--spec",
        action="store_true",
        help="WORKFLOW.md statt der Pro-Knoten-Artefakte schreiben",
    )
    parser_export.set_defaults(func=_cmd_export)

    parser_run = subparsers.add_parser("run", help="Workflow sequentiell ausfuehren (Verify-Only per Default)")
    parser_run.add_argument("workflow", help="Pfad zur Workflow-JSON-Datei")
    parser_run.add_argument("--cwd", default=".", help="Root-Verzeichnis fuer acceptance-Kommandos (Default: .)")
    parser_run.add_argument("--no-stop", action="store_true", help="Bei Fehlschlag nicht abbrechen")
    parser_run.add_argument("--execute", action="store_true", help="Echten Claude-Code-Agenten aufrufen")
    parser_run.add_argument("--sandbox", action="store_true", help="Stufe-2-Backend: docker + git-worktree pro Knoten")
    parser_run.add_argument("--image", default="aw-sandbox:dev", help="Container-Image (Default: aw-sandbox:dev)")
    parser_run.add_argument("--memory", default="1.5g", help="Container-Memory-Limit (Default: 1.5g)")
    parser_run.add_argument("--max-parallel", type=int, default=1, metavar="N", dest="max_parallel",
                            help="Parallele Knoten (Default: 1; >1 noch nicht implementiert)")
    parser_run.add_argument(
        "--checkpoint", default=None, metavar="PATH", dest="checkpoint_path",
        help="Pfad fuer Checkpoint-Datei (Fortschritt nach jedem Knoten). Ohne dieses Flag "
             "kein Checkpoint, kein Resume moeglich.",
    )
    parser_run.add_argument(
        "--resume", action="store_true",
        help="Bereits im Checkpoint vermerkte Knoten ueberspringen und fortsetzen. "
             "Erfordert --checkpoint (gleicher Pfad wie beim vorherigen Lauf).",
    )
    parser_run.add_argument(
        "--run-log", default=None, metavar="PATH", dest="run_log_path",
        help="Pfad fuer SQLite-Run-Historie (Default: <cwd>/.aw-runs/runs.sqlite3, automatisch aktiv)",
    )
    parser_run.add_argument(
        "--no-run-log", action="store_true",
        help="Run-Log deaktivieren (Default ist an)",
    )
    parser_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
