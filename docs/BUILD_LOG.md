# BUILD_LOG — agentic-workflows

Human-readbares Protokoll: was gebaut wurde, in welcher Reihenfolge, mit welchem Ergebnis,
und nach welcher Methode. Ergänzt `PROJECT_OVERVIEW.md` (Scope/Warum) um die **Chronik**.

Letzte Aktualisierung: 2026-06-25 (Stufe-2-Backend)

## Arbeitsmethode (wie hier gebaut wird)

Das Projekt dogfoodet sich selbst. Jeder Baustein wird als **eigener Workflow-Knoten**
umgesetzt, und zwar nach diesem festen Ablauf:

1. Pro Baustein wird eine Prompt-Datei `docs/CC_PROMPT_<thema>.md` angelegt (Aufgabe,
   API-Vertrag, Tests, **ausführbare Acceptance-Checks**, Constraints, Out-of-scope).
   Diese Prompt-Dateien sind lokale Arbeitsdateien und nicht im öffentlichen Repo enthalten.
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

Reihenfolge entspricht der Bau-Reihenfolge. Alle über `docs/CC_PROMPT_*.md` gebaut (lokal, nicht veröffentlicht).

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
13. **ui-polish** (`CC_PROMPT_ui_polish.md`) — `ui/canvas.html`: (a) Live-Mermaid-Source-Panel
    (`#btnMermaid`/`#mermaidPanel`, `refreshMermaidPanel()` an beiden `renderCanvas`-Exits,
    no-op wenn geschlossen; kein CDN). (b) Round-Trip-Härtung: die mutierenden Zeilen
    `workflow.defaults = {}` / `workflow.edges = []` aus `loadWorkflow` raus, Inspector legt
    `inputs/constraints/acceptance` nur noch lazy beim ersten "+"-Klick an. `#btnRoundtrip` /
    `checkRoundtrip()` prüft Idempotenz + Export-vs-Input-Diff (gemerkter `originalRawText`,
    in-memory). Nicht angezeigte Felder (`cwd`, `timeoutSeconds`, Kanten-`label`, top-level
    `version/description/defaults`) überleben den Round-Trip. Engine + Tests unangetastet.

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
- **UI-Polish (2026-06-22):** Live-Mermaid-Source-Panel (Quelltext, kein CDN — Zero-Deps bleibt)
  + Round-Trip-Härtung (Laden→Export ist jetzt idempotent, keine ungefragt hinzugefügten
  Felder mehr). Round-Trip-Selbstcheck via `#btnRoundtrip`. Siehe Chronik-Knoten 13.

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

## Chronik -- Stufe-2-Backend (2026-06-25)

Bau-Auftrag: `docs/CC_PROMPT_stage2_full_epic.md` (7-Phasen-Epic, autonom ausgefuehrt).
Vorbefund: 17/58 Tests rot (WSL-Bash-Stub). Behoben als Pre-Phase-Commit vor Phase 1.

| Commit | Phase | Inhalt | Tests |
|---|---|---|---|
| `6f23cce` | Bash-Fix | `_find_bash()`, Kandidatenliste, WSL-Stub-Verwerfung | 61 gruen |
| `e9bc48c` | 1 | `sandbox.py`: git-worktree + docker-sandbox + merge-back + `parse_tagged_output` | 87 gruen |
| `c38a066` | 2 | `sandbox_agent.py`: Claude CLI in Container; `Workspace`-Dataclass + `_run_workspace_node` in Orchestrator; `--sandbox/--image/--memory` CLI-Flags | 101 gruen |
| `bab72dd` | 3 | `Dockerfile` (node:20-slim, claude-code via npm); `docs/IMAGE.md` als Spec (Docker Daemon nicht aktiv, deferred) | 101 gruen |
| `e3858e7` | 4 | `_run_workflow_waves()` via `ThreadPoolExecutor` + `topological_waves`; deterministischer Merge in Wellen-Reihenfolge; `max_parallel=1` unveraendert sequenziell | 104 gruen |
| `f0624ff` | 5 | `planner.py`: `PLAN_SCHEMA`, `extract_plan_from_json` (Claude nativer JSON-Output), `extract_plan_from_tagged` (XML-Fallback), `expand_plan(plan) -> (nodes, edges)` | 120 gruen |
| `a60cffd` | 6 | `docs/STAGE2_RUNBOOK.md` (Hetzner-Schritte); `examples/smoke-stage2.json` (1-Knoten, validate ok) | 120 gruen |
| `ba35319` | 7 | `docs/STAGE3_OPENCLAW.md` (Architektur-Spec, dezentrale Worker via git); `src/openclaw_stub.py` (NotImplementedError) | 120 gruen |

### Abweichungen / Entscheidungen

- **Phase 5 `expand_plan`-Signatur**: Spec sagte `list[node-dict]`, implementiert als `(nodes, edges)` da
  `dependsOn` sonst nicht in Kanten uebersetzt werden kann. Sinnvoller als die Spezifikation.
- **Phase 3 deferred**: Docker-Daemon nicht aktiv auf Thomas' Windows-Maschine -- `IMAGE.md` als
  vollstaendige Build-Spec, echter Build auf Hetzner (Schritt 4 im Runbook).
- **Bash-Fix Pre-Phase**: `shutil.which("bash")` lieferte auf Windows den WSL-System32-Stub statt
  Git Bash. Fix: `_find_bash()` mit expliziten Kandidaten und `bash -lc "true"` Probe.

## Aktueller Stand (2026-06-25, Abend) -- HANDOFF fuer naechste Session

- **Stufe-2-Backend vollstaendig** (Code-seitig), 7 Phasen-Commits.
- **Teil 0 nachgezogen (Commit `c06c387`):** API-Key-Passthrough -- `run_in_sandbox` bekam
  `env_passthrough` (Default `["ANTHROPIC_API_KEY"]`), reicht `-e ANTHROPIC_API_KEY` (ohne Wert)
  in den Container. War ein BLOCKER: vorher hatte der Agent-Container keinen Key -> der Smoke
  waere garantiert an Auth gescheitert. Runbook + IMAGE.md korrigiert.
- **Tests: 127 gruen auf Windows (maßgeblich).** ACHTUNG: die bash-Sandbox liest den
  Windows-Mount truncated/stale (Memory `sandbox-repo-verify-unreliable`) -- Sandbox-pytest-Zahlen
  NICHT vertrauen, nur Thomas' lokalem Lauf / Claude Code.
- **Commits lokal, noch NICHT gepusht.**
- **Stage 3 (OpenClaw):** Spec vorhanden, Implementierung deferred.

## Naechste Schritte (Reihenfolge)

1. **Push:** `git push origin main` (lokal ahead).
2. **Hetzner-Smoke:** `docs/STAGE2_RUNBOOK.md` Schritt fuer Schritt per SSH (capstone2,
   <user>@<server>): prune -> reboot -> pull -> `docker build` -> `python -m src.cli run
   examples/smoke-stage2.json --sandbox --image aw-sandbox:dev --memory 1.5g`. Box: 4 Cores,
   7,6 GiB RAM, 19 GB Disk frei, KEINE GPU.
3. **Review-Fixes Teil A/B/C** (`docs/CC_PROMPT_stage2_review_fixes.md`; Teil 0 erledigt):
   A = Kosten-Instrumentierung (`--output-format json` -> `total_cost_usd` ins Run-Summary),
   B = `merge_back` braucht `git merge --abort` bei Konflikt (sonst vergiftet er Folge-Knoten),
   C = `create_worktree` im Wellen-Modus serialisieren (Race auf `.git/index.lock`).
4. **Image pinnen:** nach erstem Build `docs/IMAGE.md` mit echter CLI-Version (2.1.191).
5. **Doku-only / offene Design-Entscheidungen:** Gate laeuft auf Host statt im Container
   (Repro-Luecke); Planner-Knoten ungated (acceptance-Platzhalter `true`); `idle_timeout` ist
   nur Wall-Fallback. tomllib-Fallback (Python >= 3.11).

## Verwandte Dateien

| Datei | Inhalt |
|---|---|
| `README.md` | Pitch, Datenmodell, acceptance-Erklärung, Minimalbeispiel |
| `docs/PROJECT_OVERVIEW.md` | Scope, Warum, Reifestufen, Kosten-Routing, Backend-Kandidaten |
| `docs/DECISION_backend.md` | Backend-Entscheidung Stufe 2 (Matrix, kein Port, Worker=API, Hetzner-Kapazität, OpenClaw=Stufe-3-Trigger) |
| `docs/concept.md` | Gesamtkonzept (vom `docs-concept`-Knoten erzeugt) |
| `docs/CC_PROMPT_*.md` | je ein Bau-Auftrag pro Knoten (Quelle der Build-Historie; lokal, nicht veröffentlicht) |
| `schema/workflow.schema.json` | Datenmodell (Source of Truth) |
| `ui/canvas.html` | Single-File-Canvas-UI (laden/editieren/validieren/exportieren im Browser) |
| `meta-workflow.json` | die eigene Roadmap als ausführbarer Workflow (Dogfooding) |
