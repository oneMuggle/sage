"""内置钩子注册表 (Phase 1)。

每个内置钩子有一个唯一 ``builtin_id``, 描述元数据, 默认配置, 以及
指向处理函数的 dotted path。用户通过设置页 ``启用`` 按钮把内置钩子
写入 preferences, 运行时和自定义 shell 钩子混合执行。

注册表是只读字典, 不依赖任何外部状态。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 注册表 ──────────────────────────────────────────────────────────

BUILTIN_HOOKS: Dict[str, Dict[str, Any]] = {
    "security_guard": {
        "id": "security_guard",
        "name": "安全守卫",
        "description": "拦截危险 Shell 命令 (rm -rf /、sudo、curl|sh 等)",
        "icon": "shield",
        "event": "pre_tool_use",
        "matcher": "bash",
        "handler": "backend.hooks.builtin_guards.security_guard",
        "default_config": {
            "blocklist": [
                "rm -rf /",
                "rm -rf /*",
                "sudo rm",
                "mkfs",
                "dd if=",
                ":(){:|:&};:",
            ],
            "require_confirm": [
                "curl",
                "wget",
                "ssh",
                "scp",
            ],
        },
    },
    "sensitive_data_guard": {
        "id": "sensitive_data_guard",
        "name": "敏感信息拦截",
        "description": "阻止写入含 API key、密码、token 的文件",
        "icon": "lock",
        "event": "pre_tool_use",
        "matcher": "write_file|edit_file|apply_patch",
        "handler": "backend.hooks.builtin_guards.sensitive_data_guard",
        "default_config": {
            "patterns": [
                r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][\w-]{16,}",
                r"AKIA[0-9A-Z]{16}",
                r"ghp_[0-9a-zA-Z]{36}",
                r"sk-[0-9a-zA-Z]{32,}",
            ],
        },
    },
    "audit_log": {
        "id": "audit_log",
        "name": "操作审计日志",
        "description": "记录所有工具调用到审计日志文件 (~/.sage/audit.jsonl)",
        "icon": "file-text",
        "event": "post_tool_use",
        "matcher": "*",
        "handler": "backend.hooks.builtin_audit.audit_logger",
        "default_config": {
            "max_size_mb": 50,
        },
    },
    "cost_alert": {
        "id": "cost_alert",
        "name": "成本预警",
        "description": "单次会话 token 消耗超阈值时通知",
        "icon": "dollar-sign",
        "event": "stop",
        "matcher": "*",
        "handler": "backend.hooks.builtin_cost.cost_alert",
        "default_config": {
            "threshold_tokens": 100000,
        },
    },
}


def get_builtin(builtin_id: str) -> Optional[Dict[str, Any]]:
    """按 ID 取内置钩子元数据, 不存在返回 None。"""
    return BUILTIN_HOOKS.get(builtin_id)


def list_builtins() -> List[Dict[str, Any]]:
    """返回所有内置钩子元数据列表 (供前端渲染)。"""
    return list(BUILTIN_HOOKS.values())


def make_hook_entry(
    builtin_id: str,
    config_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从内置 ID 生成一条可存入 preferences 的 hook JSON 条目。"""
    meta = BUILTIN_HOOKS.get(builtin_id)
    if meta is None:
        raise KeyError(f"unknown builtin hook: {builtin_id!r}")
    entry: Dict[str, Any] = {
        "event": meta["event"],
        "matcher": meta["matcher"],
        "command": "",
        "hook_type": "python",
        "handler": meta["handler"],
        "builtin_id": meta["id"],
        "timeout_seconds": 10,
    }
    if config_override:
        entry["config"] = config_override
    return entry
