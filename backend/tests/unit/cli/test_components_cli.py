"""CLI tests for ``backend.cli.components`` and the rescue entry point."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.cli import components as cli, rescue


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, public_pem


def _build_pack(tmp_path: Path, key, payload):
    manifest = {
        "schemaVersion": 1,
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "branch": "win7",
        "python": "3.8",
        "arch": "x64",
        "target": "user_data",
        "payloadDir": "payload",
        "files": [
            {
                "path": path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for path, data in payload.items()
        ],
    }
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    signature = key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    pack = tmp_path / "demo.sagepkg"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("component.json", body)
        archive.writestr("signature.bin", signature)
        for relative, data in payload.items():
            archive.writestr("payload/" + relative, data)
    return pack


def _parse_lines(output: str):
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def test_cli_parser_has_all_actions():
    parser = cli.build_parser()
    for argv in (
        ["list"],
        ["scan"],
        ["verify", "x.sagepkg"],
        ["import", "x.sagepkg"],
        ["remove", "demo"],
    ):
        assert parser.parse_args(argv).action == argv[0]


def test_rescue_parser_exposes_components_subcommand():
    namespace = rescue.build_parser().parse_args(["components", "list"])
    assert namespace.command == "components"
    assert namespace.action == "list"


def test_cli_json_error_is_machine_readable(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    rc = cli.main(["verify", str(tmp_path / "missing.sagepkg"), "--json"])
    assert rc == 2
    lines = _parse_lines(capsys.readouterr().out)
    assert lines[-1]["event"] == "result"
    assert lines[-1]["ok"] is False
    assert "不存在" in lines[-1]["error"]


def test_cli_import_then_list_and_remove(tmp_path, capsys, monkeypatch):
    key, public_pem = _keypair()
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(public_pem)
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setenv("SAGE_RESOURCES_DIR", str(tmp_path))
    monkeypatch.setenv("SAGE_COMPONENT_PUBLIC_KEY_PATH", str(public_path))
    pack = _build_pack(tmp_path, key, {"models/demo/model.bin": b"model"})

    rc = cli.main(["import", str(pack), "--json", "--yes"])
    assert rc == 0
    events = _parse_lines(capsys.readouterr().out)
    assert events[-1]["event"] == "result"
    assert events[-1]["ok"] is True
    assert events[-1]["component"]["id"] == "demo"
    assert (tmp_path / "userdata" / "models" / "demo" / "model.bin").is_file()

    rc = cli.main(["list", "--json"])
    assert rc == 0
    listing = _parse_lines(capsys.readouterr().out)[-1]
    assert listing["installed"][0]["id"] == "demo"

    rc = cli.main(["remove", "demo", "--json", "--yes"])
    assert rc == 0
    removed = _parse_lines(capsys.readouterr().out)[-1]
    assert removed["ok"] is True
    assert removed["componentId"] == "demo"
    assert not (tmp_path / "userdata" / "models" / "demo" / "model.bin").exists()


def test_cli_remove_unknown_component_returns_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path / "userdata"))
    rc = cli.main(["remove", "missing", "--json", "--yes"])
    assert rc == 2
    result = _parse_lines(capsys.readouterr().out)[-1]
    assert result["ok"] is False
    assert result["code"] == "not_installed"
