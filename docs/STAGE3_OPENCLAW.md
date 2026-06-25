# Stage 3 -- OpenClaw (Spec-only, deferred)

Stand: 2026-06-25  
Status: **Nicht implementiert.** Dieses Dokument ist eine Architektur-Skizze als Grundlage fuer eine spaetere Implementierung.

---

## Motivation

Stage 2 koordiniert Worker-Agenten (Claude CLI in Docker) vom selben Host aus: ein Orchestrator, ein git-Repo, N Worktrees, sequenzieller oder paralleler Betrieb.

Stage 3 ("OpenClaw") soll das auf mehrere unabhaengige Hosts skalieren. Kern-Idee: Worker sind vollstaendig autonom -- sie holen sich Arbeit aus einem shared git-Repository, bearbeiten sie in einem eigenen Branch, und melden Ergebnisse zurueck, ohne dass ein zentraler Prozess aktiv koordiniert.

---

## Kern-Architektur

```
                    +----------------------+
                    |  Shared git remote   |
                    |  (z.B. Hetzner NFS,  |
                    |   bare Repo auf S3)  |
                    +----------+-----------+
                               |
          +--------------------+--------------------+
          |                    |                    |
    +-----+------+      +------+-----+      +------+-----+
    | Worker A   |      | Worker B   |      | Worker C   |
    | Host 1     |      | Host 2     |      | Host 3     |
    | (Docker)   |      | (Docker)   |      | (Docker)   |
    +------------+      +------------+      +------------+
```

- Kein dauerhaft laufender Orchestrator-Prozess.
- Worker reagieren auf das Repo-Zustand (Pull-Model statt Push-Model).
- Koordination ausschliesslich ueber git-Objekte (Branches, Tags, Commit-Messages).

---

## Key Design Decisions

### 1. Arbeits-Queue via git-Branch-Naming

Knotenarbeit wird in Branches codiert:
- `tasks/pending/<node-id>` -- Aufgabe offen, kein Worker hat zugegriffen.
- `tasks/claimed/<worker-id>/<node-id>` -- Worker hat die Aufgabe genommen (optimistisches Locking).
- `tasks/done/<node-id>` -- Fertig, Gate gruen, Ergebnis gemergt.
- `tasks/failed/<node-id>` -- Gate rot, worktree erhalten.

Claim-Mechanismus: Worker versucht `git push origin tasks/claimed/<wid>/<nid>` -- faellt fehl, wenn ein anderer Worker schneller war (non-fast-forward). Retry mit naechster offenen Task.

### 2. Dependency-Resolution ohne zentralen Planer

Jeder Worker kann die Wave-Struktur selbst berechnen (topological_waves ist deterministisch auf demselben Workflow-JSON). Worker prueft vor Claim: Sind alle `dependsOn`-Branches in `tasks/done/` vorhanden?

### 3. Heartbeat statt Lease-Timeout

Worker schreibt regelmaessig ein `claimed/<wid>/<nid>/heartbeat`-Tag mit Timestamp. Andere Worker loeschen verwaiste Claims nach TTL (z.B. 15 Minuten ohne Heartbeat).

### 4. Merge-Konflikt-Strategie

Da Worker-Branches unabhaengig entwickelt werden, sind strukturelle Konflikte wahrscheinlicher als in Stage 2. Optionen (noch offen):
- (a) Serielle Merge-Queue: ein leichtgewichtiger Merge-Coordinator (kein full Orchestrator) verarbeitet `tasks/done/` sequenziell.
- (b) Rebase-basierter Workflow: Worker rebased auf aktuellen main vor dem Push -- Konflikt wird sichtbar, nicht blind gemergt.
- **Empfehlung**: Option (a) fuer den ersten Build (einfacher Fehler-Handling), (b) als Haertung.

### 5. Security

- Jeder Worker hat nur den API-Key fuer seinen eigenen Claude-CLI-Aufruf.
- git remote Credentials: Deploy-Key per Worker (read+push auf `tasks/`, read-only auf main).
- Kein Worker schreibt direkt auf `main` -- nur der Merge-Coordinator.

---

## Offen / Noch zu entscheiden

| Frage | Optionen |
|---|---|
| Shared git remote | NFS-bare-Repo, Gitea auf Hetzner, GitHub |
| Worker-Scheduling | cron + git pull, oder Webhook-getriggert |
| Merge-Coordinator | minimaler Python-Prozess, oder GitHub Actions |
| Observability | git log als einzige Quelle vs. separates Event-Log |
| Rollback-Strategie | `git revert` des Merge-Commits |

---

## Abgrenzung zu Stage 2

| Aspekt | Stage 2 | Stage 3 (OpenClaw) |
|---|---|---|
| Koordination | Orchestrator-Prozess | git-Repo (dezentral) |
| Worker-Standorte | Gleicher Host, N Container | Verschiedene Hosts |
| Dependency-Check | Im Orchestrator | Jeder Worker selbst |
| Merge | Orchestrator nach Gate | Merge-Coordinator oder Worker |
| Claim-Mechanismus | Kein (sequenziell) | git push race (optimistisch) |

---

## Bezug zum aktuellen Repo

Der Code fuer Stage 3 existiert noch nicht. Stub: `src/openclaw_stub.py`.

Voraussetzung fuer die Implementierung: Stage-2-Betrieb auf Hetzner laeuft stabil
(Smoke-Test + mindestens ein echter Workflow-Lauf).
