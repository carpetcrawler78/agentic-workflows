"""Tests fuer src/sandbox_agent.py -- gemocktes run_in_sandbox, kein echter docker."""

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sandbox_agent
from sandbox import SandboxResult, Worktree
from sandbox_agent import make_sandbox_agent


def _fake_worktree():
    return Worktree(path="/fake/wt", branch="agent/n1", base="HEAD")


def _node(model="sonnet"):
    return {"id": "n1", "model": model, "_worktree": _fake_worktree()}


def _ok_sandbox(**kwargs):
    return SandboxResult(exit_code=0, stdout="", stderr="", timed_out=False)


def _fail_sandbox(wt, command, **kwargs):
    return SandboxResult(exit_code=1, stdout="", stderr="tests failed", timed_out=False)


# ---------------------------------------------------------------------------
# Modell-Routing
# ---------------------------------------------------------------------------


def test_model_routing_sonnet(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    agent(_node("sonnet"), "do something")
    assert "--model sonnet" in captured[0]


def test_model_routing_planner(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    agent(_node("planner"), "plan this")
    assert "--model opus" in captured[0]


def test_model_routing_local_warns_fallback_to_sonnet(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    with pytest.warns(UserWarning, match="local"):
        agent(_node("local"), "trivial task")
    assert "--model sonnet" in captured[0]


def test_model_routing_default_sonnet(monkeypatch):
    """Kein 'model'-Key im node -> Default sonnet."""
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    agent({"id": "n1", "_worktree": _fake_worktree()}, "prompt")
    assert "--model sonnet" in captured[0]


# ---------------------------------------------------------------------------
# Permission-Mode
# ---------------------------------------------------------------------------


def test_bypass_permissions_flag(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    agent(_node(), "do it")
    assert "bypassPermissions" in captured[0]


# ---------------------------------------------------------------------------
# Fehlerbehandlung
# ---------------------------------------------------------------------------


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", _fail_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    with pytest.raises(RuntimeError, match="fehlgeschlagen"):
        agent(_node(), "some task")


def test_missing_worktree_raises():
    agent = make_sandbox_agent(image="img", memory_limit="1g")
    with pytest.raises(RuntimeError, match="_worktree"):
        agent({"id": "n1"}, "prompt")


# ---------------------------------------------------------------------------
# Optionale Parameter
# ---------------------------------------------------------------------------


def test_max_budget_usd_in_command(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g", max_budget_usd=0.5)
    agent(_node(), "prompt")
    assert "--max-budget-usd" in captured[0]
    assert "0.5" in captured[0]


def test_extra_args_appended(monkeypatch):
    captured = []

    def fake_run_in_sandbox(wt, command, **kwargs):
        captured.append(command)
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="img", memory_limit="1g", extra_args=["--verbose"])
    agent(_node(), "prompt")
    assert "--verbose" in captured[0]


def test_image_and_memory_passed_to_sandbox(monkeypatch):
    calls = []

    def fake_run_in_sandbox(wt, command, *, image, memory_limit, **kwargs):
        calls.append({"image": image, "memory_limit": memory_limit})
        return _ok_sandbox()

    monkeypatch.setattr(sandbox_agent, "run_in_sandbox", fake_run_in_sandbox)
    agent = make_sandbox_agent(image="aw-sandbox:dev", memory_limit="2g")
    agent(_node(), "prompt")
    assert calls[0]["image"] == "aw-sandbox:dev"
    assert calls[0]["memory_limit"] == "2g"
