# Backend-Entscheidung — Execution-Backend für Stufe 2

Stand: 2026-06-25
Bezug: `PROJECT_OVERVIEW.md` (Designfrage #4), `sandcastle-master-slave-analysis.md`,
`notes_2026-05-31_execution-und-kosten.md`

Stufe 2 = ein Master-Agent liest den Workflow-DAG und arbeitet ihn autonom ab: pro Knoten
ein Worker-Agent in isolierter Sandbox + automatisches Acceptance-Gate, der nächste Knoten
startet nur bei grünem Gate. Diese Datei hält die Backend-Entscheidung und ihre Begründung
fest. Die Engine (`orchestrator.py --execute`) ist faktisch schon der Master-Kern; offen ist
nur die Ausführungs-/Isolations-Ebene darunter.

## Optionen

| Option | Was es liefert | Sprache | Fit für unseren Use-Case |
|---|---|---|---|
| **sandcastle** | Worktree + Container + Branch-Merge fertig, 6 Agent-Provider, strukturierter Output, Session-Resume, AbortSignal. Auf Multi-Branch-Merge ausgelegt. | TypeScript (intern Effect) | Hoch — aber TS-Fremdkörper im Python-Stack |
| **OpenHands** | Zweckgebauter autonomer Coding-Agent, jede Session in isoliertem Docker-Sandbox (Terminal/Editor/Browser). ~70k Stars. | Python | Hoch — liefert die Slave-Ebene fertig |
| **LangGraph + eigene Primitive** | LangGraph als Master-Scheduler (Python, production-grade Graph-Orchestrierung) + selbstgebaute Worktree/Docker/Merge-Primitive. | Python | Hoch — alles Python, voller Kontrolle |
| **OpenClaw** | Always-on persönlicher Assistent (Gateway zu WhatsApp/Telegram/Slack). ~380k Stars (meist-gesterntes GH-Projekt 2026). | — | **Niedrig** — Architektur-Mismatch, kein Coding-Sandbox-/Merge-Backend |

## Entscheidungen

### 1. sandcastle NICHT nach Python portieren — Primitive nachbauen

Ein originalgetreuer Port wäre groß und fehleranfällig: sandcastle ist intern komplett auf
**Effect** gebaut, das Paradigma bildet sich nicht sauber auf Python-Idiom ab. Wir brauchen
aber nur drei Primitive, und die sind in Python eher einfacher:

- `createWorktree()` -> `git worktree add` (subprocess-Wrapper)
- Container-Sandbox -> `docker run` pro Knoten, mit `--memory`-Limit
- Merge-back + strukturierter Output -> `git merge` + XML-Tag parsen + gegen `jsonschema`
  validieren (jsonschema nutzen wir im Loader bereits)

Die fehleranfälligen Stellen (Container-Isolation, Merge-Konflikte, plattformübergreifende
Shell — siehe der `bash`-vs-`cmd.exe`-Fix im Executor) sind sprachunabhängig. Nachbauen statt
portieren ist mittlere Komplexität, niedriges Risiko und kohärent mit dem Python-Stack.

Fallback, falls Eigenbau zu viel wird: **OpenHands** als fertige Slave-Ebene einbinden.

### 2. OpenClaw ist raus (als Execution-Backend)

Populär, aber architektonisch das falsche Werkzeug: persönlicher always-on Assistent, kein
Sandbox-+-Merge-Backend für Code-Tasks. Als Talking-Point erwähnenswert ("evaluiert, aber
für diesen Job das passendere Tool gewählt"), nicht als Baustein. Der legitime Nutzungs-Pfad
für OpenClaw steht in Abschnitt 4.

### 3. Worker = API-Modell (Sonnet), nicht lokal

Die Hetzner-Box hat **keine GPU**. Lokale Inferenz (qwen2.5:7b via Ollama) liefe auf CPU und
ist für einen echten Coding-Loop (mehrere Dateien, Build-Schleife) zu langsam — der
Zeitverlust frisst die API-Ersparnis. Konsequenz fürs Kosten-Routing:

- Worker = **Sonnet (API)** als Default.
- Planner = teures API-Modell.
- `model: local`-Hint bleibt im Datenmodell, wird aber Nische (Trivial-Tasks: Textersetzung,
  JSON-Massage, wo CPU reicht).

Wichtig: Bei diesem Design läuft die LLM-Inferenz NICHT auf der Box. Der Sandbox-Container
führt nur die Agent-CLI aus (dünner API-Client). Die Box ist Orchestrator + Werkstatt
(Git + Docker + CLI), nicht Rechenzentrum — GPU daher irrelevant.

### 4. OpenClaw — wenn überhaupt, dann als Trigger/Notification-Layer (Stufe 3)

Der "punkten"-Reflex (OpenClaw ist das meist-gesternte GitHub-Projekt 2026, Schöpfer bei
OpenAI) ist nicht falsch — nur an der falschen Stelle. OpenClaw kann das, wofür es gebaut ist:
always-on Event-Gateway + Chat-Surface. Der ehrliche Integrations-Pfad nutzt es als
**Vorderfront, nicht als Motor**:

- OpenClaw als **Trigger-Layer**: lauscht auf Events ("starte Workflow X" via Telegram/Slack,
  oder ein Commit-Hook) und ruft unsere Engine auf.
- OpenClaw als **Reporting-Layer**: meldet das Gate-Ergebnis pro Knoten zurück in den Chat.
- Die **Python-Engine bleibt der Kern** (Master + Slaves + Gating). OpenClaw fasst keinen Code
  an, führt nichts aus, mergt nichts.

So ist die Architektur sauber UND der Buzzword-/Signal-Wert ("integriert mit OpenClaw")
legitim nutzbar, ohne dass ein technisches Gegenüber Löcher reinschießt. Einordnung: reines
**Stufe-3-Komfort-Feature**, kein Pflicht-Baustein. Frühestens NACH dem ersten sequenziellen
Stufe-2-Lauf dranschrauben — vorher lenkt es nur ab.

## Hetzner-Kapazität (capstone2, gemessen 2026-06-25)

| Ressource | Wert | Bewertung |
|---|---|---|
| Cores | 4 | Deckt 2-3 parallele Builds, Rest für OS + Orchestrator |
| RAM | 7,6 GiB total, 6,9 GiB frei | ~1,5 GB/Slave -> 2-3 parallel realistisch |
| Disk `/` | 75 GB, 19 GB frei (75 % belegt) | Zweiter Engpass; Image-Hygiene nötig |
| GPU | keine | Irrelevant (Inferenz API-seitig) |

Die alte Capstone-Last (postgres/redis/grafana/mlflow/ollama, 8 Container) ist abgebaut —
`used` lag bei der Messung bei 653 Mi. Von den 54 GB belegtem Disk sind große Teile
Capstone-Reste (Ollama-Modelle 4-5 GB/Stück, Postgres-Volume, alte Images); aufräumen
(`docker system prune -a` + alte Modelle/Volumes) holt zweistellige GB zurück.

Hinweis: Box meldet "System restart required" — vor ernsthaftem Betrieb rebooten.

## Ausführungs-Roadmap

1. **Sequenziell zuerst** — ein Slave nach dem anderen durchs Gate. Einfach, debugbar.
2. **Parallelität später als Optimierung** — max. 2-3 Slaves, je `docker run --memory=1.5g`,
   Idle-Timeout pro Container. Kein Fan-out über 3 (Box zu klein).
3. **Disk-Hygiene** als Dauerlauf — `docker system prune` regelmäßig, Worktrees nach Merge
   aufräumen.

## Offen

- Eigenbau-Primitive vs. OpenHands final entscheiden, sobald der erste sequenzielle
  Stufe-2-Lauf steht.
- Capstone-Reste auf Hetzner abräumen (Disk freimachen) vor erstem Betrieb.
