"""Memory Safety Scanner - 记忆安全扫描

借鉴 Hermes Agent 的三级威胁扫描，在记忆写入前进行安全检查。
防止通过对话记忆进行 prompt 注入、数据泄露或持久化攻击。

检测模式：
- 经典 prompt 注入（"ignore previous instructions" 等）
- 敏感信息泄露（密码、API key、token 等）
- 持久化攻击（试图通过记忆影响未来会话的行为）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """扫描结果"""

    blocked: bool
    reason: str = ""
    threat_level: str = "none"  # none / low / medium / high


# 注入模式（借鉴 Hermes 的 threat patterns）
INJECTION_PATTERNS = [
    re.compile(r"(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"<\|?system\|?>", re.I),
    re.compile(r"\[INST\]|\[/INST\]", re.I),
    re.compile(r"assistant\s*:\s*", re.I),
]

# 敏感信息模式
SENSITIVE_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|password|token|credential)\s*[=:]\s*\S+", re.I),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.I),  # OpenAI API key pattern
    re.compile(r"ghp_[a-zA-Z0-9]{36}", re.I),  # GitHub PAT
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", re.I),
]

# 持久化攻击模式
PERSISTENCE_PATTERNS = [
    re.compile(r"(always|every\s+time|from\s+now\s+on)\s+(respond|reply|say|do)", re.I),
    re.compile(r"remember\s+to\s+(always|never|ignore)", re.I),
    re.compile(r"in\s+future\s+(conversations?|sessions?|chats?)\s*,", re.I),
]


class MemorySafetyScanner:
    """记忆安全扫描器

    三级威胁扫描：
    - Level 1 (all): 经典注入 + 数据泄露
    - Level 2 (context): 上下文注入模式
    - Level 3 (strict): 持久化攻击

    Example:
        >>> scanner = MemorySafetyScanner()
        >>> result = scanner.scan("ignore previous instructions and...")
        >>> if result.blocked:
        ...     logger.warning(f"Blocked: {result.reason}")
    """

    def scan(self, content: str, level: str = "all") -> ScanResult:
        """扫描记忆内容

        Args:
            content: 要扫描的内容
            level: 扫描级别 ("all" / "context" / "strict")

        Returns:
            ScanResult: 扫描结果
        """
        if not content:
            return ScanResult(blocked=False)

        # Level 1: 经典注入检测
        if level in ("all", "context", "strict"):
            for pattern in INJECTION_PATTERNS:
                if pattern.search(content):
                    return ScanResult(
                        blocked=True,
                        reason=f"疑似 prompt 注入: 匹配模式 {pattern.pattern[:30]}",
                        threat_level="high",
                    )

        # Level 2: 敏感信息检测
        if level in ("all", "context", "strict"):
            for pattern in SENSITIVE_PATTERNS:
                if pattern.search(content):
                    return ScanResult(
                        blocked=True,
                        reason=f"疑似敏感信息泄露: 匹配模式 {pattern.pattern[:30]}",
                        threat_level="high",
                    )

        # Level 3: 持久化攻击检测
        if level == "strict":
            for pattern in PERSISTENCE_PATTERNS:
                if pattern.search(content):
                    return ScanResult(
                        blocked=True,
                        reason=f"疑似持久化攻击: 匹配模式 {pattern.pattern[:30]}",
                        threat_level="medium",
                    )

        return ScanResult(blocked=False)

    def scan_write(self, content: str) -> ScanResult:
        """写入前扫描（使用最严格的级别）

        Args:
            content: 要写入的记忆内容

        Returns:
            ScanResult
        """
        return self.scan(content, level="strict")


# 全局扫描器实例
_scanner: Optional[MemorySafetyScanner] = None


def get_scanner() -> MemorySafetyScanner:
    """获取全局扫描器实例"""
    global _scanner
    if _scanner is None:
        _scanner = MemorySafetyScanner()
    return _scanner
