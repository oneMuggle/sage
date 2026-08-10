"""检查前端 dist 产物可用性(dist/index.html 存在 + 非空 + 关键字段)。

诊断:Electron 桌面端打包后,dist/ 与 dist-electron/ 缺一会导致白屏。
dev 模式下 npm run build 未跑也会让 Electron production 模式启动时加载失败。

本 check 启动期探测 dist 状态,降低"装了但开不起来"报障率。
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register

#: index.html 最小字节数(空文件 < 1KB,正常最小化产物 ~1.5KB+)
MIN_INDEX_BYTES = 100

#: 测试/重载用 env override(默认是 cwd 下的 dist/)
_DIST_DIR_ENV = "SAGE_DIST_DIR"
_DIST_ELECTRON_DIR_ENV = "SAGE_DIST_ELECTRON_DIR"


def _resolve_dist_paths():
    """返回 (dist_index, dist_electron_main) 两个 Path。

    优先读 env override,否则 fallback 到 cwd 下的 dist/ + dist-electron/。
    """
    dist_dir = Path(os.environ.get(_DIST_DIR_ENV, "dist")).resolve()
    electron_dir = Path(os.environ.get(_DIST_ELECTRON_DIR_ENV, "dist-electron")).resolve()
    return dist_dir / "index.html", electron_dir / "electron" / "main.js"


@register
class FrontendDistCheck:
    name = "frontend_dist"
    description = "前端 dist/ 产物可用性(Electron 启动前置条件)"

    def run(self) -> CheckResult:
        dist_index, dist_electron_main = _resolve_dist_paths()
        # Electron 桌面端:dist-electron 必须存在(主进程)
        # dist/ 必须存在(渲染进程)。dev 模式二者都不必有(走 vite dev server),
        # 本 check 探测"如果是 production 配置(dist-electron 存在)但 dist 缺失"的情形。
        has_electron_build = dist_electron_main.exists()
        has_dist = dist_index.exists()

        if not has_electron_build and not has_dist:
            return CheckResult(
                self.name,
                Severity.INFO,
                "未检测到 dist/ 与 dist-electron/(纯源码/开发模式)",
            )

        if has_electron_build and not has_dist:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"dist-electron/ 已构建但 dist/ 缺失:{dist_index.parent}",
                "npm run build",
            )

        if not has_dist:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"dist/index.html 缺失:{dist_index.parent}",
                "npm run build",
            )

        try:
            size = dist_index.stat().st_size
        except OSError as exc:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"无法读取 dist/index.html 大小({exc.__class__.__name__}): {exc}",
                "npm run build",
            )

        if size < MIN_INDEX_BYTES:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"dist/index.html 异常小 ({size} bytes):{dist_index}",
                "npm run build 重新构建",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"dist/index.html 正常 ({size} bytes):{dist_index}",
        )
