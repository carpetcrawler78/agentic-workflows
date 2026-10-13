# How this was built

The code in this repository was written with Claude Code. The way it was built mirrors
what the tool itself does: every building block was a task with an explicit, executable
definition of done.

## Working method

1. **One task prompt per building block.** For each step a prompt file was written first,
   in a separate planning session. Each prompt has the same structure: files to read first,
   context, what to build (API contract), tests, executable acceptance checks, constraints,
   out of scope.
2. **Execution in Claude Code.** The prompt was run in Claude Code in the repository root.
   The code was written there, not in the planning session.
3. **Acceptance checks decide.** A step counted as done only when all acceptance commands
   passed (typically `py_compile`, the full `pytest` run and a targeted check).
4. **Review fixes as separate tasks.** Problems found in review or in a test run on a server
   were turned into new task prompts (e.g. review fixes, smoke-test hotfixes) instead of
   being patched ad hoc.

The task prompts were working files and are not part of the repository. The build history
is summarised in [`BUILD_LOG.md`](BUILD_LOG.md) and [`DEVLOG.md`](DEVLOG.md).

## Order of the building blocks

**Engine (stage 1)**

1. Workflow validator (`src/loader.py`): JSON Schema validation that collects all errors
2. Exporter: slash commands / sub-agent files per node (`src/export.py`)
3. `WORKFLOW.md` export (Mermaid diagram + prompts)
4. Runner: topological order with cycle detection (`src/runner.py`)
5. Acceptance executor: runs the check commands and compares with `expect` (`src/executor.py`)
6. Orchestrator: nodes in order → agent → acceptance gate (`src/orchestrator.py`)
7. `meta-workflow.json`: the project's own roadmap as a workflow (dogfooding)
8. Common CLI (`src/cli.py`), packaging, execution in waves, checkpoint/resume
9. Canvas UI (`ui/canvas.html`), later a Mermaid source panel and round-trip checks
10. Executor fix: explicit `bash -lc` so that checks behave the same on Windows and Linux

**Sandbox backend (stage 2)**

11. Seven-phase task: git worktree + Docker sandbox + merge back, agent in the container,
    Dockerfile, parallel waves, planner, runbook, stage-3 stub
12. Review fixes: API key passed into the container, cost tracking, `git merge --abort` on
    conflict, serialised worktree creation
13. Smoke-test hotfixes, commit of the agent's work before the merge back
14. Run history (SQLite), `--checkpoint` / `--resume` in the CLI

## Example task prompt (shortened)

```markdown
# Task: implement the workflow runner (execution order)

Read first: README.md (data model), schema/workflow.schema.json,
src/loader.py (validator -- call it, do not bypass it), examples/example-workflow.json

## Context
The schema guarantees the shape of `edges`, but not that edge IDs exist and not that
the graph is acyclic. This step orders the nodes and rejects invalid graphs.

## What to build (src/runner.py)
- topological_order(workflow) -> list[str]: validate, check edge references,
  return node IDs in dependency order (Kahn's algorithm, standard library only)
- deterministic: among ready nodes, take the one listed first in nodes[]
- unknown edge ID -> WorkflowGraphError; cycle -> WorkflowCycleError(.cycle)

## Tests (tests/test_runner.py)
Example workflow order, determinism, isolated node, unknown edge ID, cycle,
invalid workflow raises WorkflowValidationError.

## Acceptance (all must pass)
python -m py_compile src/runner.py     # exit 0
pytest -q                              # exit 0
grep -rn "def topological_order" src/  # exit 0

## Constraints
Only src/runner.py and tests/test_runner.py. No new dependencies.
Do not change schema/, examples/, src/export.py.

## Out of scope
No execution of nodes, no parallel waves, no CLI.

## Done
All acceptance checks green: short summary (file, algorithm, number of tests), then stop.
```
