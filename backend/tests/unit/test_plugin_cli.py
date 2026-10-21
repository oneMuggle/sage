# ruff: noqa: UP006, UP007, UP035
"""R86 ``python -m backend.cli.plugin`` tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from backend.cli.plugin import build_parser, main


def _stdout_json(capsys: Any) -> Dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init_plugin(tmp_path: Path, capsys: Any) -> Path:
    root = tmp_path / "acme-echo"
    exit_code = main(
        [
            "init",
            "acme-echo",
            "--output",
            str(root),
            "--author",
            "Ada",
            "--json",
        ]
    )
    payload = _stdout_json(capsys)
    assert exit_code == 0
    assert payload["plugin"]["name"] == "acme-echo"
    return root


def test_parser_exposes_ecosystem_commands() -> None:
    parser = build_parser()

    args = parser.parse_args(["init", "acme-echo", "--template", "tool"])
    assert args.command == "init"
    args = parser.parse_args(["index", "search", "index.json", "echo"])
    assert args.index_command == "search"


def test_templates_json(capsys: Any) -> None:
    assert main(["templates", "--json"]) == 0

    payload = _stdout_json(capsys)
    assert [item["name"] for item in payload["templates"]] == [
        "tool",
        "hook",
        "mcp",
        "skill",
    ]


def test_init_validate_and_dev_json(tmp_path: Path, capsys: Any) -> None:
    root = _init_plugin(tmp_path, capsys)

    assert main(["validate", str(root), "--strict", "--json"]) == 0
    validation = _stdout_json(capsys)
    assert validation["ok"] is True
    assert validation["issues"] == []

    assert (
        main(
            [
                "dev",
                str(root),
                "--arguments-file",
                str(root / "examples" / "request.json"),
                "--config",
                '{"greeting": "Hi"}',
                "--json",
            ]
        )
        == 0
    )
    dev = _stdout_json(capsys)
    assert dev["capability"] == "acme_echo"
    assert dev["result"]["message"] == "Hi, Ada!"
    assert dev["runtime"]["state"] == "active"


def test_validate_missing_plugin_returns_one(tmp_path: Path, capsys: Any) -> None:
    assert main(["validate", str(tmp_path / "missing"), "--json"]) == 1

    payload = _stdout_json(capsys)
    assert payload["ok"] is False
    assert payload["issues"][0]["code"] == "PLUGIN_ROOT_NOT_FOUND"


def test_index_build_validate_and_search_cli(tmp_path: Path, capsys: Any) -> None:
    root = _init_plugin(tmp_path, capsys)
    index_path = tmp_path / "index.json"

    assert (
        main(
            [
                "index",
                "build",
                str(root),
                "--base-dir",
                str(tmp_path),
                "--output",
                str(index_path),
                "--json",
            ]
        )
        == 0
    )
    built = _stdout_json(capsys)
    assert built["output"] == str(index_path)
    assert built["index"]["plugins"][0]["source"]["path"] == "acme-echo"

    assert (
        main(["index", "validate", str(index_path), "--check-local", "--json"])
        == 0
    )
    validation = _stdout_json(capsys)
    assert validation["ok"] is True
    assert validation["plugin_count"] == 1

    assert (
        main(
            [
                "index",
                "search",
                str(index_path),
                "Ada",
                "--capability-type",
                "tool",
                "--json",
            ]
        )
        == 0
    )
    search = _stdout_json(capsys)
    assert [item["name"] for item in search["results"]] == ["acme-echo"]


def test_search_unknown_capability_is_input_error(
    tmp_path: Path,
    capsys: Any,
) -> None:
    root = _init_plugin(tmp_path, capsys)
    index_path = tmp_path / "index.json"
    assert (
        main(
            [
                "index",
                "build",
                str(root),
                "--base-dir",
                str(tmp_path),
                "--output",
                str(index_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "index",
                "search",
                str(index_path),
                "--capability-type",
                "widget",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "UNKNOWN_CAPABILITY_TYPE"


def test_no_command_is_input_error(capsys: Any) -> None:
    assert main([]) == 2
    assert "sage plugin" in capsys.readouterr().out
