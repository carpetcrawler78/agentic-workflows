"""Sandbox-Primitive fuer Stufe-2 (worktree + docker + merge + structured output).

Jede Funktion baut ihr Kommando deterministisch und ist mit gemocktem subprocess
testbar -- KEIN echtes docker/git wird in der Test-Suite ausgefuehrt.
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ParseError(ValueError):
    """Strukturierter Output fehlt, ist kein JSON oder verletzt das Schema."""


@dataclass
class Worktree:
    path: str
    branch: str
    base: str


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


@dataclass
class MergeResult:
    merged: bool
    conflict: bool
    stdout: str
    stderr: str


def _require(tool):
    """Wirft RuntimeError wenn tool nicht im PATH ist."""
    if shutil.which(tool) is None:
        raise RuntimeError(f"{tool} nicht im PATH -- bitte installieren")


def create_worktree(repo_root, node_id, base="HEAD", *, runner=subprocess.run):
    """Legt git-worktree auf Branch agent/<node_id> an.

    Pfad: <repo_root>/.aw-worktrees/<node_id> (relativ zum repo_root).
    Gibt Worktree-Dataclass zurueck. Wirft RuntimeError bei git-Fehlschlag."""
    _require("git")
    branch = f"agent/{node_id}"
    wt_path = str(Path(repo_root) / ".aw-worktrees" / node_id)
    result = runner(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", branch, wt_path, base],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add fehlgeschlagen: {result.stderr.strip()}")
    return Worktree(path=wt_path, branch=branch, base=base)


def run_in_sandbox(
    worktree,
    command,
    *,
    image,
    memory_limit,
    idle_timeout=None,
    wall_timeout=None,
    network="bridge",
    runner=subprocess.run,
):
    """Startet docker-Container mit gemounteten worktree und fuehrt command aus.

    --memory <memory_limit> ist IMMER gesetzt (Hetzner-Constraint).
    network="bridge" erlaubt egress zur Anthropic-API.
    Gibt SandboxResult zurueck; bei Timeout timed_out=True, exit_code=None."""
    _require("docker")
    cmd = [
        "docker", "run", "--rm",
        "--memory", memory_limit,
        "--network", network,
        "-v", f"{worktree.path}:/work",
        "-w", "/work",
        image,
        "bash", "-lc", command,
    ]
    timeout = wall_timeout or idle_timeout
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=timeout)
        return SandboxResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(exit_code=None, stdout="", stderr="", timed_out=True)


def merge_back(repo_root, branch, base, *, runner=subprocess.run):
    """git merge --no-ff <branch> im repo_root.

    Konflikt wird sauber als conflict=True zurueckgegeben -- kein raise.
    no-ff bewusst: Merge-Commits bleiben erhalten fuer spaetere Multi-Branch-Merge."""
    _require("git")
    result = runner(
        ["git", "-C", str(repo_root), "merge", "--no-ff", branch],
        capture_output=True,
        text=True,
    )
    conflict = result.returncode != 0 and "CONFLICT" in result.stdout
    return MergeResult(
        merged=result.returncode == 0,
        conflict=conflict,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def remove_worktree(repo_root, worktree, *, force_keep_on_dirty=True, runner=subprocess.run):
    """Raeumt worktree auf. Bei dirty/Fehlschlag: erhalten und melden, nicht werfen."""
    _require("git")
    result = runner(
        ["git", "-C", str(repo_root), "worktree", "remove", worktree.path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[sandbox] worktree erhalten (remove fehlgeschlagen): {result.stderr.strip()}"
        )


def parse_tagged_output(stdout, tag, schema=None):
    """Extrahiert <tag>...</tag> aus stdout, parst als JSON, validiert optional.

    Wirft ParseError bei fehlendem Tag, kaputtem JSON oder Schema-Verstoss."""
    pattern = rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>"
    match = re.search(pattern, stdout, re.DOTALL)
    if not match:
        raise ParseError(f"Tag <{tag}> nicht in stdout gefunden")
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Kein gueltiges JSON im <{tag}>-Block: {exc}") from exc
    if schema is not None:
        from jsonschema import Draft202012Validator  # noqa: PLC0415
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(data))
        if errors:
            raise ParseError(f"Schema-Verstoss in <{tag}>: {errors[0].message}")
    return data
