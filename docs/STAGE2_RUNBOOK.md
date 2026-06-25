# Stage-2 Runbook -- Erster Hetzner-Lauf

Stand: 2026-06-25  
Status: Schritte 1-6 sind Thomas' Live-Schritte (SSH). Engine-Code ist bereit.

---

## Voraussetzungen

| Voraussetzung | Pruefung |
|---|---|
| Hetzner-Box per SSH erreichbar | `ssh <user>@<ip>` |
| Docker Daemon laeuft | `docker info` |
| Python 3.11+ vorhanden | `python3 --version` |
| anthropic/claude-code npm-Paket verfuegbar | wird im Image installiert |
| `ANTHROPIC_API_KEY` im Environment gesetzt | `echo $ANTHROPIC_API_KEY` |

---

## Schritt 1: Disk-Hygiene

Auf Hetzner-Box ausfuehren:

```bash
# Nicht-mehr-benoetigte Docker-Artefakte entfernen (anhalten lassen, was laeuft)
docker system prune -a --volumes -f

# Ollama-Modelle/Volumes ggf. separat:
# docker volume ls | grep ollama | awk '{print $2}' | xargs -r docker volume rm

# Freien Speicher pruefen (Ziel: >= 10 GB fuer Image-Build + worktrees)
df -h /
```

---

## Schritt 2: Box neu starten (wenn "System restart required" angezeigt wird)

```bash
sudo reboot
# Warten, dann neu einloggen
ssh <user>@<ip>
```

---

## Schritt 3: Repo aktualisieren

```bash
cd ~/agentic-workflows   # oder git clone, wenn das Repo noch nicht da ist
git pull origin main
git log --oneline -3     # Commit-Stand pruefen
```

---

## Schritt 4: Container-Image bauen

Referenz-Version der Claude CLI: **2.1.191** (lokal installiert und getestet).

```bash
# Version pinnen fuer Reproduzierbarkeit
export CLAUDE_CLI_VERSION=2.1.191

docker build \
  --build-arg CLAUDE_CLI_VERSION=${CLAUDE_CLI_VERSION} \
  -t aw-sandbox:dev \
  .

# Pruefung: Claude CLI ist verfuegbar und meldet sich
docker run --rm aw-sandbox:dev claude --version
```

Erwartet: `claude 2.1.191` oder aehnlich.  
Bei anderer Version: Image-Tag als `aw-sandbox:<version>` taggen und IMAGE.md aktualisieren.

**API-Key wird NICHT ins Image eingebaut.** Er wird zur Laufzeit per `-e` uebergeben.

---

## Schritt 5: Smoke-Test ausfuehren

```bash
cd ~/agentic-workflows

ANTHROPIC_API_KEY=<dein-key> \
python -m src.cli run examples/smoke-stage2.json \
  --sandbox \
  --image aw-sandbox:dev \
  --memory 1.5g \
  --cwd .
```

**Was passiert (intern):**

1. Engine liest `examples/smoke-stage2.json`.
2. Fuer Knoten `smoke-hello` wird ein git-worktree unter `.aw-worktrees/smoke-hello/` angelegt.
3. Container startet: `docker run --rm --memory 1.5g --network bridge -v .aw-worktrees/smoke-hello/:/work aw-sandbox:dev`.
4. Claude CLI im Container bekommt den Goal-Prompt: "Erstelle eine Datei 'hello.txt' ...".
5. Nach Abschluss: Gate prueft `grep 'hello from stage-2' hello.txt` im worktree-Pfad.
6. Bei gruenem Gate: `git merge --no-ff agent/smoke-hello` in den main-Branch.
7. worktree wird entfernt.

---

## Schritt 6: Ergebnis-Pruefung

```bash
# Zusammenfassung aus dem CLI-Output (wird automatisch ausgegeben):
#   PASS  smoke-hello  [agent_invoked=True]
#
# Datei im Repo nach Merge:
cat hello.txt
# -> hello from stage-2

# git log:
git log --oneline -3
# -> <hash> Merge branch 'agent/smoke-hello'
```

Wenn dieser Test gruen ist: Stage-2-Backend ist betriebsbereit.

---

## Fehler-Diagnose

### Container startet nicht / OOM

```bash
docker run --rm --memory 1.5g aw-sandbox:dev claude --version
# Wenn OOM: --memory 2g versuchen
```

### Rotes Gate -- worktree nicht gemergt

Der worktree bleibt unter `.aw-worktrees/<node-id>/` erhalten. Inspektion:

```bash
ls .aw-worktrees/smoke-hello/
cat .aw-worktrees/smoke-hello/hello.txt   # vorhanden? Richtiger Inhalt?
```

Manuell bereinigen:
```bash
git worktree remove .aw-worktrees/smoke-hello --force
```

### API-Key nicht gesetzt

Fehlermeldung des Containers: `ANTHROPIC_API_KEY not set` oder `Authentication error`.  
Loesung: Key als `-e`-Flag uebergeben (wird vom `run_in_sandbox` intern gesetzt, wenn ANTHROPIC_API_KEY im Environment steht).

### Merge-Konflikt

```bash
git status   # CONFLICT-Meldung
git merge --abort
# worktree inspizieren, dann manuell loesen
```

---

## Naechste Schritte nach erfolgreichem Smoke-Test

1. `docs/IMAGE.md` aktualisieren: installierte CLI-Version eintragen.
2. Ersten echten Workflow-Knoten testen (z.B. `meta-workflow.json` Knoten 1).
3. `--max-parallel 2` mit einem 2-Knoten-Workflow ausprobieren.
