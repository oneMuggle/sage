"""Rescue CLI — parser / config / safe-mode / allowlist."""
from __future__ import annotations

import json

from backend.cli import rescue
from backend.services.rescue import allowlist as al, config_wizard as cw


def test_parser_has_all_subcommands():
    parser = rescue.build_parser()
    ns = parser.parse_args(["config", "list"])
    assert ns.command == "config"
    assert ns.action == "list"
    ns = parser.parse_args(["safe-mode", "set", "2"])
    assert ns.command == "safe-mode"
    assert ns.level == 2
    ns = parser.parse_args(["security", "detect"])
    assert ns.action == "detect"
    ns = parser.parse_args([])
    assert ns.command is None  # 默认 shell


class TestConfigCommands:
    def test_add_then_list(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
        rc = rescue.main(
            [
                "config",
                "add",
                "--base-url",
                "http://10.0.0.5:8000/v1",
                "--api-key",
                "sk-cli-test",
                "--model",
                "qwen2.5-7b",
                "--no-backup",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "已创建端点" in out

        rc = rescue.main(["config", "list", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1
        assert data[0]["baseUrl"] == "http://10.0.0.5:8000/v1"
        assert data[0]["hasApiKey"] is True
        # 脱敏：不能出现明文
        assert "sk-cli-test" not in json.dumps(data)

    def test_remove_requires_confirmation(self, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
        rescue.main(
            [
                "config",
                "add",
                "--base-url",
                "http://x/v1",
                "--api-key",
                "k",
                "--no-backup",
            ]
        )
        capsys.readouterr()
        ep_id = cw.list_endpoints()[0]["id"]
        # 无 --yes 且 stdin EOF → 不删除
        rc = rescue.main(["config", "remove", "--id", ep_id])
        assert rc == 2


class TestSafeModeCommands:
    def test_set_and_status(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
        rc = rescue.main(["safe-mode", "set", "2"])
        assert rc == 0
        capsys.readouterr()  # 清空 set 的输出
        rc = rescue.main(["safe-mode", "status"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["level"] == 2

    def test_off_resets_to_zero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
        rescue.main(["safe-mode", "set", "3"])
        capsys.readouterr()
        rc = rescue.main(["safe-mode", "off"])
        assert rc == 0
        capsys.readouterr()
        rc = rescue.main(["safe-mode", "status"])
        data = json.loads(capsys.readouterr().out)
        assert data["level"] == 0


class TestSecurityCommand:
    def test_detect_non_windows_is_empty(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "backend.services.rescue.security_software.platform.system",
            lambda: "Linux",
        )
        rc = rescue.main(["security", "detect", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data == []


class TestAllowlist:
    def test_build_and_write(self, tmp_path):
        data = al.build_allowlist(user_data_dir=tmp_path)
        assert data["schema"] == 1
        assert any(p["port"] == 8765 for p in data["ports"])
        md = al.write_allowlist(tmp_path / "out" / "allowlist.md", user_data_dir=tmp_path)
        assert md.is_file()
        assert md.with_suffix(".json").is_file()
        text = md.read_text(encoding="utf-8")
        assert "127.0.0.1:8765" in text
        assert "不修改" in text

    def test_build_hashes_existing_executable(self, tmp_path):
        import hashlib

        install = tmp_path / "install"
        install.mkdir()
        exe = install / "Sage.exe"
        exe.write_bytes(b"abc")
        data = al.build_allowlist(install_dir=install, user_data_dir=tmp_path)
        assert data["executables"]
        assert data["executables"][0]["sha256"] == hashlib.sha256(b"abc").hexdigest()
