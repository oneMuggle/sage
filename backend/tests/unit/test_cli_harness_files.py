# ruff: noqa: UP006, UP007, UP035
"""R84：harness exporter 与 ``files`` CLI 契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List

import pytest
import yaml

from backend.agents.agents_files import parse_agent_file
from backend.application.kernel.harness_config import clear_harness_cache
from backend.application.kernel.harness_files import HarnessFileSpec, load_harness_lock
from backend.application.kernel.harness_snapshots import write_harness_files
from backend.cli.harness import main
from backend.cli.harness_export import collect_harness_file_specs


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "SAGE_HARNESS_PRESET",
        "SAGE_HARNESS_HOME",
        "SAGE_WORKSPACE",
        "SAGE_SKILLS_DIR",
        "SAGE_HARNESS_LOCK_ENFORCE",
        "SAGE_AGENTS_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_harness_cache()
    yield
    clear_harness_cache()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _args(tmp_path: Path) -> List[str]:
    return [
        "--workspace",
        str(tmp_path / "workspace"),
        "--user-home",
        str(tmp_path / "home"),
    ]


def _seed_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    _write(
        workspace / ".sage" / "agents" / "primary.md",
        "---\n"
        "name: Custom Primary\n"
        "role: coordinator\n"
        "description: Custom primary profile\n"
        "tools: read_file\n"
        "memory_access: working\n"
        "max_iterations: 9\n"
        "model: test-model\n"
        "temperature: 0.2\n"
        "max_tokens: 2048\n"
        "---\n\nCUSTOM PRIMARY PROMPT\n",
    )
    _write(
        workspace / ".sage" / "agents" / "coder.md",
        "---\n"
        "name: Custom Coder\n"
        "role: coder\n"
        "description: Custom coder profile\n"
        "tools: read_file, write_file\n"
        "memory_access: semantic\n"
        "max_iterations: 7\n"
        "model: coder-model\n"
        "temperature: 0.1\n"
        "max_tokens: 1024\n"
        "---\n\nCUSTOM CODER PROMPT\n",
    )
    _write(workspace / "AGENTS.md", "PROJECT RULE FROM AGENTS\n")
    _write(
        workspace / "skills" / "demo" / "SKILL.md",
        "---\nname: demo\ndescription: workspace demo\n---\n\nWORKSPACE DEMO\n",
    )
    _write(
        home / ".sage" / "skills" / "demo" / "SKILL.md",
        "---\nname: demo\ndescription: user demo\n---\n\nUSER DEMO\n",
    )


def test_files_export_diff_snapshot_rollback_and_plugins_layer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _seed_workspace(tmp_path)
    workspace = tmp_path / "workspace"
    root = workspace / "harness"

    assert main(["files", "export", *_args(tmp_path), "--json"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["file_count"] >= 24
    assert exported["snapshot"]["id"] == "initial"

    expected = {
        ".gitignore",
        "system.md",
        "guardrails.yaml",
        "memory.yaml",
        "tool-guidance.yaml",
        "plugins.yaml",
        "scripts/policy.yaml",
        "scripts/README.md",
        "proposals/README.md",
        "evidence/README.md",
        "subagents/primary.md",
        "subagents/coder.md",
        "skills/demo/SKILL.md",
        "skills/academic-search/SKILL.md",
    }
    assert expected <= {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}

    system = (root / "system.md").read_text(encoding="utf-8")
    assert "version: 1" in system
    assert "workspace:.sage/agents/primary.md" in system
    assert "CUSTOM PRIMARY PROMPT" in system
    assert "PROJECT RULE FROM AGENTS" in system

    coder = parse_agent_file(root / "subagents" / "coder.md")
    assert coder["name"] == "Custom Coder"
    assert coder["system_prompt"] == "CUSTOM CODER PROMPT"
    assert coder["tools"] == ["read_file", "write_file"]

    guardrails = yaml.safe_load((root / "guardrails.yaml").read_text(encoding="utf-8"))
    assert guardrails["_meta"]["version"] == 1
    assert guardrails["tool_policy"]["max_tool_calls_per_run"] == 100
    assert "interactive" in guardrails["permissions"]["modes"]

    memory = yaml.safe_load((root / "memory.yaml").read_text(encoding="utf-8"))
    assert memory["scoring"]["weights"]["relevance"] == 0.40
    assert memory["content_exported"] is False

    guidance = yaml.safe_load(
        (root / "tool-guidance.yaml").read_text(encoding="utf-8")
    )
    tools = {item["name"]: item for item in guidance["tools"]}
    assert len(tools) >= 90
    assert tools["bash"]["bundle"] == "shell"
    assert tools["bash"]["risk"] == "exec"
    assert guidance["excluded_bundles"] == [
        {"name": "mcp", "reason": "external_discovery"},
        {"name": "plugins", "reason": "dynamic_plugin_runtime"},
    ]

    assert "WORKSPACE DEMO" in (
        root / "skills" / "demo" / "SKILL.md"
    ).read_text(encoding="utf-8")
    scripts = yaml.safe_load((root / "scripts" / "policy.yaml").read_text(encoding="utf-8"))
    assert scripts["execution_tools"]["sandbox"] == ["repl", "execute_code"]
    assert scripts["scripts_copied"] is False

    lock = load_harness_lock(root)
    assert lock is not None
    assert {
        "system",
        "guardrails",
        "memory",
        "tool-guidance",
        "subagents",
        "skills",
        "scripts",
        "plugins",
    } <= {entry.component for entry in lock.files}

    assert main(["files", "verify", *_args(tmp_path), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["valid"] is True
    assert status["counts"]["unchanged"] == exported["file_count"]

    with open(root / "system.md", "a", encoding="utf-8") as handle:
        handle.write("DRIFT\n")
    _write(root / "extra.md", "extra\n")

    assert main(["files", "verify", *_args(tmp_path)]) == 1
    capsys.readouterr()
    assert main(["files", "diff", *_args(tmp_path), "--patch", "--json"]) == 0
    diff = json.loads(capsys.readouterr().out)
    by_path = {item["path"]: item for item in diff["entries"]}
    assert by_path["system.md"]["status"] == "modified"
    assert "+DRIFT" in by_path["system.md"]["patch"]
    assert by_path["extra.md"]["status"] == "added"

    assert main(["files", "update-lock", *_args(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert main(["check", *_args(tmp_path), "--json"]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["harness_files"][0]["valid"] is True

    assert main(["files", "snapshot", *_args(tmp_path), "--name", "reviewed"]) == 0
    capsys.readouterr()
    (root / "system.md").write_text("BAD STATE\n", encoding="utf-8")
    (root / "extra.md").unlink()
    assert main(["files", "rollback", *_args(tmp_path), "--snapshot", "reviewed"]) == 0
    capsys.readouterr()
    assert "DRIFT" in (root / "system.md").read_text(encoding="utf-8")
    assert (root / "extra.md").exists()

    plugins_path = root / "plugins.yaml"
    plugins_text = plugins_path.read_text(encoding="utf-8")
    plugins_path.write_text(
        plugins_text.replace("preset: standard", "preset: focus", 1),
        encoding="utf-8",
    )
    assert main(["files", "update-lock", *_args(tmp_path)]) == 0
    capsys.readouterr()
    clear_harness_cache()
    assert main(["dump-config", *_args(tmp_path), "--json"]) == 0
    dumped = json.loads(capsys.readouterr().out)
    assert dumped["preset"] == "focus"
    assert any(source.endswith("plugins.yaml") for source in dumped["sources"])

    with open(root / "system.md", "a", encoding="utf-8") as handle:
        handle.write("UNREVIEWED\n")
    assert main(["check", *_args(tmp_path)]) == 1
    assert "lock" in capsys.readouterr().err


def test_user_scope_export_excludes_workspace_surfaces(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)

    specs = collect_harness_file_specs(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={},
        scope="user",
        updated_at="2026-10-21T00:00:00Z",
        include_tool_schemas=False,
    )
    by_path = {spec.path: spec for spec in specs}

    assert "CUSTOM PRIMARY PROMPT" not in str(by_path["system.md"].content)
    assert "PROJECT RULE FROM AGENTS" not in str(by_path["system.md"].content)
    assert "CUSTOM CODER PROMPT" not in str(by_path["subagents/coder.md"].content)
    assert b"USER DEMO" in by_path["skills/demo/SKILL.md"].data


def test_files_status_missing_root_and_verify_requires_lock(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    missing = tmp_path / "missing-harness"

    assert main(["files", "status", "--output", str(missing), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["exists"] is False
    assert status["adopted"] is False

    assert main(["files", "verify", "--output", str(missing), "--json"]) == 1
    verified = json.loads(capsys.readouterr().out)
    assert verified["adopted"] is False


def test_files_export_requires_force_for_existing_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    root = tmp_path / "harness"
    specs = [HarnessFileSpec("system.md", "hello\n", component="system")]
    write_harness_files(root, specs, create_snapshot=False)
    monkeypatch.setattr(
        "backend.cli.harness_export.collect_harness_file_specs",
        lambda **_kwargs: specs,
    )

    assert main(["files", "export", "--output", str(root)]) == 2
    assert "--force" in capsys.readouterr().err
    assert main(["files", "export", "--output", str(root), "--force"]) == 0
    assert "exported 1 harness files" in capsys.readouterr().out
