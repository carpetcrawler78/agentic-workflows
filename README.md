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
   **Entschieden (2026-07-10):** groß — ein Node = ein Sub-Agent. Begründung folgt aus Entscheidung 2 (Stufe 2): ein autonom laufender Master-Agent profitiert von wenigen, in sich geschlossenen Agent-Nodes statt vieler feinkörniger Slash-Command-Schritte, die einzeln orchestriert werden müssten. Kleine Slash-Command-Nodes bleiben als Exportformat (`kind: command`) für Stufe-1-Fälle weiter möglich, sind aber nicht mehr die Standardgranularität.
2. **Execution-Modell** — Stufe 1 (Canvas als Design-Tool, Mensch orchestriert) vs. Stufe 2 (Master-Agent liest Graph und arbeitet ihn ab). Reifestufen, kein Entweder-oder; beide existieren in der Engine.
   **Entschieden (2026-07-10):** Stufe 2 (Master-Agent orchestriert autonom) ist das primäre Execution-Modell. Stufe 1 bleibt als Design-/Debug-Ansicht im Canvas erhalten (Workflow bauen, einzelne Nodes manuell testen), ist aber nicht mehr der Regelbetrieb.
3. **Persistenz** — Workflow-JSON im Repo (git-versioniert, PR-fähig) vs. nur im Cowork-Artifact.
   **Entschieden (2026-07-10, von Thomas bestätigt):** "Im Repo" ist bereits die etablierte professionelle Methode für Workflow-als-Code — dasselbe Muster wie GitHub-Actions-Workflows (`.github/workflows/*.yml`), Airflow-DAGs oder Temporal-Workflow-Definitionen: Definition versioniert in Git, diff-/PR-fähig, Schema-validiert (`schema/workflow.schema.json`, bereits vorhanden). Eine schwergewichtige Workflow-Orchestrierungsplattform (Airflow/Prefect/Dagster/Temporal) wäre kein "professionellerer" Ersatz, sondern ein Bruch mit der eigenen Konvention (`CLAUDE.md`: Single-File bevorzugt, keine neuen Dependencies ohne Begründung) und für ein Solo-/Dogfooding-Tool überdimensioniert.
   Die eigentliche Lücke liegt woanders: aktuell wird **nur die Definition** persistiert, nicht die **Ausführungshistorie**. `total_cost_usd` u. a. Run-Daten werden im Sandbox-Agent zur Laufzeit geparst (`src/sandbox_agent.py`), aber nirgends dauerhaft abgelegt — nach dem Run sind sie weg. Professionalisierungsschritt wäre, Definition (Git) und Run-Historie (Zustand/Kosten/Logs pro Lauf) sauber zu trennen, z. B. ein append-only Run-Log (JSONL) oder eine leichte SQLite-Datei unter einem eigenen, ggf. gitignorten Verzeichnis (`runs/`) — kein neuer Fremd-Dependency, passt zur bestehenden Konvention. Das ist die naheliegende "professionellere Methode", nicht ein Wechsel weg von Git für die Definition selbst.
   **Umsetzung als Claude-Code-Auftrag vorbereitet:** `docs/CC_PROMPT_run_history_log.md` — noch nicht ausgeführt. **Finale Entscheidungen (2026-07-10, später am Tag):** SQLite statt JSONL (stdlib `sqlite3`, keine neue Dependency); keine Größenbegrenzung/Rotation, aber Warnung auf stderr sobald die Datei >10 MB ist; `run` loggt **standardmäßig** (default-on, Default-Pfad `.aw-runs/runs.sqlite3` relativ zu `--cwd`), Deaktivierung über `--no-run-log`.
   **Erweitert (2026-07-10, Cowork-Audit):** derselbe Claude-Code-Auftrag deckt jetzt zusätzlich zwei weitere Vor-Echtbetrieb-Lücken ab, die beim Real-Files-Audit gefunden wurden — Teil 0: ein verwaistes `.git/index.lock` bereinigen; Teil 1: `--checkpoint`/`--resume` als CLI-Flags nachrüsten (die Library (`run_workflow`) unterstützt beides bereits, nur die CLI reicht es noch nicht durch — bislang nur in `job-search-system/CLAUDE.md` als bekannte Lücke dokumentiert, nicht hier).
   **Umgesetzt (2026-07-10, Cowork-Audit-Nachtrag ausgeführt):** Run-Log implementiert als SQLite (`src/orchestrator.py`, `_append_run_log`), default-on unter `.aw-runs/runs.sqlite3` relativ zu `--cwd`, Warnung auf stderr ab 10 MB, keine automatische Rotation; Deaktivierung über `--no-run-log` bzw. `run_log_path=None`. `--checkpoint PATH` / `--resume` sind jetzt ebenfalls als CLI-Flags verfügbar (`src/cli.py`), nicht mehr nur Library-intern. Details/Tests: `docs/CC_PROMPT_run_history_log.md`, `docs/DEVLOG.md` (Eintrag 2026-07-10).
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
