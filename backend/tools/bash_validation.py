"""Shell 命令风险启发式校验（M1 工具安全加固）。

移植自 claw-code ``rust/crates/runtime/src/bash_validation.rs`` 的**实用子集**。
claw 原版用纯子串匹配 + 首命令识别；本模块保留同样的务实风格
（子串 / 正则表），不尝试完整 shell 解析——目标是"明显危险的命令
必须被标记"，而不是穷尽所有边界情况。

三档风险:

- ``SAFE``       — 未命中任何规则
- ``SUSPICIOUS`` — 需要用户确认（sudo、curl|sh、系统目录写入、force push 等）
- ``DESTRUCTIVE`` — 极可能不可逆（rm -rf /、mkfs、dd 写盘、fork bomb 等）

本模块是纯函数，不读时钟 / 文件 / 网络；可被 ``PermissionEnforcer`` 注入。

旗标顺序无关的结构化检测
------------------------

纯子串规则只能覆盖 ``rm -rf`` 这一种拼写。对本模块**声称拦截**的三类
命令，另有一层 tokenize 后的结构化启发式（见 ``_segment_tokens`` 规范化
辅助函数），旗标顺序 / 组合任意都命中:

- ``rm``: 递归 (``-r``/``-R``/``--recursive``) + 强制 (``-f``/``--force``)
  以任意顺序出现（``-fr`` ``-r -f`` ``--recursive --force`` 等），且目标
  命中高危集合（``/ ~ * .`` 家族，口径与既有子串规则一致）。
- ``dd``: 只要出现 ``of=/dev/*`` 即判 DESTRUCTIVE（不看 ``if=`` 位置）。
- ``del``/``rd`` (Windows): ``/s`` 与 ``/q`` 任意顺序。

已知局限（接受不修，claw-code 同源共享）
----------------------------------------

字符串匹配启发式不理解 shell 语法，以下绕过 / 误报是已知且有意接受的:

- 编码绕过: ``base64 -d <<< ... | sh``、``eval "$CMD"``、变量展开
  （``$RM -rf /``）、反斜杠转义（``r\\m -rf /``）均不识别。
- 引号不可见: ``echo "rm -rf /"`` 会被当成真实 rm 标记（误报）——
  字符串匹配无法区分字面量与命令，宁可误报不可漏报。
- heredoc / 多行脚本体内部不做语义检查（仅按行分隔符切段）。
- alias / function / 环境变量间接调用（``alias r='rm -rf'``）不追踪。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Pattern, Tuple


class BashRisk(str, Enum):
    """命令风险等级（递增）。"""

    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DESTRUCTIVE = "destructive"


# 用于 max() 比较的等级序（数值越大越危险）
_RISK_ORDER = {
    BashRisk.SAFE: 0,
    BashRisk.SUSPICIOUS: 1,
    BashRisk.DESTRUCTIVE: 2,
}


@dataclass(frozen=True)
class BashValidationResult:
    """校验结果（不可变）。

    Attributes:
        risk:    命中的最高风险等级；无命中为 ``SAFE``。
        reasons: 所有命中规则的人类可读原因（中文），按规则表顺序。
    """

    risk: BashRisk
    reasons: Tuple[str, ...]


# ---------------------------------------------------------------------------
# 规则表。每条规则注明 claw-code 出处或本模块新增理由。
# 子串规则全部小写匹配（claw: command_lower.contains(...)）。
# ---------------------------------------------------------------------------

#: (小写子串, 风险, 原因) — 子串命中即触发
_SUBSTRING_RULES: Tuple[Tuple[str, BashRisk, str], ...] = (
    # claw-code bash_validation.rs DESTRUCTIVE_PATTERNS（原样移植）
    ("rm -rf /", BashRisk.DESTRUCTIVE, "rm -rf 作用于根目录 /"),
    ("rm -rf ~", BashRisk.DESTRUCTIVE, "rm -rf 作用于用户主目录 ~"),
    ("rm -rf *", BashRisk.DESTRUCTIVE, "rm -rf 作用于通配符 *"),
    # 注: claw 的 "rm -rf ." 子串规则误伤 "rm -rf ./build" 等日常操作，
    # 改用下方正则只匹配裸 "." / ".." / "./*"。
    ("mkfs", BashRisk.DESTRUCTIVE, "mkfs 会格式化文件系统"),
    ("dd if=", BashRisk.DESTRUCTIVE, "dd 可能直接写裸磁盘设备"),
    ("> /dev/sd", BashRisk.DESTRUCTIVE, "重定向到块设备 /dev/sd*"),
    (">/dev/sd", BashRisk.DESTRUCTIVE, "重定向到块设备 /dev/sd*"),
    ("> /dev/nvme", BashRisk.DESTRUCTIVE, "重定向到块设备 /dev/nvme*"),
    ("chmod -r 777", BashRisk.DESTRUCTIVE, "chmod -R 777 递归放开全部权限"),
    ("chmod -r 000", BashRisk.DESTRUCTIVE, "chmod -R 000 递归剥夺全部权限"),
    (":(){ :|:& };:", BashRisk.DESTRUCTIVE, "fork bomb 会耗尽系统进程"),
    # claw 原版未覆盖 Windows；sage 面向 Win7 桌面，补齐 Windows 破坏命令
    ("del /s /q", BashRisk.DESTRUCTIVE, "del /s /q 递归强制删除 (Windows)"),
    ("rd /s /q", BashRisk.DESTRUCTIVE, "rd /s /q 递归强制删目录 (Windows)"),
    ("format ", BashRisk.DESTRUCTIVE, "format 会格式化磁盘 (Windows)"),
    # 可疑但非不可逆 → SUSPICIOUS
    ("sudo ", BashRisk.SUSPICIOUS, "使用 sudo 提升权限"),
    ("sudo\t", BashRisk.SUSPICIOUS, "使用 sudo 提升权限"),
)

#: (编译好的正则, 风险, 原因) — 正则规则，小写匹配
_REGEX_RULES: Tuple[Tuple[Pattern, BashRisk, str], ...] = (
    # claw-code DESTRUCTIVE_PATTERNS "rm -rf ." 的精确版: 裸当前目录 /
    # 父目录 / 当前目录全通配 → DESTRUCTIVE；"rm -rf ./build" 等具体
    # 子目录路径不命中（桌面场景日常操作，避免审批疲劳）。
    (
        re.compile(r"rm\s+-rf\s+(?:\.\.?|\.\*|\.\/\*)(?:\s|$)"),
        BashRisk.DESTRUCTIVE,
        "rm -rf 作用于当前目录",
    ),
    # claw-code WRITE/STATE_MODIFYING 命令族中的关机序列（只读模式 Block）。
    # 用单词边界避免误伤（如 "halted"）；关机对桌面用户几乎总是意外操作 → DESTRUCTIVE
    (
        re.compile(r"(?:^|[|;&\s])(?:sudo\s+)?(?:shutdown|reboot|halt|poweroff)\b"),
        BashRisk.DESTRUCTIVE,
        "shutdown/reboot/halt/poweroff 会关闭或重启系统",
    ),
    # dd 写块设备: 子串规则 "dd if=" 只覆盖 if= 在前的写法；
    # of=/dev/* 才是"写盘"的充分证据，与 if= 位置无关 → DESTRUCTIVE
    (
        re.compile(r"\bdd\s+[^|;&\n]*\bof=/dev/"),
        BashRisk.DESTRUCTIVE,
        "dd 输出重定向到块设备 of=/dev/*（if=/of= 顺序任意）",
    ),
    # curl|sh / wget|sh 管道执行远程脚本（claw 仅标记 Network intent，
    # 本模块按 sage 安全需求升级为 SUSPICIOUS）
    (
        re.compile(r"curl\s[^|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"),
        BashRisk.SUSPICIOUS,
        "curl | sh 直接执行远程脚本",
    ),
    (
        re.compile(r"wget\s[^|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"),
        BashRisk.SUSPICIOUS,
        "wget | sh 直接执行远程脚本",
    ),
    # git push --force / --force-with-lease 到 main/master
    # （claw 不检查 --force；sage 显式要求覆盖）
    (
        re.compile(r"git\s+push\s+(?:[^|;&]*)(?:--force\b|--force-with-lease\b|-f\b)[^|;&]*\b(?:main|master)\b"),
        BashRisk.SUSPICIOUS,
        "git push --force 到 main/master",
    ),
    (
        re.compile(r"git\s+push\s+[^|;&]*\b(?:main|master)\b[^|;&]*(?:--force\b|--force-with-lease\b|-f\b)"),
        BashRisk.SUSPICIOUS,
        "git push --force 到 main/master",
    ),
    # 写入系统目录 /etc /usr /bin /sbin 或 C:\Windows
    # （claw: command_targets_outside_workspace → Warn；需要命令里同时出现
    # 写操作痕迹（重定向 / cp / mv / tee 等），避免误伤只读命令）
    (
        re.compile(
            r"(?:>|>>|\bcp\b|\bmv\b|\btee\b|\brm\b|\bchmod\b|\bchown\b|\binstall\b|\bmkdir\b|\bsed\s+-i\b)"
            r"[^|;&]*(?:/(?:etc|usr|bin|sbin)/|\\windows\\|c:\\windows)"
        ),
        BashRisk.SUSPICIOUS,
        "写入系统目录 (/etc /usr /bin /sbin 或 C:\\Windows)",
    ),
)


# ---------------------------------------------------------------------------
# 结构化（旗标顺序无关）启发式
# ---------------------------------------------------------------------------

#: 命令链分隔符 —— 把复合命令粗切成独立执行段
_SEGMENT_SPLIT_RE = re.compile(r"[|;&\n]+")

#: rm 递归 + 强制旗标同时命中时视为不可逆的高危目标。
#: 口径与既有子串 / 正则规则一致（/ ~ * . 家族 + ``~/`` 前缀的主目录路径）；
#: 有意不扩大到任意绝对路径——``rm -rf ./build`` 是桌面日常操作，不误报。
_RM_DANGEROUS_TARGETS = frozenset({"/", "~", "*", ".", "..", ".*", "./*"})


def _segment_tokens(lowered: str) -> List[List[str]]:
    """规范化辅助: 已小写化的命令 → 各执行段的 token 列表。

    只按 shell 元字符（``| ; & 换行``）粗切，不理解引号 / 转义——与模块
    整体的务实启发式定位一致（见 docstring "已知局限"）。拆段能让结构化
    检查只看目标命令所在的段，减少其它命令参数里出现字面 ``rm`` 的误报。
    """
    return [segment.split() for segment in _SEGMENT_SPLIT_RE.split(lowered)]


def _rm_destructive_hits(lowered: str) -> List[Tuple[BashRisk, str]]:
    """rm 旗标顺序无关检测: 递归 + 强制旗标任意顺序/组合 + 高危目标 → DESTRUCTIVE。

    覆盖 ``-fr`` / ``-rf`` / ``-r -f`` / ``-Rfv`` / ``--recursive --force``
    等全部常见拼写。短旗标簇（``-fr`` 等）按字符集判定；``--`` 之后的
    token 一律视为目标。命中时每个高危目标产出一条原因。
    """
    hits: List[Tuple[BashRisk, str]] = []
    for tokens in _segment_tokens(lowered):
        if "rm" not in tokens:
            continue
        body = tokens[tokens.index("rm") + 1 :]
        recursive = False
        force = False
        dangerous_target: Optional[str] = None
        seen_dashdash = False
        for tok in body:
            if seen_dashdash:
                pass  # "--" 之后全部是目标，落到下方目标判定
            elif tok == "--":
                seen_dashdash = True
                continue
            elif tok.startswith("-") and len(tok) > 1:
                if tok == "--recursive":
                    recursive = True
                elif tok == "--force":
                    force = True
                elif not tok.startswith("--"):
                    # 短旗标簇: -fr / -rf / -Rf / -irfv …（输入已小写化）
                    chars = tok[1:]
                    recursive = recursive or "r" in chars
                    force = force or "f" in chars
                continue  # 其它长旗标（--no-preserve-root 等）不影响判定
            if dangerous_target is None and (
                tok in _RM_DANGEROUS_TARGETS or tok.startswith("~/")
            ):
                dangerous_target = tok
        if recursive and force and dangerous_target is not None:
            hits.append(
                (
                    BashRisk.DESTRUCTIVE,
                    f"rm 递归+强制（任意旗标顺序）作用于高危目标 {dangerous_target}",
                )
            )
    return hits


def _delrd_destructive_hits(lowered: str) -> List[Tuple[BashRisk, str]]:
    """Windows del/rd 旗标顺序无关检测: /s 与 /q 任意顺序 → DESTRUCTIVE。

    子串规则只覆盖 ``del /s /q`` 这一种顺序；``del /q /s`` 等变体在此兜住。
    """
    hits: List[Tuple[BashRisk, str]] = []
    for tokens in _segment_tokens(lowered):
        if not tokens or tokens[0] not in ("del", "rd"):
            continue
        flags = {tok for tok in tokens[1:] if tok.startswith("/")}
        if "/s" in flags and "/q" in flags:
            reason = (
                "del /s /q 递归强制删除 (Windows)"
                if tokens[0] == "del"
                else "rd /s /q 递归强制删目录 (Windows)"
            )
            hits.append((BashRisk.DESTRUCTIVE, reason))
    return hits


def validate_bash(command: str) -> BashValidationResult:
    """对单条命令字符串做风险分级（纯函数）。

    Args:
        command: 待校验的命令文本（可含管道 / 链式命令，不做语法解析）。

    Returns:
        ``BashValidationResult``：最高命中风险 + 全部命中原因。
        无任何命中时 ``risk=SAFE, reasons=()``。
    """
    if not command or not command.strip():
        return BashValidationResult(risk=BashRisk.SAFE, reasons=())

    lowered = command.lower()
    hits: List[Tuple[BashRisk, str]] = []

    for pattern, risk, reason in _SUBSTRING_RULES:
        if pattern in lowered:
            hits.append((risk, reason))

    for regex, risk, reason in _REGEX_RULES:
        if regex.search(lowered):
            hits.append((risk, reason))

    # 结构化启发式（旗标顺序无关）：与子串 / 正则规则取并集。
    # 子串规则负责"任意位置出现即危险"的语义，结构化规则负责
    # "rm -fr / rm -r -f / del /q /s"等旗标变体。
    hits.extend(_rm_destructive_hits(lowered))
    hits.extend(_delrd_destructive_hits(lowered))

    if not hits:
        return BashValidationResult(risk=BashRisk.SAFE, reasons=())

    top = max(hits, key=lambda h: _RISK_ORDER[h[0]])[0]
    # 去重保序：同一原因可能出现多次（例如两条正则描述相同）
    seen = set()
    reasons = tuple(r for _, r in hits if not (r in seen or seen.add(r)))  # type: ignore[func-returns-value]
    return BashValidationResult(risk=top, reasons=reasons)


__all__ = [
    "BashRisk",
    "BashValidationResult",
    "validate_bash",
]
