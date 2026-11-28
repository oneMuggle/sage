#!/usr/bin/env python3
"""中间页解析脚本（用户级技能模板）。

职责**限于确定性、无副作用判断**的动作：读中间页 HTML、提取 downurl、
按 fallback 规则生成候选 URL。**不做**：决定是否下载（合规判断须留在
agent 侧）、登录、限速豁免（spec §7.2）。

用法::

    python parse_interstitial.py --html intermediate.html \\
        --fallback kns.cnki.net --fallback oversea.cnki.net

输出 JSON::

    {"candidates": ["https://.../a", "https://.../b"]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

#: 仓库根 —— 供「从仓库内 import 公共模块」的路径兜底。
SAGE_REPO_ROOT = "/home/fz/project/sage"


def _load_interstitial_module():
    """尽量复用仓库内的 interstitial 模块；不可用时退回本地实现。"""
    root = Path(SAGE_REPO_ROOT)
    if (root / "backend" / "literature" / "interstitial.py").is_file():
        sys.path.insert(0, str(root))
        try:
            from backend.literature.interstitial import (  # type: ignore[import-not-found]
                parse_download_url,
                rewrite_host_candidates,
            )

            return parse_download_url, rewrite_host_candidates
        except ImportError:
            pass

    import re
    from urllib.parse import urlsplit, urlunsplit

    pattern = re.compile(r"var\s+downurl\s*=\s*['\"]([^'\"]+)['\"]")

    def parse_download_url(html: str) -> List[str]:
        return [match.group(1).strip() for match in pattern.finditer(html or "")]

    def rewrite_host_candidates(url: str, fallbacks) -> List[str]:
        parts = urlsplit(url)
        candidates = [
            urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
            for host in (fallbacks or ())
        ]
        candidates.append(url)
        return candidates

    return parse_download_url, rewrite_host_candidates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="解析中间页并生成候选下载地址")
    parser.add_argument("--html", required=True, help="中间页 HTML 文件路径")
    parser.add_argument("--fallback", action="append", default=[], help="主机回退（可重复）")
    args = parser.parse_args(argv)

    html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    parse_download_url, rewrite_host_candidates = _load_interstitial_module()
    urls = parse_download_url(html)

    candidates: List[str] = []
    for url in urls:
        for candidate in rewrite_host_candidates(url, args.fallback):
            if candidate not in candidates:
                candidates.append(candidate)

    print(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
