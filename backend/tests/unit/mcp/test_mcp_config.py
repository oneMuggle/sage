"""M3 — MCP multi-server config unit tests.

Covers: validation, frozen immutability, built-in drawio detection,
user JSON load/merge/corrupt-file fallback, atomic save round-trip.
"""

import dataclasses
import json

import pytest

from backend.mcp import config as cfg
from backend.mcp.config import (
    McpConfigError,
    delete_user_server_config,
    load_server_configs,
    load_user_server_configs,
    save_user_server_configs,
    upsert_user_server_config,
    validate_server_config,
)


class TestValidate:
    def test_valid_config_is_frozen(self):
        c = validate_server_config(name="srv-1", command="node", args=("a.js",))
        assert c.name == "srv-1"
        assert c.command == "node"
        assert c.args == ("a.js",)
        assert c.enabled is True
        assert c.required is False
        assert c.timeout_seconds == 30.0
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.name = "other"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "bad_name",
        ["Srv", "has space", "中文", "", "x" * 65, "dot.name", "slash/name"],
    )
    def test_invalid_names_rejected(self, bad_name):
        with pytest.raises(McpConfigError):
            validate_server_config(name=bad_name, command="node")

    def test_empty_command_rejected(self):
        with pytest.raises(McpConfigError):
            validate_server_config(name="srv", command="   ")

    def test_nonpositive_timeout_rejected(self):
        with pytest.raises(McpConfigError):
            validate_server_config(name="srv", command="node", timeout_seconds=0)
        with pytest.raises(McpConfigError):
            validate_server_config(name="srv", command="node", timeout_seconds=-5)

    def test_non_string_env_rejected(self):
        with pytest.raises(McpConfigError):
            validate_server_config(name="srv", command="node", env={"A": 1})  # type: ignore[dict-item]

    def test_list_args_normalized_to_tuple(self):
        c = validate_server_config(name="srv", command="node", args=["a", "b"])  # type: ignore[arg-type]
        assert c.args == ("a", "b")


class TestBuiltins:
    def test_drawio_present_only_when_dist_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "_project_root", lambda: tmp_path)
        assert cfg.builtin_server_configs() == []

        entry = tmp_path / "packages" / "drawio-mcp-server" / "dist" / "index.js"
        entry.parent.mkdir(parents=True)
        entry.write_text("// built")
        builtins = cfg.builtin_server_configs()
        assert [b.name for b in builtins] == ["drawio"]
        drawio = builtins[0]
        assert drawio.command == "node"
        assert drawio.args == (str(entry),)
        assert "DRAWIO_BASE_URL" in drawio.env


class TestUserFile:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_user_server_configs(tmp_path / "nope.json") == []

    def test_corrupt_file_falls_back_to_empty(self, tmp_path, caplog):
        path = tmp_path / "mcp_servers.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_user_server_configs(path) == []
        assert any("corrupt" in r.message for r in caplog.records)

    def test_wrong_shape_falls_back_to_empty(self, tmp_path):
        path = tmp_path / "mcp_servers.json"
        path.write_text(json.dumps({"servers": "nope"}), encoding="utf-8")
        assert load_user_server_configs(path) == []

    def test_invalid_entries_skipped_valid_loaded(self, tmp_path, caplog):
        path = tmp_path / "mcp_servers.json"
        payload = {
            "servers": [
                {"name": "GOOD_SRV", "command": "node"},  # invalid name → skipped
                {"name": "", "command": "node"},  # invalid name → skipped
                {"name": "ok", "command": "node", "args": ["x.js"]},
                "not-a-dict",
            ]
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_user_server_configs(path)
        assert [c.name for c in loaded] == ["ok"]
        assert any("skipping" in r.message for r in caplog.records)

    def test_duplicate_names_deduped_first_wins(self, tmp_path):
        path = tmp_path / "mcp_servers.json"
        payload = {
            "servers": [
                {"name": "dup", "command": "first"},
                {"name": "dup", "command": "second"},
            ]
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_user_server_configs(path)
        assert len(loaded) == 1
        assert loaded[0].command == "first"


class TestSave:
    def test_atomic_save_round_trip(self, tmp_path):
        path = tmp_path / "mcp_servers.json"
        configs = [
            validate_server_config(name="a", command="node", env={"TOKEN": "x"}),
            validate_server_config(name="b", command="python", required=True),
        ]
        save_user_server_configs(configs, path)
        loaded = load_user_server_configs(path)
        assert [c.name for c in loaded] == ["a", "b"]
        assert loaded[1].required is True
        assert loaded[0].env == {"TOKEN": "x"}
        # no leftover temp files
        assert list(tmp_path.glob(".mcp_servers.*.tmp")) == []

    def test_save_rejects_duplicate_names(self, tmp_path):
        path = tmp_path / "mcp_servers.json"
        dup = [
            validate_server_config(name="a", command="node"),
            validate_server_config(name="a", command="python"),
        ]
        with pytest.raises(McpConfigError):
            save_user_server_configs(dup, path)

    def test_upsert_and_delete(self, tmp_path):
        path = tmp_path / "mcp_servers.json"
        upsert_user_server_config(validate_server_config(name="a", command="node"), path)
        upsert_user_server_config(validate_server_config(name="a", command="python"), path)
        loaded = load_user_server_configs(path)
        assert len(loaded) == 1
        assert loaded[0].command == "python"
        assert delete_user_server_config("a", path) is True
        assert delete_user_server_config("a", path) is False
        assert load_user_server_configs(path) == []


class TestMerge:
    def test_user_overrides_builtin_by_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            cfg,
            "builtin_server_configs",
            lambda: [validate_server_config(name="drawio", command="node", args=("built.js",))],
        )
        user_path = tmp_path / "mcp_servers.json"
        upsert_user_server_config(
            validate_server_config(name="drawio", command="node", enabled=False),
            user_path,
        )
        upsert_user_server_config(
            validate_server_config(name="extra", command="python"), user_path
        )
        monkeypatch.setattr(cfg, "get_user_config_path", lambda: user_path)
        merged = {c.name: c for c in load_server_configs()}
        assert set(merged) == {"drawio", "extra"}
        assert merged["drawio"].enabled is False  # user wins
