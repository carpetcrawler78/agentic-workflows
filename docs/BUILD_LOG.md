# BUILD_LOG — agentic-workflows

Human-readbares Protokoll: was gebaut wurde, in welcher Reihenfolge, mit welchem Ergebnis,
und nach welcher Methode. Ergänzt `PROJECT_OVERVIEW.md` (Scope/Warum) um die **Chronik**.

Letzte Aktualisierung: 2026-06-22

## Arbeitsmethode (wie hier gebaut wird)

Das Projekt dogfoodet sich selbst. Jeder Baustein wird als **eigener Workflow-Knoten**
umgesetzt, und zwar nach diesem festen Ablauf:

1. Pro Baustein wird eine Prompt-Datei `docs/CC_PROMPT_<thema>.md` angelegt (Aufgabe,
   API-Vertrag, Tests, **ausführbare Acceptance-Checks**, Constraints, Out-of-scope).
2. Diese Datei wird in **Claude Code** ausgeführt — dort entsteht der eigentliche Code.
   Im Cowork-Chat wird der Code NICHT direkt geschrieben (bewusste Trennung; siehe Memory
   `build-via-cc-prompts`).
3. Verifikation in der Sandbox: `py_compile`, `pytest -q`, gezielte Smoke-Checks.

Der rote Faden ist immer der **acceptance-Check**: ein Knoten gilt nur als fertig, wenn seine
Shell-Kommandos mit dem erwarteten Exit/Pattern zurückkommen. Genau dieses Prinzip ist auch
das Produkt selbst.

## Pipeline-Architektur (was die Module tun)

Design-Time → Runtime, als Kette:

| Stufe | Modul | Aufgabe |
|---|---|---|
| Validieren | `src/loader.py` | `workflow.json` gegen `schema/workflow.schema.json` prüfen; sammelt ALLE Fehler (`WorkflowValidationError.issues`) |
| Exportieren | `src/export.py` | pro Knoten `.claude/commands|agents/<id>.md` + `WORKFLOW.md` (Mermaid + Prompts inline). Reine `render_*`-Funktionen, getrennt vom Schreiben |
| Reihenfolge | `src/runner.py` | `topological_order` (Kahn, deterministisch) + `topological_waves`; referenzielle Integrität + Zyklus-Erkennung (`WorkflowCycleError`/`WorkflowGraphError`) |
| Gate | `src/executor.py` | acceptance-Kommandos via `subprocess` ausführen, gegen `expect` prüfen (nur gesetzte Schlüssel, UND-verknüpft) |
| Orchestrator | `src/orchestrator.py` | verdrahtet alles: Knoten in Topo-Reihenfolge → Agent (injizierbar) → Gate; `stop_on_failure`, `skipped`, Checkpoint/Resume |
| CLI | `src/cli.py` | gemeinsamer Entrypoint: `python -m src.cli {validate|export|run} ...` |

## Chronik der Knoten

Reihenfolge entspricht der Bau-Reihenfolge. Alle über `docs/CC_PROMPT_*.md` gebaut.

1. **implement-validator + test-validator** (`CC_PROMPT_validate_workflow.md`) — `loader.py`,
   8 Tests. Validierung sammelt alle Verstöße statt beim ersten zu stoppen.
2. **document-schema** (README-Edit, direkt) — Datenmodell + acceptance-Check + Minimalbeispiel
   im `README.md` dokumentiert.
3. **export-artifacts** (`CC_PROMPT_export_artifacts.md`) — `export.py` Pro-Knoten-Artefakte,
   +4 Tests.
4. **workflow-spec** (`CC_PROMPT_workflow_spec.md`) — `render_workflow_md` / `WORKFLOW.md`
   (Mermaid + Prompts), `--spec`-Flag, +5 Tests.
5. **runner-toposort** (`CC_PROMPT_runner_toposort.md`) — `runner.py`, Kahn + Zyklus/Ref-Check,
   +7 Tests.
6. **acceptance-executor** (`CC_PROMPT_acceptance_executor.md`) — `executor.py`, +10 Tests.
   Nur tatsächlich gesetzte `expect`-Schlüssel werden geprüft (kein injizierter Default-Exit).
7. **orchestrator** (`CC_PROMPT_orchestrator.md`) — `orchestrator.py`, Agent als injizierbares
   Callable (testbar ohne echtes Claude Code), Verify-Only vs. `--execute`, +9 Tests.
8. **meta-workflow** (`CC_PROMPT_meta_workflow.md`) — `meta-workflow.json`: die eigene Roadmap
   als DAG (5 Knoten), +3 Tests. Dogfooding-Artefakt.
9. **unify-cli** (`CC_PROMPT_unify_cli.md`) — `src/cli.py`, erster real gebauter
   meta-workflow-Knoten.
10. **package-project / runner-waves / orchestrator-resume / docs-concept**
    (`CC_PROMPT_meta_remaining.md`) — `pyproject.toml`, `topological_waves`,
    Checkpoint/Resume, `docs/concept.md`.
11. **ui-canvas** (`CC_PROMPT_ui_canvas.md`) — `ui/canvas.html`, Single-File-Canvas-UI:
    laden/editieren/validieren/exportieren im Browser. Export byte-identisch gegen `src/export.py`.
12. **executor-shell-fix** (`CC_PROMPT_executor_shell_fix.md`) — `src/executor.py` von
    `subprocess.run(shell=True)` auf explizites `bash -lc` umgestellt (Default
    `_DEFAULT_SHELL = ["bash", "-lc"]`, Pfadauflösung via `shutil.which` gegen den
    WSL-Relay-Stub in System32). `shell`-Parameter additiv an `run_check`/`run_node`,
    `FileNotFoundError` → `CheckResult(passed=False, exit_code=None)` statt Crash. +4 Tests.

## Aktueller Stand (2026-06-22)

- **Engine komplett**, end-to-end lauffähig. Beispiel-Workflow läuft 3/3 durchs Gate.
- **58 Tests grün** (loader 8, export 9, runner 13, executor 14, orchestrator 11, +meta 3).
- **Executor plattformrobust**: `bash -lc` explizit gesetzt, Windows-WSL-Stub umgangen
  (verifiziert 2026-06-22, alle Acceptance-Checks grün).
- **meta-workflow 5/5** auf Thomas' Maschine (Python 3.11). Der Backlog der eigenen Roadmap
  ist damit abgearbeitet — das Tool hat seine eigenen nächsten Stufen selbst gebaut.
- **UI gebaut**: `ui/canvas.html` (Single-File, keine Deps, kein Build-Step). Laden via
  Datei-Picker/Drag&Drop/Paste; Canvas mit Auto-Layout (JS-Port der Kahn-Wellen aus
  `runner.py`); Inspector pro Slot editierbar; Browser-Validierung als Komfort-Spiegel
  (`src/loader.py` bleibt Source of Truth); Export `workflow.json` + `WORKFLOW.md` im Browser,
  byte-identisch gegen `src/export.py` verifiziert. „Run mit Gate" gibt nur den CLI-Befehl aus.
  Gebaut über `CC_PROMPT_ui_canvas.md`.

## Zwei Ausführungsmodi (Stufe 1 vs. Stufe 2 — beide existieren in der Engine)

- **Export-only** (`export.py`): Canvas/Engine erzeugt nur Artefakte; der Mensch arbeitet die
  Slash-Commands in Claude Code selbst ab. Kein autonomes Risiko.
- **Run mit Gate** (`orchestrator.py`): die Engine läuft den DAG selbst ab, je Knoten Agent +
  automatisches acceptance-Gate. Der nächste Knoten startet nur bei grünem Gate.

Die README-Designfrage #2 ("Canvas-only vs. Master-Agent") ist damit kein Entweder-oder mehr —
die Engine kann beides, die UI bietet es als Umschalter an.

## Bekannte Probleme / Umgebungs-Annahmen (wichtig)

- **Shell auf Windows (GELÖST 2026-06-22):** `executor.py` nutzte `subprocess.run(shell=True)`
  — auf Windows cmd.exe, nicht bash, sodass bash-Stil-Checks (`grep`, `test -f`, `pytest`) nur
  zufällig grün waren. Fix-Option (b) umgesetzt: explizites `bash -lc` mit `shutil.which`-
  Pfadauflösung (umgeht den WSL-Relay-Stub in System32). Fehlt bash, gibt es ein sauberes
  `CheckResult(passed=False)` statt Crash. Siehe Chronik-Knoten 12.
- **tomllib braucht Python ≥ 3.11.** Der `package-project`-acceptance-Check
  (`python -c "import tomllib; ..."`) fällt auf Python 3.10. Bei Bedarf robuster: `tomli`-Fallback.
- **git aus der Sandbox** scheitert auf gemounteten Windows-Ordnern — git-Befehle gehören in
  Thomas' eigenes Terminal (Memory `sandbox-git-on-windows-mount`).

## Nächste Schritte

1. **UI-Polish** (`ui/canvas.html` steht): Feinschliff, ggf. Live-Mermaid-Preview, Round-Trip-
   Härtung.
2. Weitere meta-workflow-Knoten bzw. neue Workflows (z.B. ein nicht-Dev-Workflow als Beweis
   der Allgemeinheit — Idee "Steuer-/Dokumenten-Sammler" wurde diskutiert, noch nicht gebaut).
3. **tomllib-Fallback** (`package-project`-Check braucht Python ≥ 3.11) und README-Status
   von "Konzeptphase" auf den realen Stand bringen — beides niedrige Prio.

## Verwandte Dateien

| Datei | Inhalt |
|---|---|
| `README.md` | Pitch, Datenmodell, acceptance-Erklärung, Minimalbeispiel |
| `docs/PROJECT_OVERVIEW.md` | Scope, Warum, Reifestufen, Kosten-Routing, Backend-Kandidaten |
| `docs/concept.md` | Gesamtkonzept (vom `docs-concept`-Knoten erzeugt) |
| `docs/CC_PROMPT_*.md` | je ein Bau-Auftrag pro Knoten (Quelle der Build-Historie) |
| `schema/workflow.schema.json` | Datenmodell (Source of Truth) |
| `ui/canvas.html` | Single-File-Canvas-UI (laden/editieren/validieren/exportieren im Browser) |
| `meta-workflow.json` | die eigene Roadmap als ausführbarer Workflow (Dogfooding) |
