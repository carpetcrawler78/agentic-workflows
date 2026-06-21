# Konzept

Dieses Dokument (`docs/concept.md`) beschreibt das Gesamtkonzept von
`agentic-workflows`: das Problem,
das Datenmodell, die Verarbeitungs-Pipeline, das CLI und das Dogfooding-Setup.
Es ergaenzt das `README.md`, das den schnellen Einstieg liefert.

## Problem und Idee

Agentic-Coding-Workflows mit Claude Code bestehen oft aus mehreren Schritten, die
voneinander abhaengen: implementieren, testen, dokumentieren, paketieren. Heute
werden solche Schritte meist ad-hoc als Prompts formuliert, ohne dass der
Fortschritt strukturiert nachvollziehbar oder automatisch verifizierbar ist.

Die Idee: einen Workflow als DAG (gerichteter azyklischer Graph) modellieren, ihn
in einer Datei versionieren, und jeden Knoten mit einem **ausfuehrbaren
acceptance-Check** versehen. Damit wird aus einer Prompt-Sammlung ein Artefakt,
das sich validieren, exportieren und automatisiert abarbeiten laesst.

## Datenmodell

Ein Workflow ist eine JSON-Datei gegen `schema/workflow.schema.json` (JSON-Schema
Draft 2020-12). Die beiden Kernfelder sind:

- **`nodes[]`** — ein Knoten ist ein verifizierbar abschliessbarer Task mit `id`,
  `goal` und mindestens einem `acceptance`-Check. Optional: `title`, `inputs[]`,
  `constraints[]`, `comments`, `model` (Kosten-Routing: `planner` | `sonnet` |
  `local`) und `kind` (Export-Granularitaet: `command` | `agent`).
- **`edges[]`** — gerichtete Abhaengigkeiten (`from` muss fertig sein, bevor `to`
  startet). Die Kanten spannen den DAG auf.

Der **acceptance-Block** ist der Hebel, der autonome Ausfuehrung ueberhaupt
ermoeglicht: ein Knoten gilt nur als fertig, wenn alle seine Checks bestehen. Ein
Check ist ein Shell-Kommando plus erwartetes Ergebnis (`exitCode`,
`stdoutMatches`, `stdoutNotMatches`, `stderrMatches` — UND-verknuepft). Details
und ein Minimalbeispiel stehen im `README.md`-Abschnitt "Acceptance-Check".

## Pipeline

Die Module unter `src/` bilden eine lineare Pipeline vom Rohtext bis zur
Ausfuehrung:

1. **`loader.py`** — validiert eine Workflow-Datei gegen das Schema und sammelt
   *alle* Verstoesse in einer `WorkflowValidationError`, statt beim ersten
   abzubrechen.
2. **`export.py`** — rendert validierte Knoten zu Claude-Code-Artefakten:
   `.claude/commands/<node-id>.md`, `.claude/agents/<node-id>.md`, oder als
   Single-File-Spec `WORKFLOW.md` mit eingebettetem Mermaid-Diagramm.
3. **`runner.py`** — bestimmt die Abarbeitungsreihenfolge per topologischer
   Sortierung (Kahn's Algorithmus). `topological_order` liefert eine flache
   Liste, `topological_waves` gruppiert stattdessen in Wellen voneinander
   unabhaengiger Knoten (Basis fuer parallele Ausfuehrung).
4. **`executor.py`** — fuehrt die acceptance-Checks eines einzelnen Knotens als
   Shell-Kommandos aus und wertet `expect` dagegen aus.
5. **`orchestrator.py`** — verdrahtet die vorigen Schritte zu einem Lauf: pro
   Knoten optional ein injizierbarer Agent-Schritt (Dependency Injection, damit
   der Kern ohne echten Claude-Code-Aufruf testbar bleibt), danach das
   acceptance-Gate. Bei Fehlschlag wird per Default gestoppt. Optional laesst
   sich der Fortschritt als Checkpoint-Datei (JSON mit bestandenen node-ids)
   persistieren; mit `resume=True` ueberspringt ein Folgelauf bereits bestandene
   Knoten und setzt beim ersten offenen Knoten fort.

## CLI

`src/cli.py` buendelt die Modul-CLIs hinter einem Entrypoint
`python -m src.cli <subcommand> ...` (bzw. nach `pip install` als Konsolen-Script
`agentic-workflows`):

- `validate <workflow.json>` — Schema-Validierung, keine Seiteneffekte.
- `export <workflow.json> [--out DIR] [--spec]` — Pro-Knoten-Artefakte oder mit
  `--spec` die `WORKFLOW.md`-Gesamtspec.
- `run <workflow.json> [--cwd DIR] [--no-stop] [--execute]` — Verify-Only per
  Default; mit `--execute` wird ein echter Claude-Code-Agent aufgerufen.

Jedes Subcommand ist ein duenner Wrapper um die jeweilige Modul-Funktion — Logik
wird nicht dupliziert.

## Dogfooding via meta-workflow.json

Sobald das Tool nutzbar war, wurde die Weiterentwicklung des Projekts selbst als
Workflow-Instanz modelliert: `meta-workflow.json` im Repo-Root beschreibt die
naechsten Ausbaustufen (CLI vereinheitlichen, Paketierung, Parallel-Wellen,
Checkpoint/Resume, diese Konzept-Doku) als Knoten mit echten, ausfuehrbaren
acceptance-Checks. Der Fortschritt laesst sich jederzeit mit
`python -m src.cli run meta-workflow.json --no-stop` ueberpruefen — das Tool
verifiziert damit seine eigene Weiterentwicklung.
