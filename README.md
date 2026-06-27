# agentic-workflows

Visuelles Tool zum Bauen und Kommentieren von Dev-Workflows, die anschließend von Claude Code (oder kompatiblen Agenten) Schritt für Schritt ausgeführt werden.

## Idee in einem Satz

Workflow als DAG zeichnen → pro Node strukturierte Slots (Ziel, Inputs, Constraints, Acceptance, Kommentare) ausfüllen → Tool generiert daraus Slash-Commands / Sub-Agent-Definitionen für Claude Code.

## Status

Stufe 1 **und** Stufe 2 funktionsfähig (Stand 2026-06-27). Engine komplett und getestet
(loader → export → runner → executor → orchestrator → cli), Beispiel-Workflow läuft
end-to-end durchs acceptance-Gate. UI gebaut (`ui/canvas.html`, Single-File, Zero-Deps).
Dogfooding live über `meta-workflow.json`.

Stufe 2 (Sandbox-Backend: docker + git-worktree pro Knoten) ist **end-to-end auf Hetzner
verifiziert**: Isolation im Container, acceptance-Gate, `commit_worktree` vor `merge_back`
(Agent-Arbeit landet via `--no-ff`-Merge in `main`), idempotentes `create_worktree` und
Kosten-Tracking (`total_cost_usd` im Run-Summary). Aufruf: `… run <wf>.json --sandbox`.
Details: `docs/PROJECT_OVERVIEW.md`, `docs/DECISION_backend.md`, `docs/STAGE2_RUNBOOK.md`.

Erster realer Nicht-Dev-Konsument (der „Allgemeinheits-Beweis"): **job-search-system**
(eigenes Repo). Beziehung + Cross-Reference-Konvention siehe `CLAUDE.md` →
„Externe Konsumenten / Zwei-Repo-Beziehung".

## Offene Designfragen

1. **Granularität pro Node** — ein Node = ein Slash-Command (klein, viele Nodes) vs. ein Node = ein ganzer Sub-Agent (groß, wenige Nodes).
2. **Execution-Modell** — Stufe 1 (Canvas als Design-Tool, Mensch orchestriert) vs. Stufe 2 (Master-Agent liest Graph und arbeitet ihn ab). Reifestufen, kein Entweder-oder; beide existieren in der Engine.
3. **Persistenz** — Workflow-JSON im Repo (git-versioniert, PR-fähig) vs. nur im Cowork-Artifact.
4. **Backend für Stufe 2** — entschieden (`docs/DECISION_backend.md`): Python-Primitive nachbauen statt sandcastle portieren; Worker = API-Modell; OpenClaw nur als optionaler Stufe-3-Trigger.

## Datenmodell

Ein Workflow ist eine JSON-Datei, die gegen `schema/workflow.schema.json` (JSON-Schema Draft 2020-12) validiert. Die Validierung läuft über `validate_workflow()` / `validate_workflow_file()` in `src/loader.py` und sammelt **alle** Verstöße auf einmal in einer `WorkflowValidationError` (Feld `.issues`), statt beim ersten abzubrechen.

Auf oberster Ebene hat ein Workflow `version` (`"1"`), `name`, optional `description`, optional `defaults` sowie die beiden Kernfelder `nodes[]` und `edges[]`.

Ein **Node** ist ein verifizierbar abschließbarer Task. Pflichtfelder sind `id` (kebab-case, dient zugleich als Export-Dateiname), `goal` (wird zur Prompt-Grundlage) und `acceptance` (mindestens ein Check). Optional kommen `title`, `inputs[]`, `constraints[]`, `comments`, `model` (`planner` | `sonnet` | `local` — Kosten-Routing) und `kind` (`command` | `agent` — Export-Granularität) hinzu.

Eine **Edge** ist eine gerichtete Abhängigkeit mit `from` und `to` (beides Node-IDs) und optionalem `label`: `from` muss fertig sein, bevor `to` startet. Die Kanten spannen so den DAG auf.

### Acceptance-Check

Der `acceptance`-Block ist der Hebel, der autonome Ausführung überhaupt ermöglicht: ein Node gilt nur dann als fertig, wenn **alle** seine Checks bestehen. Ein Check ist ein Shell-Kommando plus erwartetes Ergebnis:

- `command` — das auszuführende Kommando (deterministisch, ohne Seiteneffekte außerhalb des Repos).
- `expect` — was zutreffen muss; mehrere Bedingungen sind UND-verknüpft. Möglich sind `exitCode`, `stdoutMatches`, `stdoutNotMatches` und `stderrMatches` (Regex/ECMA).
- optional `description`, `cwd`, `timeoutSeconds` (Default 120).

Kleiner Node = ein Check, großer Node = mehrere.

### Minimalbeispiel

```json
{
  "version": "1",
  "name": "Smoke-Test-Workflow",
  "nodes": [
    {
      "id": "run-tests",
      "goal": "Test-Suite ausführen und sicherstellen, dass sie grün ist.",
      "acceptance": [
        {
          "description": "Alle Tests grün",
          "command": "pytest -q",
          "expect": { "exitCode": 0 }
        }
      ]
    }
  ],
  "edges": []
}
```

Ein vollständigeres Beispiel mit Modell-Routing, mehreren Checks und DAG-Kanten liegt in `examples/example-workflow.json`.

## Export-Targets

- `.claude/commands/<node-id>.md` — Slash-Commands, ein File pro Node
- `.claude/agents/<node-id>.md` — Sub-Agent-Definitionen
- `WORKFLOW.md` — Mermaid + alle Prompts inline als Single-File-Spec
