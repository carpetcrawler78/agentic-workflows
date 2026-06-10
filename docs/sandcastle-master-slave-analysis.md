# Sandcastle als Execution-Backend — Master/Slave-Analyse

Stand: 2026-06-10
Quelle: [mattpocock/sandcastle](https://github.com/mattpocock/sandcastle) @ `main` (v0.1.4)
Bezug: Designfrage #2 (Execution-Modell), Notiz `notes_2026-05-31_execution-und-kosten.md`

## Worum es geht

`sandcastle` ist eine TypeScript-Library, die KI-Coding-Agents in isolierten Containern
orchestriert: Worktree bauen → Agent im Sandbox laufen lassen → Commits zurückmergen, alles
hinter einem `run()`. Sie ist Kandidat für das **Execution-Backend von Stufe 2** (Master-Agent
arbeitet den Graph ab) aus unserer Execution-Notiz — eine Alternative bzw. ein Baustein neben
OpenClaw.

Diese Analyse beantwortet eine konkrete Frage: **Wie viel von einem autonomen Master/Slave-
Framework liefert sandcastle bereits, und was müssten wir selbst bauen?**

Wichtige Einschränkung: Das README untertreibt das Projekt deutlich. Der tatsächliche Code
(`src/index.ts`) exportiert weit mehr als die Doku zeigt.

## Was sandcastle wirklich kann (über das README hinaus)

- **Sechs Agent-Provider**, nicht nur Claude: `claudeCode, codex, copilot, cursor, opencode, pi`.
  Slaves müssen nicht alle dasselbe Modell sein.
- **Fünf Sandbox-Backends:** Docker, Podman, Daytona, Vercel Sandbox, plus `no-sandbox` (Host).
- **Strukturierter Output** mit Schema-Validierung (`Output.object({ tag, schema })`): der
  Agent-stdout wird nach einem XML-Tag gescannt und als typisiertes JSON zurückgegeben.
- **Session-Resume** (`result.resume(prompt)`) — Agent-Kontext über eine weitere Iteration
  fortsetzen.
- **AbortSignal**-Support: Mid-Iteration-Kill, Worktree bleibt erhalten.
- **Low-Level-APIs** `createWorktree()` / `createSandbox()` unter dem High-Level-`run()`.

Architektur-Fundament: komplett auf `effect` (Layer/Effect.gen). Wer sandcastle nur
*konsumiert* (run/createWorktree), sieht davon nichts — die öffentliche API ist Promise-basiert.
Wer *forkt/erweitert*, muss Effect lernen. Für uns gilt: konsumieren, nicht forken.

## Die Primitive, die wir bekommen

### Slave-Baustein = `createWorktree()`

Der Schlüssel ist nicht `run()`, sondern `createWorktree()`. Aufruf:

```ts
createWorktree({ branchStrategy: { type: "branch", branch: "agent/task-7" } })
```

liefert ein `Worktree`-Handle: ein eigenständiger Git-Worktree auf eigenem Branch, mit
`.run()`, `.interactive()`, `.createSandbox()` und `[Symbol.asyncDispose]`. Ein Slave =
ein Worktree + ein Container + ein Branch. Vollständig isoliert; `await using` räumt
automatisch auf (dirty → Worktree wird preserved).

### Parallelität ist zustandslos und damit trivial

Der Orchestrator selbst ist sequenziell (`for i in 1..maxIterations`, frische Sandbox pro
Iteration). Parallelität entsteht **eine Ebene höher**: der Master macht `Promise.all` über
N `createWorktree()` + `.run()`. Es gibt keinen geteilten Zustand zwischen Slaves außer Git.
Jeder Slave committet auf seinen eigenen Branch.

### Merge-back ist explizit auf Master/Slave ausgelegt

In `SandboxLifecycle.ts` wird bewusst `git merge` statt `cherry-pick` verwendet. Der
Code-Kommentar sagt wörtlich: *"cherry-pick breaks when the temp branch contains merge commits
(e.g. a merge agent merging multiple parallel branches)"*. Das Framework ist also bereits
dafür gebaut, dass ein finaler **Merge-Agent** mehrere Slave-Branches zusammenführt. Genau das
ist die `parallel-planner`-Template: planen → parallel auf Branches ausführen → mergen.

## Die drei Isolationsstufen (entscheidend für "autonom")

`SandboxProvider.ts` definiert drei `tag`-Varianten mit unterschiedlichen Branch-Strategien:

| Tag | Provider | Branch-Strategien | FS-Zugriff | Einsatz |
|---|---|---|---|---|
| `bind-mount` | Docker, Podman | `head` / `merge-to-head` / `branch` | Host-FS via Mount, kein Sync | schnell, Host exponiert |
| `isolated` | Vercel, Daytona | `merge-to-head` / `branch` | kein Host-FS; Sync via `syncOut` (format-patch/am) | echte Isolation |
| `none` | Host | alle drei | direkt auf Host | "at your own risk" |

Für ein autonomes Master/Slave-System: **`isolated` für die Slaves.** Echte Container/VM-
Boundary, parallele Slaves können sich nicht gegenseitig korrumpieren, der Agent kann das
Host-System nicht beschädigen. Preis: syncOut-Overhead.

`head` (Agent schreibt direkt aufs Host-FS) ist bei `isolated` per Typsystem ausgeschlossen.

## Autonomie-Hebel, die schon existieren

1. **Selbst-Terminierung:** `completionSignal` (Substring-Match, Default
   `<promise>COMPLETE</promise>`) + `maxIterations`. Slave läuft bis Selbst-Abschluss oder Limit.
2. **Liveness:** Idle-Timeout (kein Output für N Sek → kill) getrennt vom Wall-Clock-Timeout.
   Robuster als reines Wall-Clock — ein lang denkender, aber aktiver Agent wird nicht gekillt.
3. **AbortSignal:** Master kann jeden Slave mid-flight killen (`signal.reason` propagiert
   verbatim). Basis für "kill the stragglers" nach `Promise.race`.
4. **Strukturierter Output — der wichtigste Koordinations-Hebel.** `Output.object({ tag, schema })`
   gibt typisiertes, validiertes JSON zurück. Ein **Planner-Slave** emittiert eine strukturierte
   Task-Liste, die der Master parst und in N Executor-Slaves auffächert. Damit ist ein Slave
   keine Black Box. Das ist das Rückgrat jeder Master/Slave-Koordination.
5. **resumeSession:** Slave-Kontext fortsetzen. Master gibt Feedback ("Review fand X, fix es")
   ohne Kontextverlust.
6. **Provider-Abstraktion:** jeder Agent implementiert `buildPrintCommand`, `parseStreamLine`
   (→ `text`/`result`/`tool_call`/`session_id`), optional `sessionStorage`/`captureSessions`/
   `parseSessionUsage`. Der Orchestrator kennt kein Claude-spezifisches Format → Agents
   austauschbar.

## Ziel-Architektur auf sandcastle

```
Master (unser Code, KEIN sandcastle-Agent)
|
+-- Phase 1: PLAN
|     run({ agent: claudeCode, sandbox: isolated, output: Output.object({
|       tag: "plan", schema: { tasks: [{ id, branch, prompt, dependsOn, model }] }
|     })})  -> typisierte Task-DAG
|
+-- Phase 2: FAN-OUT (parallel, topologisch sortiert nach dependsOn)
|     Promise.all(tasks.map(t =>
|       createWorktree({ branchStrategy: { type:"branch", branch:t.branch }})
|         .run({ agent, sandbox: isolated, prompt: t.prompt,
|                completionSignal, signal: abortController.signal })
|     ))  -> N Slaves, je eigener Branch + Container
|
+-- Phase 3: MERGE
      run({ prompt: "merge branches X,Y,Z; resolve conflicts",
            branchStrategy: merge-to-head })  -> Merge-Agent
```

Das `model`-Feld pro Task setzt direkt die Model-Routing-Idee aus der Execution-Notiz um
(teurer Planer, billiger Sonnet/lokaler Worker).

## Wiederverwenden vs. selbst bauen

**Wiederverwenden (1:1 aus sandcastle):** Worktree-Lifecycle, Container-Provisioning,
Branch-Merge-Mechanik (inkl. Merge-Commit-Handling), Idle/Abort/Timeout, strukturierter Output,
Session-Capture/Resume, Provider-Abstraktion.

**Selbst bauen (existiert in sandcastle NICHT):**

- **Der Master-Scheduler.** sandcastle hat *keinen* DAG-/Dependency-Scheduler. Die
  `parallel-planner`-Template ist vermutlich nur flaches `Promise.all` + Merge — kein
  topologisches Scheduling, keine Retry-Policy, kein Backpressure. **Das ist exakt die Lücke,
  die `agentic-workflows` füllt.**
- **Acceptance-Gating.** sandcastle prüft Erfolg nur über `completionSignal` (Substring) und
  Exit-Code. Unser ausführbarer `acceptance`-Check pro Node (Shell-Kommando + erwarteter
  Exit/Pattern, siehe Execution-Notiz) ist der eigentliche Hebel und fehlt hier komplett.
- **Inter-Slave-Kommunikation.** Slaves reden nur über Git-Branches. "Slave B braucht ein
  Artefakt von Slave A" müssen wir über Branch-Topologie / geteilte Output-JSONs modellieren.
- **Konflikt-Resolution-Policy.** Merge failt hart bei Konflikten (Worktree preserved, manueller
  Retry-Hinweis). Autonomie braucht hier einen Merge-Agent mit Auflösungs-Prompt.
- **Visuelle Spec → sandcastle-Calls.** Unser Kern: aus `schema/workflow.schema.json` die
  `createWorktree`/`run`-Aufrufe generieren.

## Tradeoffs

- **Effect-Lock-in** nur beim Forken relevant; beim Konsumieren unsichtbar.
- **Pro-Iteration-Container-Overhead.** Jede Iteration = frischer Container. Für "ein Slave =
  ein langer Task" ideal; für eng-iterative Loops teuer. Gegenmittel: `createSandbox()`
  (langlebiger Sandbox-Handle) statt `run()`, wenn ein Slave viele kurze Schritte braucht.
- **Completion per Substring ist fragil** (Agent erwähnt das Signal im Fließtext → Abbruch).
  Bei langen autonomen Outputs reales Risiko. Gegenmittel: unwahrscheinliches Custom-Signal
  oder `Output.object` (separater Extraction-Pass).
- **Reifegrad:** v0.1.4, ein Maintainer, 14 Stars. Als harte Produktions-Dependency riskant;
  als Referenz-Implementierung oder vendored Baustein exzellent (überdurchschnittlich solide:
  breite Test-Coverage inkl. Windows-Pfad-Tests, dokumentierte ADRs).

## Bottom line

sandcastle löst die **Slave-Ausführungsebene** (Worktree + Container + Branch + Merge) bereits
sauber und ist explizit auf Multi-Branch-Merge ausgelegt. Was fehlt — und was `agentic-workflows`
ist — ist die **Master-Orchestrierungsebene darüber**: DAG-Scheduling, Dependency-Auflösung,
Acceptance-Gating, Retry/Konflikt-Policy, und die Übersetzung der visuellen Spec in diese Calls.

Wir bauen nicht das Sandbox-Framework neu. Wir bauen den Dirigenten. sandcastle (oder OpenClaw)
ist das Orchester.

## Offene Punkte / noch nicht verifiziert

- `createSandbox.ts` (langlebiger Sandbox-Handle) und die exakte `parallel-planner`-Template
  (`InitService.ts`) wurden noch nicht im Detail gelesen — Mechanik aber aus `createWorktree.ts`
  + `SandboxLifecycle.ts` rekonstruiert.
- `AgentProvider.ts` (Claude-Invocation-Detail) aus der Nutzung im Orchestrator abgeleitet,
  nicht direkt gelesen.
- Entscheidung sandcastle vs. OpenClaw als Stufe-2-Backend steht aus (separate Designfrage).

## Quellen

- [src/createWorktree.ts](https://github.com/mattpocock/sandcastle/blob/main/src/createWorktree.ts)
- [src/SandboxLifecycle.ts](https://github.com/mattpocock/sandcastle/blob/main/src/SandboxLifecycle.ts)
- [src/SandboxProvider.ts](https://github.com/mattpocock/sandcastle/blob/main/src/SandboxProvider.ts)
- [src/Orchestrator.ts](https://github.com/mattpocock/sandcastle/blob/main/src/Orchestrator.ts)
- [src/run.ts](https://github.com/mattpocock/sandcastle/blob/main/src/run.ts)
- [src/index.ts](https://github.com/mattpocock/sandcastle/blob/main/src/index.ts)
