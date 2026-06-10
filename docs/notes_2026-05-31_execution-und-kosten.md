# Notiz 2026-05-31 — Execution-Modell & Kosten

Festgehalten aus einer Cowork-Diskussion (post-Capstone-Gedanke). Fuettert direkt die
offenen Designfragen #2 (Execution-Modell) und das Kostenthema. Keine Entscheidung, nur
geklaerte Tradeoffs als Input fuer `concept.md`.

## Bezug zu Designfrage #2 — Canvas-only vs. Master-Agent

Die zwei Optionen aus dem README sind in Wahrheit eine Reifestufe, kein Entweder-oder:

1. **Stufe 1 — Canvas als Design-Tool, Mensch als Orchestrator.** Du zeichnest den DAG,
   fuellst pro Node die Slots (Ziel/Inputs/Constraints/Acceptance), und arbeitest die Nodes
   selbst ab (Prompt rauskopieren -> Claude Code -> Ergebnis pruefen -> naechster Node).
   Genau der manuelle Relay, den ich heute beim Deck-Umbau mache.
2. **Stufe 2 — Master-Agent liest den Graph und arbeitet ihn ab.** Erst sinnvoll, wenn jeder
   Node ein **maschinell pruefbares Acceptance-Kriterium** hat (Build gruen, Test gruen,
   Diff sauber, grep-Match). Ohne das eskaliert der Fehler-Loop und der autonome Lauf wird
   teurer als der manuelle.

**Konsequenz fuers Datenmodell:** das `acceptance`-Slot pro Node darf nicht Freitext bleiben.
Es braucht einen *ausfuehrbaren* Check (Shell-Kommando + erwarteter Exit/Pattern), sonst kann
Stufe 2 nie greifen. Das ist der eigentliche Hebel des ganzen Tools — nicht die UI.

## Kosten — Model-Routing (teurer Planer, billiger Worker)

- Kosten = Tokenmenge x Preis. Volumen sitzt beim **Worker** (Files lesen, Code generieren),
  nicht beim **Planer** (Graph lesen, naechsten Node waehlen). -> teures Modell als Planer,
  billiges als Worker ist das richtige Routing.
- **Sweet Spot Worker: Sonnet.** Fuer Coding zuverlaessig genug, deutlich billiger als Opus.
- **Lokale Mini-LLMs (z.B. qwen2.5:7b via Ollama) als Worker:** API-Kosten 0, aber nur fuer
  Trivial-Tasks (Textersetzung, JSON-Massage). Fuer mehrdateiige Refactors mit Build-Loop zu
  schwach -> Rework frisst die Ersparnis.
- **Catch:** ein zu schwacher Worker erzeugt mehr Korrektur-Loops vom Planer -> kann teurer
  werden als gleich das gute Modell. Ersparnis nur, wenn Worker "gut genug" fuer den Node ist.
  -> Pro-Node ein Modell-Hint im Datenmodell (`model: planner|sonnet|local`) waere sinnvoll.

## OpenClaw / MyClaw als moegliches Execution-Backend (Stufe 2)

- **OpenClaw** (Open Source, Clawdbot/Moltbot) = autonom-loopendes Agent-Framework: always-on
  Dauerprozess, self-trigger auf Events, dispatch + Logs lesen + iterieren. Genau das Backend,
  das den Master-Agent aus Designfrage #2 real laufen lassen koennte.
- **MyClaw.ai** = Managed Hosting dafuer (One-Click, ~19 $/Monat, dedizierte VM).
- **Empfehlung bei sensiblen Daten:** self-hosted OpenClaw auf eigener Box (z.B. Hetzner)
  statt Managed-Dienst — konsistent mit dem GDPR-Reflex aus SentinelAI (Groq production-excluded).
  Bei einem Managed-Agenten gibst du Keys/Repo-Zugang an einen Dritten.

## Realismus-Check agentic engineering (Mitte 2026)

Funktioniert fuer **eng umrissene, verifizierbare** Tasks (Refactor, Test gruen ziehen,
Migration). Noch NICHT fuer "grosses Projekt von Architektur bis fertig komplett autonom" —
da explodiert der Fehler-Loop. Der entscheidende Skill ist Tasks so zu schneiden, dass ein
Agent sie verifizierbar abschliessen kann. Dieses Tool ist im Kern genau ein Werkzeug fuer
dieses Task-Schneiden — der Wert liegt im Acceptance-Slot, nicht im Canvas.

## Naechster offener Punkt

`acceptance` als ausfuehrbaren Check ins Datenmodell aufnehmen (Designfrage #1 Granularitaet
haengt mit dran: kleiner Node = ein Check, grosser Node = mehrere). Erst danach Stufe 2 / OpenClaw.
