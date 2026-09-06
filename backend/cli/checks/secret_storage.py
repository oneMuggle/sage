"""Doctor check — API Key 静态加密状态（L15 SecretBox）。

汇报当前 scheme 与 endpoints[*].apiKey 的加密覆盖情况:
- scheme=none(平台无可用加密后端)且存在已配置 key → WARN(明文落库)
- 存在未迁移明文且 scheme 可用 → WARN(提示重启触发迁移或检查迁移日志)
- 其余 → INFO(scheme + 覆盖计数)

fail-open: 直接以只读方式扫 preferences 表, DB 未就绪/为空时报 INFO,
不让 doctor 在冷启动早期阻塞。
"""
from __future__ import annotations

from backend.cli.checks.llm_config import _load_app_settings_json, _resolve_db_path
from backend.cli.doctor import CheckResult, Severity, register
from backend.services.secret_box import _secret_stats, current_scheme, is_wrapped


@register
class SecretStorageCheck:
    name = "secret_storage"
    description = "API Key 静态加密状态(SecretBox)"

    def run(self) -> CheckResult:
        scheme = current_scheme()
        app_settings = _load_app_settings_json(_resolve_db_path())
        if app_settings is None:
            return CheckResult(self.name, Severity.INFO, "尚未配置 LLM endpoint(无加密需求)")

        stats = _secret_stats(app_settings)
        if stats["total"] == 0:
            return CheckResult(self.name, Severity.INFO, f"加密 scheme={scheme}, 暂无已配置 apiKey")

        if scheme == "none":
            return CheckResult(
                self.name,
                Severity.WARN,
                f"当前平台无可用加密后端, {stats['total']} 个 apiKey 以明文落库",
                "Windows 使用 DPAPI; macOS 需 security CLI; Linux 需 secret-tool(libsecret)",
            )
        if stats["plaintext"]:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{stats['plaintext']}/{stats['total']} 个 apiKey 仍是明文(scheme={scheme})",
                "重启后端触发自动迁移; 若持续出现请查看 SecretBox 迁移日志",
            )
        return CheckResult(
            self.name,
            Severity.INFO,
            f"{stats['wrapped']}/{stats['total']} 个 apiKey 已加密落库(scheme={scheme})",
        )


# 供 doctor 汇总断言使用(如 e2e 检查密文形态)
__all__ = ["SecretStorageCheck", "is_wrapped"]
