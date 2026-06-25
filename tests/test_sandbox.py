"""Tests fuer src/sandbox.py. Kein echtes git/docker -- runner wird immer gemockt."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sandbox
from sandbox import (
    MergeResult,
    ParseError,
    SandboxResult,
    Worktree,
    create_worktree,
    merge_back,
    parse_tagged_output,
    remove_worktree,
    run_in_sandbox,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(stdout="", stderr="", returncode=0):
    r = subprocess.CompletedProcess(args=[], returncode=returncode)
    r.stdout = stdout
    r.stderr = stderr
    return r


def _fake_worktree(path="/repo/.aw-worktrees/node1"):
    return Worktree(path=path, branch="agent/node1", base="HEAD")


def _mock_which(monkeypatch, value="/usr/bin/tool"):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: value)


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------


def test_create_worktree_correct_git_command(monkeypatch, tmp_path):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    create_worktree(str(tmp_path), "my-node", runner=fake_runner)
    cmd = captured[0]
    assert cmd[0] == "git"
    assert cmd[1:3] == ["-C", str(tmp_path)]
    assert "worktree" in cmd
    assert "add" in cmd
    assert "-b" in cmd


def test_create_worktree_branch_name(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok()

    wt = create_worktree(str(tmp_path), "node42", runner=fake_runner)
    assert wt.branch == "agent/node42"


def test_create_worktree_path_under_aw_worktrees(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok()

    wt = create_worktree(str(tmp_path), "node42", runner=fake_runner)
    assert ".aw-worktrees" in wt.path
    assert "node42" in wt.path


def test_create_worktree_raises_on_git_failure(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(stderr="fatal: branch already exists", returncode=128)

    with pytest.raises(RuntimeError, match="fehlgeschlagen"):
        create_worktree(str(tmp_path), "node", runner=fake_runner)


def test_create_worktree_missing_git_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="nicht im PATH"):
        create_worktree(str(tmp_path), "node")


# ---------------------------------------------------------------------------
# run_in_sandbox
# ---------------------------------------------------------------------------


def test_run_in_sandbox_memory_always_set(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok(stdout="ok")

    run_in_sandbox(_fake_worktree(), "echo ok", image="img", memory_limit="1.5g", runner=fake_runner)
    cmd = captured[0]
    assert "--memory" in cmd
    assert cmd[cmd.index("--memory") + 1] == "1.5g"


def test_run_in_sandbox_volume_mount(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    wt = _fake_worktree("/repo/.aw-worktrees/n1")
    run_in_sandbox(wt, "true", image="img", memory_limit="1g", runner=fake_runner)
    cmd = captured[0]
    assert "-v" in cmd
    assert cmd[cmd.index("-v") + 1] == "/repo/.aw-worktrees/n1:/work"


def test_run_in_sandbox_workdir(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(_fake_worktree(), "true", image="img", memory_limit="1g", runner=fake_runner)
    cmd = captured[0]
    assert "-w" in cmd
    assert cmd[cmd.index("-w") + 1] == "/work"


def test_run_in_sandbox_image_and_bash_lc(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(_fake_worktree(), "pytest -q", image="aw-sandbox:dev", memory_limit="1g", runner=fake_runner)
    cmd = captured[0]
    assert "aw-sandbox:dev" in cmd
    assert "bash" in cmd
    assert "-lc" in cmd
    assert "pytest -q" in cmd


def test_run_in_sandbox_network_default_bridge(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(_fake_worktree(), "true", image="img", memory_limit="1g", runner=fake_runner)
    cmd = captured[0]
    assert "--network" in cmd
    assert cmd[cmd.index("--network") + 1] == "bridge"


def test_run_in_sandbox_network_override(monkeypatch):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(_fake_worktree(), "true", image="img", memory_limit="1g", network="none", runner=fake_runner)
    cmd = captured[0]
    assert cmd[cmd.index("--network") + 1] == "none"


def test_run_in_sandbox_timeout(monkeypatch):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    result = run_in_sandbox(
        _fake_worktree(), "sleep 99", image="img", memory_limit="1g", wall_timeout=1, runner=fake_runner
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_run_in_sandbox_result_fields(monkeypatch):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(stdout="hello\n", stderr="warn\n", returncode=42)

    result = run_in_sandbox(_fake_worktree(), "cmd", image="img", memory_limit="1g", runner=fake_runner)
    assert result.exit_code == 42
    assert result.stdout == "hello\n"
    assert result.stderr == "warn\n"
    assert result.timed_out is False


def test_run_in_sandbox_missing_docker_raises(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="nicht im PATH"):
        run_in_sandbox(_fake_worktree(), "true", image="img", memory_limit="1g")


def test_run_in_sandbox_env_passthrough_flag_present(monkeypatch):
    """env_passthrough=["ANTHROPIC_API_KEY"] -> '-e ANTHROPIC_API_KEY' im Befehl."""
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(
        _fake_worktree(), "true", image="img", memory_limit="1g",
        env_passthrough=["ANTHROPIC_API_KEY"], runner=fake_runner,
    )
    cmd = captured[0]
    assert "-e" in cmd
    idx = cmd.index("-e")
    assert cmd[idx + 1] == "ANTHROPIC_API_KEY"


def test_run_in_sandbox_env_passthrough_no_value_in_cmd(monkeypatch):
    """Der Wert des Keys darf NIE in argv erscheinen -- nur der Name."""
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(
        _fake_worktree(), "true", image="img", memory_limit="1g",
        env_passthrough=["ANTHROPIC_API_KEY"], runner=fake_runner,
    )
    cmd = captured[0]
    assert not any("=" in token and "ANTHROPIC_API_KEY" in token for token in cmd)


def test_run_in_sandbox_no_env_passthrough_no_e_flag(monkeypatch):
    """Ohne env_passthrough enthaelt der Befehl kein '-e'-Flag."""
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(_fake_worktree(), "true", image="img", memory_limit="1g", runner=fake_runner)
    assert "-e" not in captured[0]


def test_run_in_sandbox_env_passthrough_multiple(monkeypatch):
    """Mehrere Namen erzeugen je ein '-e NAME'-Paar."""
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    run_in_sandbox(
        _fake_worktree(), "true", image="img", memory_limit="1g",
        env_passthrough=["FOO", "BAR"], runner=fake_runner,
    )
    cmd = captured[0]
    e_indices = [i for i, t in enumerate(cmd) if t == "-e"]
    assert len(e_indices) == 2
    assert cmd[e_indices[0] + 1] == "FOO"
    assert cmd[e_indices[1] + 1] == "BAR"


# ---------------------------------------------------------------------------
# merge_back
# ---------------------------------------------------------------------------


def test_merge_back_uses_no_ff(monkeypatch, tmp_path):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok(stdout="Merge made by the 'ort' strategy.")

    result = merge_back(str(tmp_path), "agent/n1", "main", runner=fake_runner)
    assert "--no-ff" in captured[0]
    assert result.merged is True
    assert result.conflict is False


def test_merge_back_conflict_no_raise(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(
            stdout="CONFLICT (content): Merge conflict in foo.py\nAutomatic merge failed.",
            returncode=1,
        )

    result = merge_back(str(tmp_path), "agent/n1", "main", runner=fake_runner)
    assert result.merged is False
    assert result.conflict is True


def test_merge_back_non_conflict_failure(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(stdout="error: not a git repository", returncode=1)

    result = merge_back(str(tmp_path), "agent/n1", "main", runner=fake_runner)
    assert result.merged is False
    assert result.conflict is False


# ---------------------------------------------------------------------------
# remove_worktree
# ---------------------------------------------------------------------------


def test_remove_worktree_success(monkeypatch, tmp_path):
    _mock_which(monkeypatch)
    captured = []

    def fake_runner(cmd, **kwargs):
        captured.append(cmd)
        return _ok()

    wt = Worktree(path=str(tmp_path / "wt"), branch="agent/n1", base="HEAD")
    remove_worktree(str(tmp_path), wt, runner=fake_runner)
    assert "worktree" in captured[0]
    assert "remove" in captured[0]


def test_remove_worktree_dirty_no_raise(monkeypatch, tmp_path):
    """Dirty worktree: kein raise, worktree bleibt erhalten."""
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(stderr="fatal: 'the worktree is dirty'", returncode=1)

    wt = Worktree(path=str(tmp_path / "wt"), branch="agent/n1", base="HEAD")
    remove_worktree(str(tmp_path), wt, runner=fake_runner)  # must not raise


def test_remove_worktree_other_failure_no_raise(monkeypatch, tmp_path):
    _mock_which(monkeypatch)

    def fake_runner(cmd, **kwargs):
        return _ok(stderr="fatal: worktree not found", returncode=1)

    wt = Worktree(path=str(tmp_path / "wt"), branch="agent/n1", base="HEAD")
    remove_worktree(str(tmp_path), wt, runner=fake_runner)  # must not raise


# ---------------------------------------------------------------------------
# parse_tagged_output
# ---------------------------------------------------------------------------


def test_parse_tagged_output_happy_path():
    stdout = 'preamble\n<plan>{"tasks": [1, 2]}</plan>\npostamble'
    result = parse_tagged_output(stdout, "plan")
    assert result == {"tasks": [1, 2]}


def test_parse_tagged_output_multiline_json():
    stdout = '<result>\n{\n  "a": 1\n}\n</result>'
    result = parse_tagged_output(stdout, "result")
    assert result == {"a": 1}


def test_parse_tagged_output_missing_tag():
    with pytest.raises(ParseError, match="nicht.*gefunden"):
        parse_tagged_output("no tag here at all", "plan")


def test_parse_tagged_output_broken_json():
    with pytest.raises(ParseError, match="JSON"):
        parse_tagged_output("<result>{not: valid}</result>", "result")


def test_parse_tagged_output_schema_violation():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(ParseError, match="Schema"):
        parse_tagged_output('<out>{"age": 42}</out>', "out", schema=schema)


def test_parse_tagged_output_schema_valid():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    result = parse_tagged_output('<out>{"name": "Alice"}</out>', "out", schema=schema)
    assert result == {"name": "Alice"}
