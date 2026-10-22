# ruff: noqa: UP006, UP007, UP035
"""R81：``backend.cli.harness`` 的 CLI 冒烟与输出契约测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, List

import pytest

from backend.application.kernel.harness_config import clear_harness_cache
from backend.cli.harness import main


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("SAGE_HARNESS_PRESET", raising=False)
    monkeypatch.delenv("SAGE_HARNESS_HOME", raising=False)
    monkeypatch.delenv("SAGE_WORKSPACE", raising=False)
    clear_harness_cache()
    yield
    clear_harness_cache()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _paths(tmp_path: Path) -> List[str]:
    return [
        "--workspace",
        str(tmp_path / "workspace"),
        "--user-home",
        str(tmp_path / "home"),
    ]


def test_presets_text_lists_all_four(capsys: pytest.CaptureFixture) -> None:
    assert main(["presets"]) == 0

    out = capsys.readouterr().out
    for name in ("standard", "focus", "headless", "dev"):
        assert name in out
    assert "office_core" in out
    assert "ask_user" in out


def test_presets_json_is_machine_readable(capsys: pytest.CaptureFixture) -> None:
    assert main(["presets", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in payload] == [
        "standard",
        "focus",
        "headless",
        "dev",
    ]
    assert payload[1]["flags"] == {"context": "compact"}


def test_dump_config_defaults_to_standard(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["dump-config", *_paths(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["preset"] == "standard"
    assert len(payload["bundles"]["selected"]) == 31
    assert payload["bundles"]["skipped"] == []
    assert payload["sources"] == ["builtin"]
    assert payload["warnings"] == []


def test_dump_config_reads_project_preset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write(
        tmp_path / "workspace" / ".sage" / "harness.yaml",
        "preset: focus\nbundles:\n  office_core: true\n",
    )

    assert main(["dump-config", *_paths(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    selected = payload["bundles"]["selected"]
    skipped = {item["name"]: item["reason"] for item in payload["bundles"]["skipped"]}
    assert payload["preset"] == "focus"
    assert len(selected) == 23
    assert "office_core" in selected
    assert skipped["browser"] == "preset"


def test_dump_config_preset_argument_overrides_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write(tmp_path / "workspace" / ".sage" / "harness.yaml", "preset: focus\n")

    assert main(["dump-config", *_paths(tmp_path), "--preset", "headless", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["preset"] == "headless"
    assert len(payload["bundles"]["selected"]) == 30
    assert payload["bundles"]["skipped"] == [{"name": "ask_user", "reason": "preset"}]


def test_dump_config_reads_patch_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    patch = _write(
        tmp_path / "patch.yaml",
        "bundles:\n  browser: false\nflags:\n  owner: cli-test\n",
    )

    assert main(["dump-config", *_paths(tmp_path), "--patch", str(patch), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["flags"] == {"owner": "cli-test"}
    assert payload["bundles"]["skipped"] == [{"name": "browser", "reason": "override"}]
    assert payload["sources"][-1] == "patch"


def test_dump_config_text_contains_provenance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    assert main(["dump-config", *_paths(tmp_path), "--preset", "focus"]) == 0

    out = capsys.readouterr().out
    assert "preset: focus" in out
    assert "selected bundles (22)" in out
    assert "browser (preset)" in out
    assert "sources:" in out


def test_check_accepts_valid_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write(tmp_path / "workspace" / ".sage" / "harness.yaml", "preset: dev\n")

    assert main(["check", *_paths(tmp_path)]) == 0
    assert "OK: preset=dev" in capsys.readouterr().out


def test_check_rejects_unknown_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    _write(
        tmp_path / "workspace" / ".sage" / "harness.yaml",
        "bundles:\n  mystery: false\n",
    )

    assert main(["check", *_paths(tmp_path)]) == 1
    assert "mystery" in capsys.readouterr().err


def test_dump_config_missing_patch_is_cli_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    code = main(
        [
            "dump-config",
            *_paths(tmp_path),
            "--patch",
            str(tmp_path / "missing.yaml"),
        ]
    )

    assert code == 2
    assert "patch 文件读取失败" in capsys.readouterr().err
