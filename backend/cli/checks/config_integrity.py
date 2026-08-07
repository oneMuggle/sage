"""检查 ~/.sage/config/*.json 配置文件的 JSON 合法性和必填字段。"""
from __future__ import annotations

import json

from backend.cli.checks.sqlite_writable import _resolve_user_data_dir
from backend.cli.doctor import CheckResult, Severity, register

REQUIRED_FIELDS = ("version",)


@register
class ConfigIntegrityCheck:
    name = "config_integrity"
    description = "用户数据目录 config/*.json 校验"

    def run(self) -> CheckResult:
        config_dir = _resolve_user_data_dir() / "config"
        if not config_dir.exists():
            return CheckResult(
                self.name,
                Severity.INFO,
                "尚无配置文件（首次安装）",
            )

        files = sorted(config_dir.glob("*.json"))
        if not files:
            return CheckResult(
                self.name,
                Severity.INFO,
                "尚无配置文件（首次安装）",
            )

        broken: list = []
        for f in files:
            try:
                with f.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                broken.append(f"{f.name}: {exc}")
                continue
            missing = [k for k in REQUIRED_FIELDS if k not in data]
            if missing:
                broken.append(f"{f.name}: 缺少必填字段 {missing}")

        if broken:
            joined = "; ".join(broken)
            return CheckResult(
                self.name,
                Severity.WARN,
                f"配置文件损坏或缺失必填字段: {joined}",
                "删除该文件，下次启动会重建",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"{len(files)} 个配置文件全部合法",
        )
