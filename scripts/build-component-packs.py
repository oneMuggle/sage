# ruff: noqa: T201
"""Build signed offline component packages (``.sagepkg``) from bundled assets.

The win7 full installer keeps shipping models on disk. This script additionally
produces standalone packs for the thin/repair path; both share the same
signature and safe-extraction rules used by ``backend.services.components``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _iter_payload(source_dir: Path) -> Iterable[Tuple[Path, str]]:
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(source_dir)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.name == ".DS_Store":
            continue
        yield path, relative.as_posix()


def _load_private_key(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _public_pem(private_key) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def build_pack(
    *,
    component_id: str,
    name: str,
    version: str,
    source_dir: Path,
    payload_prefix: str,
    output_dir: Path,
    private_key_path: Path,
    branch: str,
    python_version: str,
    arch: str = "x64",
    description: str = "",
) -> Path:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"源目录不存在：{source_dir}")
    files: List[Dict[str, object]] = []
    payload: List[Tuple[Path, str]] = []
    for absolute, relative in _iter_payload(source_dir):
        installed_path = f"{payload_prefix.rstrip('/')}/{relative}"
        files.append(
            {
                "path": installed_path,
                "size": absolute.stat().st_size,
                "sha256": _sha256_file(absolute),
            }
        )
        payload.append((absolute, installed_path))

    manifest = {
        "schemaVersion": 1,
        "id": component_id,
        "name": name,
        "version": version,
        "branch": branch,
        "python": python_version,
        "arch": arch,
        "target": "user_data",
        "payloadDir": "payload",
        "files": files,
        "description": description,
        # timezone.utc keeps py3.8 support (datetime.UTC is 3.11+).
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # noqa: UP017
    }
    body = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    private_key = _load_private_key(private_key_path)
    signature = private_key.sign(body, padding.PKCS1v15(), hashes.SHA256())

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{component_id}-{version}-{branch}.sagepkg"
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        json_info = zipfile.ZipInfo("component.json", date_time=FIXED_ZIP_TIME)
        archive.writestr(json_info, body)
        signature_info = zipfile.ZipInfo("signature.bin", date_time=FIXED_ZIP_TIME)
        archive.writestr(signature_info, signature)
        for absolute, installed_path in payload:
            info = zipfile.ZipInfo(
                f"payload/{installed_path}",
                date_time=FIXED_ZIP_TIME,
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(info, "w") as target, absolute.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
    return output_path


def component_specs(
    models_dir: Path,
    *,
    version: str,
    branch: str,
    python_version: str,
    arch: str,
) -> List[Dict[str, object]]:
    return [
        {
            "component_id": "embedding-bge-small-zh",
            "name": "Embedding model (bge-small-zh-v1.5)",
            "version": version,
            "source_dir": models_dir / "bge-small-zh-v1.5",
            "payload_prefix": "models/bge-small-zh-v1.5",
            "branch": branch,
            "python_version": python_version,
            "arch": arch,
            "description": "本地语义嵌入模型（ONNX）",
        },
        {
            "component_id": "ocr-models-ppocr",
            "name": "OCR models (PP-OCRv6 tiny)",
            "version": version,
            "source_dir": models_dir / "rapidocr",
            "payload_prefix": "models/rapidocr",
            "branch": branch,
            "python_version": python_version,
            "arch": arch,
            "description": "RapidOCR det/rec 模型",
        },
    ]


def _write_index(
    output_dir: Path,
    built: Sequence[Tuple[Dict[str, object], Path]],
) -> Path:
    entries = []
    for spec, package_path in built:
        entries.append(
            {
                "id": spec["component_id"],
                "name": spec["name"],
                "version": spec["version"],
                "branch": spec["branch"],
                "python": spec["python_version"],
                "arch": spec["arch"],
                "file": package_path.name,
                "size": package_path.stat().st_size,
                "sha256": _sha256_file(package_path),
            }
        )
    index = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # noqa: UP017
        "packages": entries,
    }
    index_path = output_dir / "components-index.json"
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return index_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Sage 离线组件包（.sagepkg）")
    parser.add_argument("--all", action="store_true", help="构建全部内置组件")
    parser.add_argument("--models-dir", default="resources/models")
    parser.add_argument("--output", default="release/components")
    parser.add_argument(
        "--key",
        default=os.environ.get("SAGE_COMPONENT_SIGNING_KEY_PATH", ""),
        help="RSA 私钥 PEM 路径（也可用 SAGE_COMPONENT_SIGNING_KEY_PATH）",
    )
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--branch", default="win7")
    parser.add_argument("--python", default="3.8", dest="python_version")
    parser.add_argument("--arch", default="x64")
    parser.add_argument("--print-public-key", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    if not args.key:
        print("错误: 未提供 --key 或 SAGE_COMPONENT_SIGNING_KEY_PATH")
        return 1
    private_key_path = Path(args.key)
    if not private_key_path.is_file():
        print(f"错误: 私钥不存在：{private_key_path}")
        return 1

    if args.print_public_key:
        sys.stdout.write(_public_pem(_load_private_key(private_key_path)).decode("ascii"))
        return 0

    if not args.all:
        parser.print_help()
        return 2

    models_dir = Path(args.models_dir)
    output_dir = Path(args.output)
    specs = component_specs(
        models_dir,
        version=args.version,
        branch=args.branch,
        python_version=args.python_version,
        arch=args.arch,
    )
    built: List[Tuple[Dict[str, object], Path]] = []
    try:
        for spec in specs:
            package_path = build_pack(
                component_id=str(spec["component_id"]),
                name=str(spec["name"]),
                version=str(spec["version"]),
                source_dir=Path(spec["source_dir"]),
                payload_prefix=str(spec["payload_prefix"]),
                output_dir=output_dir,
                private_key_path=private_key_path,
                branch=str(spec["branch"]),
                python_version=str(spec["python_version"]),
                arch=str(spec["arch"]),
                description=str(spec["description"]),
            )
            built.append((spec, package_path))
            print(f"✓ {package_path.name} ({package_path.stat().st_size} bytes)")
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误: {exc}")
        return 1

    index_path = _write_index(output_dir, built)
    print(f"✓ {index_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
