"""Integration test: build signed packs with the script, then install them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.services.components.service import ComponentService

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_keypair(tmp_path: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "private.pem"
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_build_component_packs_and_install(tmp_path: Path):
    private_key, public_key = _write_keypair(tmp_path)
    models = tmp_path / "models"
    (models / "bge-small-zh-v1.5").mkdir(parents=True)
    (models / "bge-small-zh-v1.5" / "model.onnx").write_bytes(b"onnx")
    (models / "rapidocr").mkdir()
    (models / "rapidocr" / "det.onnx").write_bytes(b"det")
    output = tmp_path / "components"

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build-component-packs.py"),
            "--all",
            "--models-dir",
            str(models),
            "--key",
            str(private_key),
            "--output",
            str(output),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    index = json.loads((output / "components-index.json").read_text(encoding="utf-8"))
    assert len(index["packages"]) == 2

    service = ComponentService(
        user_data_dir=tmp_path / "userdata",
        resources_dir=tmp_path,
        environ={"SAGE_COMPONENT_PUBLIC_KEY_PATH": str(public_key)},
    )
    installed = service.install(output / "embedding-bge-small-zh-1.0.0-win7.sagepkg")
    assert installed.id == "embedding-bge-small-zh"
    assert installed.signature_verified is True
    assert (
        tmp_path / "userdata" / "models" / "bge-small-zh-v1.5" / "model.onnx"
    ).read_bytes() == b"onnx"
