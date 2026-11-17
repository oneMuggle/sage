# ruff: noqa: T201
"""Generate an RSA key pair for signing ``.sagepkg`` component packs.

The private key stays in ``.secrets/`` (gitignored). The public key is written
to ``resources/component-public-key.pem`` so the packaged app can verify packs.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEFAULT_PRIVATE_DIR = ".secrets"
DEFAULT_PUBLIC_PATH = "resources/component-public-key.pem"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 Sage 组件包签名密钥对")
    parser.add_argument("--out-dir", default=DEFAULT_PRIVATE_DIR, help="私钥输出目录")
    parser.add_argument("--public-out", default=DEFAULT_PUBLIC_PATH, help="公钥输出路径")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有密钥")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    out_dir = Path(args.out_dir)
    private_path = out_dir / "component-private-key.pem"
    public_path = Path(args.public_out)
    if private_path.exists() and not args.overwrite:
        print(f"错误: 私钥已存在：{private_path}（如需替换请加 --overwrite）")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_bytes)
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_bytes(public_bytes)

    print(f"私钥：{private_path}（勿入库）")
    print(f"公钥：{public_path}（可入库）")
    print("请将私钥内容保存到 CI secret SAGE_COMPONENT_SIGNING_KEY。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
