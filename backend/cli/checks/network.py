"""``network`` check —— 校验网络访问策略配置与 httpx 依赖。

场景:

- 未配置（默认 ONLINE）→ INFO
- 任意合法模式 + httpx 可用 → INFO
- INTRANET 模式但 allowed_hosts 为空 → WARN（白名单形同虚设）
- INTRANET 模式但 allowed_hosts 格式非法 → WARN（fail-safe 到 ONLINE）
- mode 非法 / JSON 解析失败 → WARN（fail-safe 到 ONLINE）
- httpx 未安装 → CRITICAL（web_fetch/http_download 不可用）

fail-safe 方向与 ``load_network_policy()`` 一致：配置读取/解析失败时不阻断
doctor 整体流程，但本 check 显式报 WARN，避免用户误以为"没配置就没问题"。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.cli.doctor import CheckResult, Severity, register
from backend.domain.network_policy import NetworkMode, NetworkPolicy

logger = logging.getLogger(__name__)


@register
class NetworkCheck:
    name = "network"
    description = "网络访问策略（mode / host 白名单 / httpx 依赖）"

    def run(self) -> CheckResult:
        """生产路径：从真实 SettingsRepository 读配置。"""
        try:
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                self.name,
                Severity.WARN,
                f"SettingsRepository 初始化失败: {exc}",
                "检查 backend/data/settings_repo.py 是否可正常 import",
            )
        return self.run_with_repo(repo)

    def run_with_repo(self, repo: Any) -> CheckResult:  # noqa: PLR0911 — 每个拒绝路径独立 return, 扁平比提取辅助函数更直读
        """可注入 repo 的入口（便于测试）。"""
        try:
            raw = repo.get("network_policy")
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                self.name,
                Severity.WARN,
                f"network_policy 读取失败: {exc}（已 fail-safe 到 online）",
                "检查 ~/.sage/preferences 表是否损坏；可清空后重启应用",
            )

        # 未配置（默认 ONLINE）—— 与 load_network_policy() 口径一致
        if not raw:
            return self._check_httpx(NetworkMode.ONLINE, mode_desc="online（默认，未配置）")

        # JSON 解析
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return CheckResult(
                self.name,
                Severity.WARN,
                "network_policy JSON 解析失败（已 fail-safe 到 online）",
                "在 Settings → Network 中重新选择网络模式",
            )

        if not isinstance(parsed, dict):
            return CheckResult(
                self.name,
                Severity.WARN,
                "network_policy 不是 JSON 对象（已 fail-safe 到 online）",
                "在 Settings → Network 中重新选择网络模式",
            )

        # mode 合法性
        mode_raw = parsed.get("mode")
        if mode_raw is not None:
            try:
                mode = NetworkMode(mode_raw)
            except ValueError:
                return CheckResult(
                    self.name,
                    Severity.WARN,
                    f"network_policy.mode 非法: {mode_raw!r}（已 fail-safe 到 online）",
                    "在 Settings → Network 中选择 online / intranet / offline",
                )
        else:
            mode = NetworkMode.ONLINE

        # INTRANET 模式下校验 allowed_hosts
        if mode is NetworkMode.INTRANET:
            hosts = parsed.get("allowed_hosts")
            if not hosts:
                return CheckResult(
                    self.name,
                    Severity.WARN,
                    "intranet 模式但 allowed_hosts 为空（白名单形同虚设，"
                    "实际行为与 offline 无差异）",
                    "在 Settings → Network 的'允许的主机'中添加至少一个 host",
                )
            # 校验 host 条目格式（通配合法性、apex 至少两段等）
            try:
                NetworkPolicy.from_config(parsed)
            except (ValueError, TypeError) as exc:
                return CheckResult(
                    self.name,
                    Severity.WARN,
                    f"intranet 白名单格式非法: {exc}（已 fail-safe 到 online）",
                    "在 Settings → Network 中修正 host 条目（通配只支持 *.example.com 形式）",
                )

        return self._check_httpx(mode, mode_desc=mode.value)

    def _check_httpx(self, mode: NetworkMode, mode_desc: str) -> CheckResult:
        """最后一步：校验 httpx 是否可导入。"""
        try:
            import httpx  # noqa: F401
        except ImportError:
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"mode={mode_desc}，但 httpx 未安装（web_fetch / http_download 不可用）",
                "conda activate sage-backend && pip install httpx",
            )

        if mode is NetworkMode.OFFLINE:
            return CheckResult(
                self.name,
                Severity.INFO,
                f"mode={mode_desc}（气隙模式，三个出网工具全部不注册）",
            )
        if mode is NetworkMode.INTRANET:
            return CheckResult(
                self.name,
                Severity.INFO,
                f"mode={mode_desc}（web_fetch / http_download 仅允许白名单内 host）",
            )
        return CheckResult(
            self.name,
            Severity.INFO,
            f"mode={mode_desc}（web_fetch / http_download / web_search 均已注册）",
        )
