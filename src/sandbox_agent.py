"""Isolierter Sandbox-Agent: Claude-Code-CLI im docker-Container.

make_sandbox_agent() liefert ein Agent-Callable (node, prompt) -> None.
Der Orchestrator-Workspace-Hook injiziert node['_worktree'] vor dem Aufruf.
"""

import shlex
import subprocess
import warnings

try:
    from .sandbox import run_in_sandbox
except ImportError:
    from sandbox import run_in_sandbox

# Mapping Schema-Enum -> Claude-CLI-Modell-Alias (verifiziert mit CLI 2.1.191)
_MODEL_MAP = {
    "planner": "opus",
    "sonnet": "sonnet",
}

_LOCAL_WARNING = (
    "model='local' nicht verfuegbar (kein lokales LLM auf Hetzner) -- Fallback auf 'sonnet'"
)


def make_sandbox_agent(
    *,
    image,
    memory_limit="1.5g",
    model_router=None,
    extra_args=None,
    max_budget_usd=None,
    env_passthrough=None,
    runner=subprocess.run,
):
    """Factory: Agent-Callable fuer isolierte docker-Container-Laeufe.

    node muss '_worktree' enthalten (wird vom Orchestrator-Workspace-Hook gesetzt).
    Modell-Routing: node.get('model') in {planner, sonnet, local};
    local -> UserWarning + Fallback auf sonnet.
    exit_code != 0 -> raise RuntimeError (Orchestrator wertet als Knotenfehlschlag).

    Optionale Parameter:
    - max_budget_usd: --max-budget-usd pro Knoten (nur mit --print, Default aus).
    - extra_args: werden ans CLI-Kommando angehaengt.
    - env_passthrough: Env-Var-Namen, die per '-e NAME' an Docker weitergegeben werden.
      Default None -> ["ANTHROPIC_API_KEY"]."""
    extra_args = list(extra_args or [])
    _env_passthrough = env_passthrough if env_passthrough is not None else ["ANTHROPIC_API_KEY"]

    def agent(node, prompt):
        worktree = node.get("_worktree")
        if worktree is None:
            raise RuntimeError(
                "sandbox_agent: node['_worktree'] fehlt -- workspace=None im Orchestrator?"
            )

        model_hint = node.get("model", "sonnet")
        if model_hint == "local":
            warnings.warn(_LOCAL_WARNING, stacklevel=2)
            model_hint = "sonnet"
        model_alias = _MODEL_MAP.get(model_hint, "sonnet")

        parts = [
            "claude",
            "-p", shlex.quote(prompt),
            "--model", model_alias,
            "--permission-mode", "bypassPermissions",
        ]
        if max_budget_usd is not None:
            parts += ["--max-budget-usd", str(max_budget_usd)]
        parts += extra_args
        command = " ".join(parts)

        result = run_in_sandbox(
            worktree,
            command,
            image=image,
            memory_limit=memory_limit,
            env_passthrough=_env_passthrough,
            runner=runner,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Agent fehlgeschlagen (exit_code={result.exit_code}): "
                f"{result.stderr[:200]}"
            )

    return agent
