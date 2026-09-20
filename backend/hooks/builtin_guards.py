"""内置安全钩子处理函数 (Phase 1)。

两个 pre_tool_use 检查器:

- ``security_guard`` — 拦截危险 Shell 命令 (rm -rf /, sudo, curl|sh 等)
- ``sensitive_data_guard`` — 拦截写入含密钥/密码/token 的内容

协议: 每个处理函数接收 payload dict + config dict, 返回 decision dict。
所有异常 fail-open (返回 allow + warning)。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _extract_command(payload: Dict[str, Any]) -> str:
    """从 payload 中提取待执行的命令字符串 (bash 工具)。"""
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command", "")
        if isinstance(cmd, str):
            return cmd
    return ""


def _extract_file_contents(payload: Dict[str, Any]) -> List[str]:
    """从 payload 中提取所有"将被写入文件"的文本片段。

    覆盖三种写文件工具的实际 schema:

    - ``write_file``: ``{"path": ..., "content": ...}``
    - ``edit_file``:  ``{"file_path": ..., "new_string": ...}``
    - ``apply_patch``: ``{"patches": [{"file_path", "old_string", "new_string"}, ...]}``

    返回列表 (apply_patch 可含多处方补丁); 无内容时返回空列表。
    """
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return []

    chunks: List[str] = []

    content = tool_input.get("content")
    if isinstance(content, str) and content:
        chunks.append(content)

    new_string = tool_input.get("new_string")
    if isinstance(new_string, str) and new_string:
        chunks.append(new_string)

    patches = tool_input.get("patches")
    if isinstance(patches, list):
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            patch_new = patch.get("new_string")
            if isinstance(patch_new, str) and patch_new:
                chunks.append(patch_new)

    return chunks


# ── security_guard ───────────────────────────────────────────────────

async def security_guard(
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """检查 Shell 命令是否匹配危险模式。

    config keys:
        blocklist: list[str] — 精确/子串匹配的命令黑名单
        require_confirm: list[str] — 出现时 warn 但不阻断的命令前缀
    """
    try:
        cmd = _extract_command(payload)
        if not cmd:
            return {"decision": "allow"}

        cmd_lower = cmd.lower().strip()
        blocklist = config.get("blocklist", [])

        for pattern in blocklist:
            if isinstance(pattern, str) and pattern.lower() in cmd_lower:
                return {
                    "decision": "deny",
                    "reason": f"安全守卫拦截: 命令匹配黑名单 [{pattern}]",
                }

        # 管道到 shell 的危险模式: curl ... | sh, wget ... | bash
        pipe_shell_patterns = [
            r"\|\s*sh\b",
            r"\|\s*bash\b",
            r"\|\s*zsh\b",
            r"\|\s*python[3]?\b",
        ]
        for pat in pipe_shell_patterns:
            if re.search(pat, cmd, re.IGNORECASE):
                return {
                    "decision": "deny",
                    "reason": f"安全守卫拦截: 管道到 shell 解释器 ({pat.strip()})",
                }

        return {"decision": "allow"}

    except Exception as exc:
        logger.warning("hooks: security_guard failed (fail-open): %s", exc)
        return {"decision": "allow", "reason": f"security_guard error: {exc}"}


# ── sensitive_data_guard ─────────────────────────────────────────────

async def sensitive_data_guard(
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """检查待写入内容是否包含敏感凭据模式。

    config keys:
        patterns: list[str] — 正则表达式列表
    """
    try:
        contents = _extract_file_contents(payload)
        if not contents:
            return {"decision": "allow"}

        patterns = config.get("patterns", [])
        for content in contents:
            for pat_str in patterns:
                if not isinstance(pat_str, str):
                    continue
                try:
                    match = re.search(pat_str, content)
                    if match:
                        # 脱敏: 只暴露匹配片段的前 8 字符, 防止泄漏完整密钥
                        matched_text = match.group(0)
                        safe_preview = matched_text[:8] + "..." if len(matched_text) > 8 else matched_text
                        return {
                            "decision": "deny",
                            "reason": f"敏感信息拦截: 检测到疑似凭据 ({safe_preview})",
                        }
                except re.error as re_exc:
                    logger.warning("hooks: sensitive_data_guard bad regex %r: %s", pat_str, re_exc)
                    continue

        return {"decision": "allow"}

    except Exception as exc:
        logger.warning("hooks: sensitive_data_guard failed (fail-open): %s", exc)
        return {"decision": "allow", "reason": f"sensitive_data_guard error: {exc}"}
