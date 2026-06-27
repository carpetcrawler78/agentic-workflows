# DEVLOG -- agentic-workflows

Lernprotokoll: Was hat funktioniert, was nicht, welche Regeln daraus entstanden sind.
Format: DONE / MISTAKE / RULE je Eintrag.

---

## 2026-06-25 -- Stufe-2-Backend-Epic

### DONE

- Bash-Resolver-Problem geloest: `shutil.which("bash")` lieferte auf Windows
  `C:\Windows\System32\bash.EXE` (WSL-Relay-Stub), der `bash -lc` nicht versteht.
  Loesung: `_find_bash()` mit expliziten Git-Bash-Kandidaten und Live-Probe (`bash -lc "true"`).
  Kandidatenliste + WSL-Stub-Verwerfung + injectable `which_fn`/`run_fn` fuer Tests.

- 7 Phasen autonom gebaut (Bash-Fix + Phasen 1-7), 120 Tests gruen, 8 Commits.
  Alle commits lokal, kein Push (Thomas entscheidet nach Review).

- `parse_tagged_output` als provider-agnostischer Fallback behalten, aber fuer Claude
  ist `--output-format json --json-schema` der Hauptpfad (kein XML-Scan noetig).

- Paralleler Modus (`_run_workflow_waves`) trennt sauber: pro Welle alle Knoten
  nebenlaeufig (subprocess-bound -> ThreadPoolExecutor), Merge immer sequenziell
  in Wellen-Reihenfolge (deterministisch, reproduzierbar).

### MISTAKE

- **`expand_plan`-Signatur zu eng spezifiziert**: Urspruengliche Spec sagte
  `expand_plan(plan) -> list[node-dict]`. Kann `dependsOn` nicht in Kanten uebersetzen.
  Implementiert als `(nodes, edges)` -- sinnvoller, aber Abweichung zur Spec.
  Regel: Spec-Signaturen fruehzeitig auf Vollstaendigkeit pruefen (enthaelt die Rueckgabe
  alle Informationen, die der Aufrufer braucht?).

- **WSL-Bash-Problem nicht beim ersten Fix vollstaendig behoben**: Erster Versuch
  liess `run_check` noch `shutil.which("bash")` fuer den `executable`-Parameter
  aufrufen, wenn der Caller explizit `shell=["bash", ...]` uebergab. Zwei Tests
  brachen nach dem initialen Fix. Zweiter Fix: `if cmd == "bash": executable = _DEFAULT_BASH`.
  Regel: Wenn ein Problem mehrere Code-Pfade hat, alle Pfade im ersten Fix abdecken,
  nicht nur den offensichtlichen.

- **Docker-Daemon auf Entwicklungsmaschine**: Phase 3 (Dockerfile) baute das Image,
  aber der Docker-Daemon war auf Thomas' Windows-Maschine nicht aktiv. Deferred mit
  `IMAGE.md` als Spec -- korrekte Entscheidung, aber frueher haefte ich checken
  sollen ob Docker verfuegbar ist (vor dem Build-Schritt, nicht danach).

### RULE

- **Candidate-List statt Single-Which fuer Plattform-Tools**: Wenn `shutil.which`
  auf verschiedenen Systemen unterschiedliche (moeglicherweise falsche) Ergebnisse
  liefert, explizite Kandidaten-Liste + Live-Probe vorziehen. Gilt fuer bash, git,
  docker etc.

- **Parallele Knotenausfuehrung: Merge immer sequenziell halten**: Auch wenn Knoten
  nebenlaeufig laufen, Merge-Reihenfolge deterministisch (Wellen-Index/sortiert).
  Sonst nicht-reproduzierbare git-History und schwer diagnostizierbare Konflikte.

- **Acceptance-Gate laeuft im Worktree, nicht im Hauptrepo**: Gate-Checks (acceptance-
  Kommandos) laufen mit `cwd_root=worktree.path`. Merge nur bei gruenem Gate. Das ist
  die zentrale Qualitaets-Sicherung von Stufe 2.

- **API-Key niemals ins Image**: ANTHROPIC_API_KEY immer als `-e`-Flag zur Laufzeit,
  nie als ARG/ENV im Dockerfile. Verletzt Commit history bleibt sauber.

---

## 2026-06-27 -- Hetzner-Smoke Hotfixes permanent ins Repo

### DONE

- Vier Hotfixes aus dem Hetzner-Klon sauber ins Repo uebertragen; alle 130 Tests gruen.
- Smoke-Status und uid-1000-Voraussetzung in `docs/STAGE2_RUNBOOK.md` dokumentiert.

### MISTAKE

- **Sandbox-Importe in `cli.py` als bare Imports**: `from sandbox_agent import ...` und
  `from orchestrator import Workspace` im `--sandbox`-Pfad standen nackt, ohne das
  try/except-Muster wie am Dateikopf. Scheiterte mit `ModuleNotFoundError` bei
  `python -m src.cli ... --sandbox`.

- **Container als root**: `node:20-slim` startet als root. Claude CLI verweigert
  `--permission-mode bypassPermissions` unter root ("cannot be used with root/sudo
  privileges"). `USER node` am Dateiende des Dockerfile wurde vergessen.

- **Prompt als argv uebergeben**: `claude -p '<prompt>'` scheiterte, weil
  `render_node` YAML-Frontmatter (`---`) liefert und die CLI die fuehrenden
  Bindestriche als Option parst. Fix: `printf %s '<prompt>' | claude -p ...`.

- **`create_worktree` nicht idempotent**: abgebrochene Laeufe hinterlassen den Branch
  `agent/<node_id>`. Folgelauf scheitert an `git worktree add -b` ("branch already
  exists"). Cleanup-Sequenz (worktree remove --force, prune, branch -D) vor dem
  `worktree add` eingebaut.

### RULE

- **Sandbox-Importe immer ueber try/except-Guard wie Dateikopf**: Relative Importe
  (`.sandbox_agent`) zuerst, bare als Fallback. Gilt fuer alle Importe, die vom
  Aufrufkontext (`python -m src.cli` vs. `python src/cli.py`) abhaengen.

- **Agent-Container non-root betreiben**: `USER <non-root>` an Dockerfile-Ende noetig,
  wenn die CLI `bypassPermissions` verlangt. Build-Schritte bleiben als root; nur
  Laufzeit wechselt den User.

- **Prompt via stdin, wenn Inhalt mit `-` beginnen kann**: `printf %s '<prompt>' | claude -p`
  statt `-p '<prompt>'` als argv. Verhindert CLI-Fehlinterpretation von Frontmatter-
  oder Optionszeichen am Prompt-Anfang.

- **worktree-Erzeugung idempotent: alten Branch wegraeumen**: Vor `git worktree add -b`
  stets Cleanup-Sequenz (remove --force, prune, branch -D) laufen lassen und Fehler
  tolerieren. Verhindert Vergiftung von Folgelaeufen nach Abbruch.

---

## 2026-06-27 -- Restarbeiten Stufe 2 (Fix A/B/C/D)

### DONE

- **Fix B**: `merge_back` bricht fehlgeschlagenen Merge sauber ab (`git merge --abort`).
  Repo bleibt nicht im halb-gemergten Zustand -- der naechste Knoten findet sauberen Index.

- **Fix C**: `create_worktree`-Aufrufe im Wellen-Modus ueber `threading.Lock` serialisiert.
  `git worktree add` laeuft nie gleichzeitig aus mehreren Threads -> kein `.git/index.lock`-
  Rennen. Agent-Aufruf (docker-Container) bleibt nebenlaeufig.

- **Fix A**: Kosten-Instrumentierung vollstaendig: `--output-format json` an CLI,
  `total_cost_usd` defensiv aus stdout geparst, in `NodeRun.cost_usd` gespeichert,
  `_print_summary` gibt `Gesamtkosten: $X.XXXX` aus wenn mindestens ein Knoten meldet.
  Backward-compat: Agenten die None zurueckgeben (alle bisherigen Tests) unveraendert.

- **Fix D**: `docs/IMAGE.md` auf verifiziert-2026-06-27 aktualisiert, Non-root-Sektion
  (USER node, uid 1000) ergaenzt, TODO-Checkboxen auf Stand gebracht.

- 10 neue Tests, volle Suite: 140 Tests gruen (war 130).

### MISTAKE

- **merge_back-Test: "abort" vs "--abort" als Listenelement**: Test pruefte `"abort" in cmd`,
  aber das cmd-Element ist `"--abort"`. Catch: sofort beim ersten Test-Run entdeckt.
  Regel: beim Pruefen von argv-Listen immer das exakte Token (`"--abort"`) verwenden,
  nicht einen Teilstring-Match auf die Liste.

### RULE

- **Merge immer abort bei Fehlschlag**: Bei `merge --no-ff` Fehlschlag sofort
  `merge --abort` (Fehler tolerieren). Verhindert vergifteten Index fuer Folgeknoten.

- **git-Operationen in Thread-Pools serialisieren**: `git worktree add/remove` und
  `merge` nie echt parallel -- immer unter `threading.Lock`. Parallelitaet liegt
  im Container-Lauf, nicht im git-Schritt.

- **Kosten defensiv parsen**: `json.loads` + `data.get(...)` + isinstance-Check
  in try/except. CLI kann andere Felder liefern oder JSON weglassen -- nie annehmen,
  dass das Feld da ist.
