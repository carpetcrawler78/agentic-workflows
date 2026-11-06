# %% [markdown]
# # agentic-workflows – Lern-Notebook (verschlankt)
#
# **Format:** Diese Datei ist ein *Percent-Notebook*. Jede Zeile `# %%` startet eine Zelle.
# VS Code (mit Python-/Jupyter-Erweiterung) zeigt sie als Notebook an, Zelle für Zelle ausführbar.
#
# **Ziel:** Den Kern deines Projekts in einem Durchlauf verstehen – ohne Tests, ohne Docker,
# ohne echten Claude-Aufruf. Statt Claude benutzen wir einen *Fake-Agenten*.
#
# **Der Ablauf in einem Satz:**
# Workflow (Graph) → Reihenfolge bestimmen → pro Knoten: eigener Git-Arbeitsordner → Agent arbeitet
# → Abnahmetest (Gate) → bei Grün: committen und in main zurückmergen.
#
# Voraussetzung: `git` ist installiert und im PATH.

# %% [markdown]
# ## 1. Importe
#
# - **subprocess**: startet externe Programme (hier `git` und die Prüfbefehle) aus Python heraus.
# - **dataclass**: Kurzschreibweise für Klassen, die nur Daten halten (wie ein typisierter Datensatz).
# - **Callable**: Typ-Hinweis für „etwas Aufrufbares“, also eine Funktion. Brauchen wir für Dependency Injection.
# - **tempfile**: legt temporäre Ordner an, damit die Demo nichts auf deinem Rechner verschmutzt.

# %%
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# %% [markdown]
# ## 2. Der Workflow als Datenstruktur
#
# Ein Workflow ist ein **DAG** (*Directed Acyclic Graph*): Kästchen (**Knoten**, engl. *nodes*)
# und Pfeile (**Kanten**, engl. *edges*), die nie im Kreis laufen.
# Eine Kante `{"from": "a", "to": "b"}` heißt: *a muss fertig sein, bevor b startet.*
#
# Im Original liegt das als JSON-Datei vor und wird gegen ein **JSON-Schema** geprüft
# (ein Regelwerk, welche Felder Pflicht sind). Hier reicht eine Mini-Prüfung.
#
# Jeder Knoten hat:
# - `goal` – die Aufgabe, daraus wird der Prompt für den Agenten,
# - `acceptance` – die **Abnahmetests**: Shell-Befehle plus erwartetes Ergebnis.
#   Erst wenn *alle* bestehen, gilt der Knoten als erledigt. Das ist der Kern des Projekts.

# %%
PY = f'"{sys.executable}"'  # Pfad zum aktuellen Python, in Anführungszeichen (wegen Leerzeichen)

def datei_existiert_check(name):
    """Baut einen Abnahmetest: Exit-Code 0, wenn die Datei existiert, sonst 1."""
    return {
        "command": f'{PY} -c "import os,sys; sys.exit(0 if os.path.exists(\'{name}\') else 1)"',
        "expect": {"exitCode": 0},
    }

workflow = {
    "name": "Demo-Workflow",
    "nodes": [
        {"id": "schritt-a", "goal": "Lege hello.txt an.",
         "acceptance": [datei_existiert_check("hello.txt")]},
        {"id": "schritt-b", "goal": "Lege world.txt an.",
         # Prüft BEIDE Dateien: beweist, dass b das Ergebnis von a 'erbt'.
         "acceptance": [datei_existiert_check("hello.txt"), datei_existiert_check("world.txt")]},
    ],
    "edges": [{"from": "schritt-a", "to": "schritt-b"}],
}

def validate_workflow(wf):
    """Mini-Validierung: sammelt ALLE Fehler, statt beim ersten abzubrechen (wie das Original)."""
    fehler = []
    ids = {n["id"] for n in wf["nodes"]}
    for n in wf["nodes"]:
        if not n.get("acceptance"):
            fehler.append(f"{n['id']}: keine acceptance-Checks")
    for e in wf["edges"]:
        if e["from"] not in ids or e["to"] not in ids:
            fehler.append(f"Kante verweist auf unbekannten Knoten: {e}")
    if fehler:
        raise ValueError("\n".join(fehler))

validate_workflow(workflow)
print("Workflow ist gültig.")

# %% [markdown]
# ## 3. Reihenfolge bestimmen – topologische Sortierung
#
# **Topologische Sortierung** = eine Reihenfolge, in der jeder Knoten erst nach all seinen
# Vorgängern kommt. Klassischer Algorithmus: **Kahn**.
#
# 1. Zähle für jeden Knoten, wie viele Pfeile auf ihn zeigen (**In-Grad**).
# 2. Alle Knoten mit In-Grad 0 sind sofort startbereit.
# 3. Nimm einen davon, „entferne“ seine ausgehenden Pfeile, und wer dadurch auf 0 fällt, wird startbereit.
# 4. Bleiben am Ende Knoten übrig, gibt es einen Kreis → kein gültiger DAG.

# %%
def topological_order(wf):
    in_grad = {n["id"]: 0 for n in wf["nodes"]}
    nachfolger = {n["id"]: [] for n in wf["nodes"]}
    for e in wf["edges"]:
        in_grad[e["to"]] += 1
        nachfolger[e["from"]].append(e["to"])

    bereit = [nid for nid, g in in_grad.items() if g == 0]
    reihenfolge = []
    while bereit:
        nid = bereit.pop(0)
        reihenfolge.append(nid)
        for nf in nachfolger[nid]:
            in_grad[nf] -= 1
            if in_grad[nf] == 0:
                bereit.append(nf)

    if len(reihenfolge) != len(in_grad):
        raise ValueError("Zyklus im Graphen – kein DAG")
    return reihenfolge

print(topological_order(workflow))

# %% [markdown]
# ## 4. Das Gate: Abnahmetests ausführen (executor)
#
# Ein Check ist ein Shell-Befehl. Wir prüfen den **Exit-Code**: Jedes Programm meldet beim Beenden
# eine Zahl, 0 heißt „Erfolg“, alles andere „Fehler“. Das Original kann zusätzlich per
# **Regex** (Suchmuster) die Ausgabe prüfen.
#
# Wichtig: Es laufen **immer alle** Checks (kein vorzeitiger Abbruch), damit der Bericht vollständig ist.
# Ein **Timeout** verhindert, dass ein hängender Befehl alles blockiert.

# %%
@dataclass
class CheckResult:
    command: str
    passed: bool
    exit_code: Optional[int]
    reasons: list = field(default_factory=list)

@dataclass
class NodeResult:
    node_id: str
    passed: bool
    checks: list

def run_check(check, cwd):
    try:
        r = subprocess.run(check["command"], shell=True, cwd=cwd,
                           capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return CheckResult(check["command"], False, None, ["Timeout"])
    erwartet = check["expect"]["exitCode"]
    gruende = [] if r.returncode == erwartet else [f"exitCode erwartet {erwartet}, war {r.returncode}"]
    return CheckResult(check["command"], not gruende, r.returncode, gruende)

def run_node(node, cwd):
    checks = [run_check(c, cwd) for c in node["acceptance"]]
    return NodeResult(node["id"], all(c.passed for c in checks), checks)

# %% [markdown]
# ## 5. Isolation mit Git (sandbox)
#
# - **Branch**: ein paralleler Entwicklungszweig im selben Repository.
# - **Worktree**: ein *zusätzlicher Arbeitsordner* für dasselbe Repo, ausgecheckt auf einem eigenen Branch.
#   So kann jeder Knoten ungestört arbeiten, main bleibt unberührt.
# - **Commit**: ein gespeicherter Stand. **Merge**: einen Branch in einen anderen einfließen lassen.
# - `--no-ff` (*no fast-forward*): erzwingt einen sichtbaren Merge-Commit – im Log sieht man pro Knoten einen Block.
#
# Im Original läuft der Agent zusätzlich in einem **Docker-Container** (isolierte Mini-Umgebung,
# Worktree als `/work` eingehängt, mit Speicherlimit). Das lassen wir hier weg.
#
# **Verbesserung gegenüber dem Original:** Wir werten das Merge-Ergebnis aus.
# Bei einem Konflikt gilt der Knoten als fehlgeschlagen (im Original wird das Ergebnis ignoriert).

# %%
GIT_ID = ["-c", "user.name=aw-agent", "-c", "user.email=aw-agent@local"]  # Commit ohne globale Git-Config

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

@dataclass
class Worktree:
    path: str
    branch: str

def create_worktree(repo, wt_root, node_id):
    branch = f"agent/{node_id}"
    path = str(Path(wt_root) / node_id)
    r = git("worktree", "add", "-b", branch, path, "HEAD", cwd=repo)  # abgezweigt vom AKTUELLEN main
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return Worktree(path, branch)

def commit_worktree(wt, message):
    git("add", "-A", cwd=wt.path)
    git(*GIT_ID, "commit", "-m", message, cwd=wt.path)

def merge_back(repo, branch):
    r = git(*GIT_ID, "merge", "--no-ff", branch, "-m", f"merge {branch}", cwd=repo)
    if r.returncode != 0:
        git("merge", "--abort", cwd=repo)  # Repo nie halb-gemergt zurücklassen
        return False
    return True

def remove_worktree(repo, wt):
    git("worktree", "remove", "--force", wt.path, cwd=repo)

# %% [markdown]
# ## 6. Der Agent – per Dependency Injection
#
# **Dependency Injection (DI)**: Eine Funktion bekommt ihre Abhängigkeit *von außen übergeben*,
# statt sie selbst fest einzubauen. Hier: Der Orchestrator weiß nicht, *wer* die Arbeit macht –
# er bekommt einfach eine Funktion `agent(node, prompt)`.
#
# Vorteil: Im Test (und in diesem Notebook) übergeben wir einen **Fake-Agenten**, der nur eine Datei
# schreibt. In Produktion übergeben wir den echten Claude-Agenten. Der Kern bleibt identisch.
#
# Analogie: Eine Kaffeemaschine mit Kapselschacht – welche Kapsel drin steckt, entscheidet der Nutzer.

# %%
Agent = Callable[[dict, str], Optional[float]]  # (Knoten, Prompt) -> Kosten in USD oder None

def fake_agent(node, prompt):
    """Tut so, als wäre er Claude: erzeugt die im Ziel genannte Datei im Worktree."""
    dateiname = node["goal"].split()[1]  # "Lege hello.txt an." -> "hello.txt"
    Path(node["_worktree"].path, dateiname).write_text(prompt, encoding="utf-8")
    return 0.0

def make_claude_agent():
    """So sieht der echte Agent aus: Claude Code headless, Prompt über stdin.
    (Hier nur gezeigt, nicht benutzt.)"""
    def agent(node, prompt):
        subprocess.run(["claude", "-p"], input=prompt, text=True, check=True, cwd=node["_worktree"].path)
    return agent

def render_prompt(node):
    """Aus den strukturierten Feldern des Knotens wird der Prompt-Text."""
    return f"Aufgabe: {node['goal']}\nFertig ist es erst, wenn die Abnahmetests bestehen."

# %% [markdown]
# ## 7. Der Orchestrator – alles zusammen
#
# Für jeden Knoten in topologischer Reihenfolge:
# 1. Worktree anlegen (vom aktuellen main abgezweigt → enthält alle Ergebnisse der Vorgänger).
# 2. Agent arbeitet im Worktree.
# 3. Gate: Abnahmetests im Worktree.
# 4. Grün → commit, merge zurück, Worktree weg. Rot → Worktree bleibt zur Inspektion, Lauf stoppt.
#
# Das ist **fail-fast**: Beim ersten Fehler werden die restlichen Knoten als *übersprungen* markiert.
# (Das Original kann zusätzlich Checkpoints/Resume, parallele „Wellen“ per ThreadPool und Kosten-Logging in SQLite.)

# %%
def run_workflow(wf, agent: Agent, repo, wt_root):
    validate_workflow(wf)
    nodes = {n["id"]: n for n in wf["nodes"]}
    ergebnisse, gestoppt = {}, False

    for nid in topological_order(wf):
        if gestoppt:
            ergebnisse[nid] = "übersprungen"
            continue
        node = nodes[nid]
        wt = create_worktree(repo, wt_root, nid)
        try:
            agent({**node, "_worktree": wt}, render_prompt(node))
        except Exception as exc:
            remove_worktree(repo, wt)
            ergebnisse[nid], gestoppt = f"Agent-Fehler: {exc}", True
            continue

        result = run_node(node, cwd=wt.path)
        if result.passed:
            commit_worktree(wt, f"agent: {nid}")
            if merge_back(repo, wt.branch):
                ergebnisse[nid] = "bestanden"
            else:
                ergebnisse[nid], gestoppt = "Merge-Konflikt", True
            remove_worktree(repo, wt)
        else:
            gruende = [g for c in result.checks for g in c.reasons]
            ergebnisse[nid], gestoppt = f"Gate rot: {gruende}", True
    return ergebnisse

# %% [markdown]
# ## 8. Demo-Lauf
#
# Wir legen ein temporäres Git-Repository mit einem ersten Commit an und starten den Workflow.
# Erwartung: beide Knoten „bestanden“, und im Git-Log zwei Merge-Commits.

# %%
tmp = Path(tempfile.mkdtemp())
repo, wt_root = tmp / "repo", tmp / "worktrees"
repo.mkdir()
git("init", cwd=repo)
(repo / "README.md").write_text("Demo\n")
git("add", "-A", cwd=repo)
git(*GIT_ID, "commit", "-m", "init", cwd=repo)

print(run_workflow(workflow, fake_agent, str(repo), str(wt_root)))
print(git("log", "--oneline", "--graph", cwd=repo).stdout)

# %% [markdown]
# ## 9. Zum Ausprobieren
#
# - Ändere bei `schritt-b` den Check auf eine Datei, die nie entsteht → das Gate wird rot, der Lauf stoppt.
# - Lass `fake_agent` eine Exception werfen → der Knoten wird als Agent-Fehler gewertet.
# - Interview-Frage zum Üben: *„Warum ist der Agent ein Parameter und nicht fest eingebaut?“*
