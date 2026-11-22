"""Unit tests for signed offline component packages."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.services.components.archive import stage_payload
from backend.services.components.crypto import load_public_key, verify_signature
from backend.services.components.errors import ComponentError
from backend.services.components.models import ComponentManifest
from backend.services.components.service import ComponentService


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, public_pem


def _manifest(
    payload,
    *,
    component_id="demo",
    target="user_data",
    version="1.0.0",
    python_version="3.8",
    arch="x64",
    branch="win7",
):
    files = [
        {
            "path": path,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for path, data in payload.items()
    ]
    return {
        "schemaVersion": 1,
        "id": component_id,
        "name": component_id,
        "version": version,
        "branch": branch,
        "python": python_version,
        "arch": arch,
        "target": target,
        "payloadDir": "payload",
        "files": files,
    }


def _build_pack(path: Path, key, manifest, payload, *, sign=True):
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    signature = key.sign(body, padding.PKCS1v15(), hashes.SHA256()) if sign else b""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("component.json", body)
        archive.writestr("signature.bin", signature)
        for relative, data in payload.items():
            archive.writestr("payload/" + relative, data)
    return path


def _service(tmp_path: Path, public_pem: bytes) -> ComponentService:
    public_path = tmp_path / "public.pem"
    public_path.write_bytes(public_pem)
    return ComponentService(
        user_data_dir=tmp_path / "userdata",
        resources_dir=tmp_path,
        environ={"SAGE_COMPONENT_PUBLIC_KEY_PATH": str(public_path)},
    )


def test_manifest_parses_and_rejects_traversal():
    manifest = ComponentManifest.from_dict(
        {
            "schemaVersion": 1,
            "id": "embedding-bge-small-zh",
            "name": "Embedding",
            "version": "1.0.0",
            "branch": "win7",
            "python": "3.8",
            "arch": "x64",
            "target": "user_data",
            "payloadDir": "payload",
            "files": [
                {
                    "path": "models/bge-small-zh-v1.5/model.onnx",
                    "size": 10,
                    "sha256": "a" * 64,
                }
            ],
        }
    )
    assert manifest.id == "embedding-bge-small-zh"
    assert manifest.files[0].path.startswith("models/")

    bad = manifest.to_dict()
    bad["files"] = [{"path": "../sage.db", "size": 1, "sha256": "a" * 64}]
    with pytest.raises(ValueError, match="路径"):
        ComponentManifest.from_dict(bad)


def test_manifest_rejects_user_data_outside_models():
    with pytest.raises(ValueError, match="user_data"):
        ComponentManifest.from_dict(
            {
                "schemaVersion": 1,
                "id": "demo",
                "name": "Demo",
                "version": "1.0.0",
                "branch": "win7",
                "python": "3.8",
                "arch": "x64",
                "target": "user_data",
                "payloadDir": "payload",
                "files": [{"path": "sage.db", "size": 1, "sha256": "a" * 64}],
            }
        )


def test_signature_roundtrip_and_tamper():
    key, public_pem = _keypair()
    payload = b'{"id":"x"}'
    signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    public_key = load_public_key(public_pem)
    assert verify_signature(public_key, payload, signature) is True
    assert verify_signature(public_key, payload + b" ", signature) is False


def test_stage_payload_verifies_hash_and_rejects_extra_file(tmp_path: Path):
    key, _public_pem = _keypair()
    payload = {"models/demo/a.bin": b"hello"}
    manifest_dict = _manifest(payload)
    manifest = ComponentManifest.from_dict(manifest_dict)
    good_pack = _build_pack(tmp_path / "good.sagepkg", key, manifest_dict, payload)
    stage_payload(good_pack, manifest, tmp_path / "stage")
    assert (tmp_path / "stage" / "models" / "demo" / "a.bin").read_bytes() == b"hello"

    extra_payload = dict(payload)
    extra_payload["models/demo/extra.bin"] = b"extra"
    extra_pack = _build_pack(tmp_path / "extra.sagepkg", key, manifest_dict, extra_payload)
    with pytest.raises(ComponentError) as excinfo:
        stage_payload(extra_pack, manifest, tmp_path / "stage-extra")
    assert excinfo.value.code == "unexpected_file"

    tampered_payload = {"models/demo/a.bin": b"HELLO"}
    tampered_pack = _build_pack(
        tmp_path / "tampered.sagepkg", key, manifest_dict, tampered_payload
    )
    with pytest.raises(ComponentError) as tamper_excinfo:
        stage_payload(tampered_pack, manifest, tmp_path / "stage-tampered")
    assert tamper_excinfo.value.code == "hash_mismatch"


def test_install_and_remove_user_data_component(tmp_path: Path):
    key, public_pem = _keypair()
    payload = {"models/demo/model.bin": b"model-bytes"}
    manifest = _manifest(payload, component_id="embedding-demo")
    pack = _build_pack(tmp_path / "embedding.sagepkg", key, manifest, payload)
    service = _service(tmp_path, public_pem)

    installed = service.install(pack)
    assert installed.id == "embedding-demo"
    assert installed.version == "1.0.0"
    assert installed.signature_verified is True
    assert (
        tmp_path / "userdata" / "models" / "demo" / "model.bin"
    ).read_bytes() == b"model-bytes"
    assert service.list_installed()[0].id == "embedding-demo"
    metadata = json.loads(
        (tmp_path / "userdata" / "components" / "installed.json").read_text(encoding="utf-8")
    )
    assert metadata["components"]["embedding-demo"]["installedAt"].endswith("Z")

    assert service.remove("embedding-demo") is True
    assert not (tmp_path / "userdata" / "models" / "demo" / "model.bin").exists()
    assert service.list_installed() == []


def test_component_dir_target(tmp_path: Path):
    key, public_pem = _keypair()
    payload = {"bin/tool.bin": b"tool"}
    manifest = _manifest(payload, component_id="tool", target="component_dir")
    pack = _build_pack(tmp_path / "tool.sagepkg", key, manifest, payload)
    service = _service(tmp_path, public_pem)

    service.install(pack)
    assert (
        tmp_path / "userdata" / "components" / "tool" / "1.0.0" / "bin" / "tool.bin"
    ).read_bytes() == b"tool"
    service.remove("tool")
    assert not (tmp_path / "userdata" / "components" / "tool" / "1.0.0").exists()


def test_component_dir_same_version_reimport_keeps_new_files(tmp_path: Path):
    key, public_pem = _keypair()
    service = _service(tmp_path, public_pem)
    old_payload = {"bin/tool.bin": b"old"}
    old_pack = _build_pack(
        tmp_path / "old.sagepkg",
        key,
        _manifest(old_payload, component_id="tool", target="component_dir"),
        old_payload,
    )
    service.install(old_pack)
    new_payload = {"bin/tool.bin": b"new"}
    new_pack = _build_pack(
        tmp_path / "new.sagepkg",
        key,
        _manifest(new_payload, component_id="tool", target="component_dir"),
        new_payload,
    )
    service.install(new_pack)
    assert (
        tmp_path / "userdata" / "components" / "tool" / "1.0.0" / "bin" / "tool.bin"
    ).read_bytes() == b"new"


def test_user_data_public_key_is_not_a_trust_anchor(tmp_path: Path):
    from backend.services.components.crypto import resolve_public_key_pem

    user_data = tmp_path / "userdata"
    (user_data / "components").mkdir(parents=True)
    (user_data / "components" / "public-key.pem").write_bytes(b"attacker-key")
    assert (
        resolve_public_key_pem(
            environ={},
            user_data_dir=user_data,
            resources_dir=tmp_path,
        )
        is None
    )


def test_install_rejects_invalid_signature(tmp_path: Path):
    signing_key, _ = _keypair()
    _, trusted_public = _keypair()
    payload = {"models/demo/model.bin": b"model"}
    manifest = _manifest(payload)
    pack = _build_pack(tmp_path / "bad.sagepkg", signing_key, manifest, payload)
    service = _service(tmp_path, trusted_public)
    with pytest.raises(ComponentError) as excinfo:
        service.install(pack)
    assert excinfo.value.code == "signature_invalid"
    assert not (tmp_path / "userdata" / "models" / "demo" / "model.bin").exists()


def test_install_rejects_python_mismatch(tmp_path: Path):
    key, public_pem = _keypair()
    payload = {"models/demo/model.bin": b"model"}
    manifest = _manifest(payload, python_version="9.9")
    pack = _build_pack(tmp_path / "mismatch.sagepkg", key, manifest, payload)
    service = _service(tmp_path, public_pem)
    with pytest.raises(ComponentError) as excinfo:
        service.install(pack)
    assert excinfo.value.code == "python_mismatch"


def test_scan_finds_package(tmp_path: Path):
    key, public_pem = _keypair()
    payload = {"models/demo/model.bin": b"model"}
    manifest = _manifest(payload, component_id="scan-demo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pack = _build_pack(inbox / "scan.sagepkg", key, manifest, payload)
    service = _service(tmp_path, public_pem)
    results = service.scan([inbox])
    assert len(results) == 1
    assert results[0].id == "scan-demo"
    assert results[0].path == str(pack)


def test_reinstall_same_version_is_idempotent(tmp_path: Path):
    key, public_pem = _keypair()
    payload = {"models/demo/model.bin": b"model"}
    manifest = _manifest(payload)
    pack = _build_pack(tmp_path / "demo.sagepkg", key, manifest, payload)
    service = _service(tmp_path, public_pem)
    first = service.install(pack)
    second = service.install(pack)
    assert first.version == second.version
    assert len(service.list_installed()) == 1


def test_install_upgrade_removes_old_files(tmp_path: Path):
    key, public_pem = _keypair()
    service = _service(tmp_path, public_pem)
    payload_v1 = {"models/demo/a.bin": b"a"}
    pack_v1 = _build_pack(
        tmp_path / "v1.sagepkg", key, _manifest(payload_v1, version="1.0.0"), payload_v1
    )
    service.install(pack_v1)
    payload_v2 = {"models/demo/b.bin": b"b"}
    pack_v2 = _build_pack(
        tmp_path / "v2.sagepkg", key, _manifest(payload_v2, version="2.0.0"), payload_v2
    )
    service.install(pack_v2)
    assert not (tmp_path / "userdata" / "models" / "demo" / "a.bin").exists()
    assert (tmp_path / "userdata" / "models" / "demo" / "b.bin").read_bytes() == b"b"
    assert service.list_installed()[0].version == "2.0.0"


# ---------- _normalise_branch + compatibility branch tolerance ----------


def _compat_manifest(branch: str = "win7") -> ComponentManifest:
    return ComponentManifest.from_dict(
        _manifest(
            {"models/demo.bin": b"x"},
            branch=branch,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        )
    )


def _compat_service(tmp_path: Path, branch_env: str) -> ComponentService:
    return ComponentService(
        user_data_dir=tmp_path,
        environ={"SAGE_COMPONENT_BRANCH": branch_env},
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("win7", "win7"),
        ("WIN7", "win7"),
        ("release/win7", "win7"),
        ("feat/orch-win7", "win7"),
        ("v0.4.9-alpha.84-win7", "win7"),
        ("v0.4.9-alpha.84-win7  ", "win7"),
        ("main", "main"),
        ("master", "main"),
        ("v0.4.9-alpha.84", "main"),
        ("unknown", "unknown"),
        ("dev-build", "dev-build"),
    ],
)
def test_normalise_branch(value, expected):
    from backend.services.components.service import _normalise_branch

    assert _normalise_branch(value) == expected


def test_check_compatibility_accepts_tag_style_win7_branch(tmp_path: Path):
    """Packaged win7 builds set SAGE_COMPONENT_BRANCH to the git tag name.

    They must still accept packs whose manifest says branch='win7'.
    """
    svc = _compat_service(tmp_path, "v0.4.9-alpha.84-win7")
    svc._check_compatibility(_compat_manifest())  # no exception == pass


def test_check_compatibility_accepts_release_win7_ref(tmp_path: Path):
    """Any ref containing 'win7' maps to the win7 channel."""
    svc = _compat_service(tmp_path, "release/win7")
    svc._check_compatibility(_compat_manifest())


def test_check_compatibility_skips_unknown_and_dev_build(tmp_path: Path):
    """Dev builds without a packaged manifest have branch='unknown' — the
    check must be skipped so local imports work during development."""
    for branch_env in ("", "unknown", "dev-build"):
        svc = _compat_service(tmp_path, branch_env)
        svc._check_compatibility(_compat_manifest())  # no exception


def test_check_compatibility_rejects_cross_channel(tmp_path: Path):
    """A main-channel build must still refuse win7 packs."""
    svc = _compat_service(tmp_path, "v0.4.9-alpha.84")
    with pytest.raises(ComponentError, match="分支不匹配"):
        svc._check_compatibility(_compat_manifest())
