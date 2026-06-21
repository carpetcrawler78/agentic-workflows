# agentic-workflows — Projekt-Übersicht (Scope, Warum, Stand)

Stand: 2026-06-21 (Engine komplett; Chronik in `BUILD_LOG.md`)

Diese Datei fasst zusammen, **was** das Projekt ist, **warum** es existiert und **was bisher
erarbeitet** wurde. Sie ist der Einstiegspunkt; Details stehen in den verlinkten Dateien.

## In einem Satz

Ein visuelles Tool, mit dem man Dev-Workflows als DAG zeichnet, pro Node strukturierte Slots
ausfüllt (Ziel, Inputs, Constraints, Acceptance, Kommentare) und daraus ausführbare Artefakte
für Claude Code (Slash-Commands, Sub-Agents, Mermaid-Spec) generiert.

## Warum (Rationale)

Agentic Engineering funktioniert Mitte 2026 zuverlässig nur für **eng umrissene, verifizierbare**
Tasks (Refactor, Test grün ziehen, Migration). Für "großes Projekt komplett autonom von
Architektur bis fertig" explodiert der Fehler-Loop. Der entscheidende Skill ist deshalb, Tasks
so zu **schneiden**, dass ein Agent sie verifizierbar abschließen kann.

Genau dafür ist dieses Tool gedacht: Der Wert liegt nicht in der hübschen Canvas-UI, sondern im
**Acceptance-Slot** — dem maschinell prüfbaren Kriterium pro Node (Build grün, Test grün, Diff
sauber, grep-Match). Ohne das bleibt jeder autonome Lauf teurer und unzuverlässiger als der
manuelle Relay (Prompt rauskopieren → Claude Code → prüfen → nächster Node).

Das Tool ist im Kern ein Werkzeug fürs **verifizierbare Task-Schneiden**.

## Scope

**In scope:**

- Datenmodell für Workflows als JSON (`nodes[]` + `edges[]`), git-versionierbar.
- Pro Node: Ziel, Inputs, Constraints, **ausführbares Acceptance-Kriterium**, Kommentare,
  optional ein Modell-Hint (`planner | sonnet | local`) fürs Kosten-Routing.
- Export nach `.claude/commands/<node>.md`, `.claude/agents/<node>.md`, `WORKFLOW.md`
  (Mermaid + Prompts inline).
- Perspektivisch: ein Master-Agent, der den Graph liest und abarbeitet (Stufe 2, siehe unten).

**Out of scope (bewusst):**

- Kein eigenes Sandbox-/Container-Framework — das übernimmt ein Execution-Backend
  (sandcastle oder OpenClaw), siehe `sandcastle-master-slave-analysis.md`.
- Kein vollautonomer "Architektur-bis-fertig"-Anspruch.

## Execution-Modell — zwei Reifestufen (Designfrage #2)

Die README-Optionen "Canvas-only vs. Master-Agent" sind keine Alternativen, sondern Stufen:

1. **Stufe 1 — Canvas als Design-Tool, Mensch als Orchestrator.** DAG zeichnen, Slots füllen,
   Nodes manuell abarbeiten. Sofort nutzbar, kein autonomes Risiko.
2. **Stufe 2 — Master-Agent arbeitet den Graph ab.** Erst sinnvoll, wenn jeder Node ein
   maschinell prüfbares Acceptance-Kriterium hat. Vorher eskaliert der Fehler-Loop und der
   autonome Lauf wird teurer als der manuelle.

Konsequenz fürs Datenmodell: `acceptance` darf **kein Freitext** sein, sondern braucht einen
ausführbaren Check (Shell-Kommando + erwarteter Exit/Pattern). Das ist die Voraussetzung dafür,
dass Stufe 2 überhaupt greifen kann.

## Kosten-Routing (teurer Planer, billiger Worker)

Kosten = Tokenmenge × Preis. Das Volumen sitzt beim **Worker** (Files lesen, Code generieren),
nicht beim **Planer** (Graph lesen, nächsten Node wählen). Daraus folgt:

- Teures Modell als Planer, billiges als Worker.
- Sweet Spot Worker: **Sonnet** (zuverlässig genug fürs Coding, deutlich billiger als Opus).
- Lokale Mini-LLMs (z.B. qwen2.5:7b via Ollama) nur für Trivial-Tasks (Textersetzung,
  JSON-Massage). Für mehrdateiige Refactors mit Build-Loop zu schwach → Rework frisst die
  Ersparnis.
- Catch: ein zu schwacher Worker erzeugt mehr Korrektur-Loops → kann teurer werden als gleich
  das gute Modell. Ersparnis nur, wenn Worker "gut genug" für den Node ist.
- Daher: ein Modell-Hint pro Node im Datenmodell.

## Execution-Backend für Stufe 2

Zwei Kandidaten, Entscheidung steht aus:

- **sandcastle** (TypeScript-Library) — löst Worktree + Container + Branch + Merge sauber, ist
  explizit auf Multi-Branch-Merge ("merge agent") ausgelegt. Detailanalyse inkl. Master/Slave-
  Mapping: `sandcastle-master-slave-analysis.md`. Fazit: liefert die Slave-Ausführungsebene,
  uns fehlt nur der Master-Scheduler + Acceptance-Gating obendrauf.
- **OpenClaw** (self-hosted, autonom-loopendes Agent-Framework) — always-on Dauerprozess,
  self-trigger auf Events. Bei sensiblen Daten self-hosted auf eigener Box (Hetzner) statt
  Managed (MyClaw.ai), konsistent mit dem GDPR-Reflex aus SentinelAI. Details:
  `notes_2026-05-31_execution-und-kosten.md`.

## Offene Designfragen

1. **Granularität pro Node** — ein Node = ein Slash-Command (klein, viele Nodes) vs. ein Node =
   ein ganzer Sub-Agent (groß, wenige Nodes). Hängt mit dem Acceptance-Check zusammen
   (kleiner Node = ein Check, großer Node = mehrere).
2. **Execution-Modell** — Stufe 1 vs. Stufe 2 (siehe oben). Reifefrage, kein Entweder-oder.
3. **Persistenz** — Workflow-JSON im Repo (git-versioniert, PR-fähig) vs. nur im Cowork-Artifact.
4. **Backend** — sandcastle vs. OpenClaw für Stufe 2.

## Code-Konventionen

- Single-File-Artifact bevorzugt (HTML + JS inline), bis Komplexität ein Build-System
  rechtfertigt.
- Keine neuen Dependencies ohne Begründung im Commit.
- Datenformat: JSON, Schema in `schema/workflow.schema.json` (folgt).
- Self-Reference-Ziel: Sobald nutzbar, wird die Weiterentwicklung dieses Projekts selbst über
  einen `meta-workflow.json` orchestriert (Dogfooding).

## Bisher erarbeitet

- **Konzept + Datenmodell** — `README.md`, `schema/workflow.schema.json` (DAG, Slots,
  ausführbarer acceptance-Check). Designdiskussionen in `notes_2026-05-31_*` und
  `sandcastle-master-slave-analysis.md`.
- **Engine komplett gebaut (2026-06-20/21)** — die gesamte Pipeline steht und ist getestet:
  `loader` (validieren) → `export` (Artefakte + `WORKFLOW.md`) → `runner` (Topo + Wellen +
  Zyklus-Check) → `executor` (acceptance-Gate) → `orchestrator` (verdrahtet alles,
  Verify-Only vs. `--execute`, Checkpoint/Resume) → `cli` (gemeinsamer Entrypoint).
  **46 Tests grün**, Beispiel-Workflow läuft end-to-end durchs Gate.
- **Dogfooding live** — `meta-workflow.json` hält die eigene Roadmap als DAG; vier der fünf
  Knoten (`unify-cli`, `package-project`, `runner-waves`, `orchestrator-resume`,
  `docs-concept`) wurden vom Tool selbst gebaut. Chronik: `BUILD_LOG.md`.

Vollständige Bau-Historie inkl. bekannter Umgebungs-Probleme (cmd.exe-vs-bash beim Executor,
`tomllib`≥3.11): siehe `docs/BUILD_LOG.md`.

## Nächster Schritt

1. **UI** — Single-File-HTML-Canvas (`docs/CC_PROMPT_ui_canvas.md` liegt bereit). Erste
   endnutzer-zugewandte Schicht; Export-only läuft im Browser, "Run mit Gate" gibt den
   CLI-Befehl aus.
2. **Executor-Shell-Fix** (`bash -lc`), damit "Run mit Gate" plattformrobust wird.

## Dateien

| Datei | Inhalt |
|---|---|
| `README.md` | Pitch, Datenmodell-Entwurf, Export-Targets, Designfragen |
| `docs/PROJECT_OVERVIEW.md` | diese Datei — Scope, Warum, Stand |
| `docs/BUILD_LOG.md` | Bau-Chronik, Pipeline-Architektur, bekannte Probleme, nächste Schritte |
| `docs/concept.md` | Gesamtkonzept (vom `docs-concept`-Knoten erzeugt) |
| `schema/workflow.schema.json` | Datenmodell — Source of Truth |
| `meta-workflow.json` | eigene Roadmap als ausführbarer Workflow (Dogfooding) |
| `docs/CC_PROMPT_*.md` | je ein Bau-Auftrag pro Knoten (Build-Historie) |
| `docs/notes_2026-05-31_execution-und-kosten.md` | Execution-Stufen, Kosten-Routing, OpenClaw |
| `docs/sandcastle-master-slave-analysis.md` | sandcastle als Stufe-2-Backend, Master/Slave |
