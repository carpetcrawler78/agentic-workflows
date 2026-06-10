# agentic-workflows

Visuelles Tool zum Bauen und Kommentieren von Dev-Workflows, die anschließend von Claude Code (oder kompatiblen Agenten) Schritt für Schritt ausgeführt werden.

## Idee in einem Satz

Workflow als DAG zeichnen → pro Node strukturierte Slots (Ziel, Inputs, Constraints, Acceptance, Kommentare) ausfüllen → Tool generiert daraus Slash-Commands / Sub-Agent-Definitionen für Claude Code.

## Status

Konzeptphase. Datenmodell, Export-Targets und UI-Mockup stehen, Implementierung folgt.

## Offene Designfragen

1. **Granularität pro Node** — ein Node = ein Slash-Command (klein, viele Nodes) vs. ein Node = ein ganzer Sub-Agent (groß, wenige Nodes).
2. **Execution-Modell** — Canvas als reines Design-Tool (User klickt Nodes manuell ab) vs. Master-Agent liest Graph und arbeitet ihn ab.
3. **Persistenz** — Workflow-JSON im Repo (git-versioniert, PR-fähig) vs. nur im Cowork-Artifact.

## Datenmodell (Entwurf)

Ein Workflow = eine JSON-Datei mit `nodes[]` und `edges[]`. Siehe `docs/concept.md` (folgt).

## Export-Targets

- `.claude/commands/<node-id>.md` — Slash-Commands, ein File pro Node
- `.claude/agents/<node-id>.md` — Sub-Agent-Definitionen
- `WORKFLOW.md` — Mermaid + alle Prompts inline als Single-File-Spec
