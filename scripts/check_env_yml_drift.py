#!/usr/bin/env python
"""Check that backend/environment.yml pip pins don't drift from requirements.txt.

The conda environment file exists for developer convenience, but its `pip:`
section duplicates pins from backend/requirements.txt. When the two disagree,
developers get a different (potentially vulnerable — e.g. python-multipart
0.0.9 vs the PYSEC-fixed 0.0.32) dependency set than CI validates.

Rules:
- A package pinned in BOTH files must have the exact same version.
- Packages only in environment.yml (dev tooling) are ignored.
- Packages only in requirements.txt are ignored (environment.yml is a subset).

Stdlib-only; wired into the `dependency-audit` CI job.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "backend" / "requirements.txt"
ENV = ROOT / "backend" / "environment.yml"

PIN_RE = re.compile(r"^\s*-?\s*([A-Za-z0-9_.\-\[\]]+)==([^#\s]+)")


def parse_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        m = PIN_RE.match(line)
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


def main() -> int:
    req = parse_pins(REQ)
    env = parse_pins(ENV)

    drift = sorted(
        (name, env[name], req[name]) for name in env if name in req and env[name] != req[name]
    )
    if not drift:
        print(f"OK: {len(env)} environment.yml pip pins agree with requirements.txt")
        return 0

    for name, env_ver, req_ver in drift:
        print(
            f"::error::dependency drift: {name} environment.yml=={env_ver} "
            f"but requirements.txt=={req_ver}"
        )
    print(
        f"\n{len(drift)} drifted pin(s). environment.yml 是 conda 开发环境的便捷入口，"
        "与 requirements.txt 重叠的钉版必须逐字一致。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
