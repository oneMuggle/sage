"""检查 SQLite preferences 表中 app_settings 至少配置了 1 个可用 LLM endpoint。

诊断:用户没配 apiKey 时,后续 chat 调用会静默失败,排查链长且报障最频繁。
本 check 提前在启动期发现"没配"或"全空 key"的情形,降低报障率。

fail-open:本 check 仅作 INFO/WARN,不会因为读不到 DB 报 CRITICAL
(避免 doctor 在冷启动早期就阻塞用户)。
"""
from __future__ import annotations

import json

from backend.cli.checks.sqlite_writable import _resolve_user_data_dir
from backend.cli.doctor import CheckResult, Severity, register

#: preferences 表的 app_settings 行
_APP_SETTINGS_KEY = "app_settings"


def _resolve_db_path():
    """解析 SQLite DB 路径,模仿 backend.data.database 的查找策略。

    不直接 import backend.data.database 以避免 doctor 自身对 DB schema 的
    强依赖(冷启动时 DB 还未创建,import 应当是惰性的)。

    实际 production 路径: <user_data_dir>/sage.db
    测试环境: 通常 tmp_path/sage.db
    """
    return _resolve_user_data_dir() / "sage.db"


def _load_app_settings_json(db_path):
    """读 preferences 表,返回 app_settings 的 JSON dict,或 None(行不存在/JSON 坏/DB 不可读)。"""
    if not db_path.exists():
        return None
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    except sqlite3.OperationalError:
        return None
    try:
        row = conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (_APP_SETTINGS_KEY,),
        ).fetchone()
    except sqlite3.OperationalError:
        # schema 还没建好(no such table: preferences)
        return None
    finally:
        conn.close()

    if row is None:
        return None
    raw = row[0]
    if not isinstance(raw, str) or not raw:
        return None
    try:
        result = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _iter_endpoints(app_settings):
    """yield 每个 endpoint dict,兼容嵌套 llm.endpoints 与扁平 endpoints。"""
    if not app_settings:
        return
    # 候选 1: 嵌套结构 {"llm": {"endpoints": [...]}}
    llm_section = app_settings.get("llm")
    if isinstance(llm_section, dict):
        nested = llm_section.get("endpoints")
        if isinstance(nested, list):
            for ep in nested:
                if isinstance(ep, dict):
                    yield ep
            return
    # 候选 2: 扁平结构 {"endpoints": [...]} (legacy / hex 路径)
    flat = app_settings.get("endpoints")
    if isinstance(flat, list):
        for ep in flat:
            if isinstance(ep, dict):
                yield ep


@register
class LlmConfigCheck:
    name = "llm_config"
    description = "LLM endpoint 配置(至少 1 个非空 apiKey)"

    def run(self) -> CheckResult:
        db_path = _resolve_db_path()
        app_settings = _load_app_settings_json(db_path)
        if app_settings is None:
            return CheckResult(
                self.name,
                Severity.INFO,
                "尚未配置 LLM endpoint(首次安装或 DB 未就绪)",
            )

        endpoints = list(_iter_endpoints(app_settings))
        if not endpoints:
            return CheckResult(
                self.name,
                Severity.WARN,
                "app_settings 中未发现 endpoints 列表",
                "在设置页或 init wizard 至少添加 1 个 LLM provider",
            )

        empty_key = [ep for ep in endpoints if not (ep.get("apiKey") or "").strip()]
        if len(empty_key) == len(endpoints):
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{len(endpoints)} 个 endpoint 全部未配置 apiKey",
                "设置页填入有效的 apiKey 后再启动 chat",
            )

        if empty_key:
            return CheckResult(
                self.name,
                Severity.INFO,
                f"{len(endpoints) - len(empty_key)}/{len(endpoints)} 个 endpoint 已配置 apiKey",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"{len(endpoints)} 个 endpoint 全部已配置 apiKey",
        )
