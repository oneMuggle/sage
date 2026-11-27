"""事实侦察清单的结构化解析（2026-11-27）。

lite scout 的产出是 LLM 自由文本（"输出不超过 10 条关键事实，每条一句话并注明
来源"）。本模块把这段文本**保守地**解析成结构化事实清单，供前端「事实侦察」
区块展示与落库。

纪律：宁可不拆，也绝不丢信息或臆造 —— 任何无法确定的形态一律整行保留为一条
事实正文（来源留空），绝不因为"解析不出结构"而丢行。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

#: 展示条数上限（scout 本身 ≤ 10 条，这里是防御性上限）
SCOUT_FACTS_MAX_ITEMS = 12

#: 单条事实正文的字符上限。取 4000 = 上游 ``SCOUT_FACTS_MAX_CHARS``（lite scout
#: 产出的原始文本在此处之前已整段截断到 4000 字符），因此生产路径**永不触发**
#: —— 单条事实无论多长都会完整保留。常量仅为其它调用方（传入任意 raw）兜底，
#: 保证不会产出无界载荷；触发时补省略号。
SCOUT_FACT_MAX_CHARS = 4000

#: 来源标注的字符上限 —— 超过则视为正文而非来源
SCOUT_SOURCE_MAX_CHARS = 120

#: 正文最小长度 —— 拆出来太短说明拆错了（例如"根据来源：X"里的"根据"）
SCOUT_MIN_BODY_CHARS = 6

#: client_meta JSON 的字节上限（与用户消息展示元数据同口径）
SCOUT_CLIENT_META_MAX_BYTES = 32768

# 行首 bullet 前缀：- * • ‣ ▪ / 1. 1) / ① / (1)
_BULLET_RE = re.compile(
    r"^\s*(?:[-*•‣▪]|\d+[.)]|[①-⑳]|[（(]\d+[)）])\s*"
)

# 行尾来源标注：
#   （来源：X） / (来源: X) / [来源: X] / 结尾的 "来源：X"
_SOURCE_TAIL_RE = re.compile(
    r"(?:[（(]\s*(?:来源|出处|出自)\s*[:：]\s*(?P<paren>[^）)]*)[）)]"
    r"|\[\s*(?:来源|出处|出自)\s*[:：]\s*(?P<bracket>[^\]]*)\]"
    r"|(?:来源|出处|出自)\s*[:：]\s*(?P<plain>[^。；;]{1,120})\s*$)"
)


def _strip_bullet(line: str) -> str:
    """剥掉行首 bullet 前缀（非 bullet 行原样返回）。"""
    stripped = _BULLET_RE.sub("", line, count=1)
    return stripped.strip()


def _split_source(line: str) -> Tuple[str, str]:
    """拆出行尾来源标注；拆不出或拆得可疑时整行保留为正文。

    Returns:
        ``(text, source)`` —— source 为空串表示未识别出来源。
    """
    match = _SOURCE_TAIL_RE.search(line)
    if not match:
        return line, ""

    source = ""
    for key in ("paren", "bracket", "plain"):
        value = match.groupdict().get(key)
        if value:
            source = value.strip()
            break
    if not source or len(source) > SCOUT_SOURCE_MAX_CHARS:
        return line, ""

    before = line[: match.start()].strip().rstrip("：:，,；;、 ")
    after = line[match.end() :].strip().lstrip("：:，,；;、 ")
    # 来源可在行尾（"正文（来源：X）"）也可在行首（"[来源: X] 正文"）；
    # 两侧都取不到像样的正文时说明拆错了 —— 保守地整行保留。
    if len(before) >= SCOUT_MIN_BODY_CHARS:
        body = before
    elif len(after) >= SCOUT_MIN_BODY_CHARS:
        body = after
    else:
        return line, ""
    return body, source


def _parse_all(raw: str) -> List[Dict[str, str]]:
    """解析全部事实行（不做条数上限）。"""
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line]
    # 引导句（"以下是侦察到的事实："）不是事实 —— 仅当其后确有内容时跳过。
    if len(lines) > 1 and lines[0].endswith(("：", ":")):
        lines = lines[1:]

    facts: List[Dict[str, str]] = []
    for line in lines:
        text, source = _split_source(_strip_bullet(line))
        if not text:
            continue
        if len(text) > SCOUT_FACT_MAX_CHARS:
            text = text[:SCOUT_FACT_MAX_CHARS] + "…"
        facts.append({"text": text, "source": source})
    return facts


def parse_scout_facts(raw: str) -> List[Dict[str, str]]:
    """把侦察文本解析成结构化事实清单（最多 ``SCOUT_FACTS_MAX_ITEMS`` 条）。"""
    return _parse_all(raw)[:SCOUT_FACTS_MAX_ITEMS]


def to_detail(raw: str) -> Dict[str, Any]:
    """生成 plan_progress.detail 载荷（事实清单 + 条数 + 是否截断）。"""
    all_facts = _parse_all(raw)
    facts = all_facts[:SCOUT_FACTS_MAX_ITEMS]
    return {
        "facts": facts,
        "fact_count": len(facts),
        "truncated": len(all_facts) > len(facts),
    }


def build_client_meta_json(detail: Optional[Dict[str, Any]]) -> Optional[str]:
    """把事实清单 detail 序列化成 messages.client_meta 的 JSON 载荷。

    只用于会话气泡回显，不参与 LLM 上下文。序列化失败或超限时返回
    ``None`` —— 只丢展示元数据，不影响消息本身落库。
    """
    if not detail:
        return None
    facts = detail.get("facts")
    if not isinstance(facts, list) or not facts:
        return None
    try:
        payload = json.dumps({"scout_facts": detail}, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    if len(payload.encode("utf-8")) > SCOUT_CLIENT_META_MAX_BYTES:
        return None
    return payload


__all__ = [
    "SCOUT_CLIENT_META_MAX_BYTES",
    "SCOUT_FACTS_MAX_ITEMS",
    "SCOUT_FACT_MAX_CHARS",
    "SCOUT_SOURCE_MAX_CHARS",
    "build_client_meta_json",
    "parse_scout_facts",
    "to_detail",
]
