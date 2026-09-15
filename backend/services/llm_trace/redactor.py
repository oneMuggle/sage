"""secrets 自动脱敏:10 类 pattern + JSON 递归 + URL/Header。

设计要点:
- 替换占位符 = `***REDACTED:<类型>***`,便于支持人员看到"这里原来是什么"
- 不修改输入,返回新对象(dict / list / str)
- body 解析失败不抛异常,返回 (None, reason) 让调用方决定怎么标
- binary body 永远返回 (None, "binary") 强信号
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

REDACTION_MARKER = "***REDACTED:{kind}***"

# 10 类 pattern —— 顺序敏感(更具体的优先,避免 jwt 被 bearer 吃掉)
_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    ("openai_key", re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|sk_live_[A-Za-z0-9]+|gsk_[A-Za-z0-9]+)")),
    ("basic", re.compile(r"(?<=Basic )[A-Za-z0-9+/=]+")),
]

# JSON 中需要脱敏的字段名(大小写不敏感)
_SENSITIVE_FIELDS = {
    "password": "password",
    "passwd": "password",
    "pwd": "password",
    "token": "token",
    "access_token": "token",
    "refresh_token": "token",
    "id_token": "token",
    "api_key": "api_key",
    "apikey": "api_key",
    "api-key": "api_key",
    "secret": "secret",
    "client_secret": "secret",
}

_QUERY_RULES: List[Tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"(api[_-]?key|key)=([^&]+)", re.IGNORECASE)),
]


def _marker(kind: str) -> str:
    return REDACTION_MARKER.format(kind=kind)


def redact_url(url: str) -> str:
    """剥 userinfo + 替换 query 中的 api_key 等。"""
    # 1) 剥 userinfo: http://user:pass@host → http://***:***@host
    out = re.sub(r"://([^/@]+)@", r"://***:***@", url)
    # 2) 替换 query secrets
    for kind, pat in _QUERY_RULES:
        out = pat.sub(lambda m, _kind=kind: f"{m.group(1)}={_marker(_kind)}", out)
    return out


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """全字段名匹配,值脱敏;返回新 dict。"""
    out: Dict[str, str] = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower == "authorization":
            if v.startswith("Bearer "):
                out[k] = "Bearer " + _marker("bearer")
            elif v.startswith("Basic "):
                out[k] = "Basic " + _marker("basic")
            else:
                out[k] = v
        elif k_lower in ("cookie", "set-cookie"):
            out[k] = _marker("cookie")
        elif k_lower in ("x-api-key", "api-key"):
            out[k] = _marker("api_key")
        else:
            out[k] = v
    return out


def redact_text(text: str) -> str:
    """对纯文本全文扫 secrets pattern。"""
    out = text
    for kind, pat in _PATTERNS:
        out = pat.sub(_marker(kind), out)
    return out


def _redact_json_value(value: Any, *, include_prompts: bool) -> Any:
    """递归走 JSON 树,返回值可能是 dict/list/str/int/bool/None。"""
    if isinstance(value, dict):
        new: Dict[str, Any] = {}
        for k, v in value.items():
            k_lower = str(k).lower()
            if k_lower in _SENSITIVE_FIELDS:
                new[k] = _marker(_SENSITIVE_FIELDS[k_lower])
            elif k_lower == "messages" and isinstance(v, list):
                # messages 数组里的每个 item 需要特殊处理:include_prompts=False 时
                # content 字段整段替换为 prompt marker;include_prompts=True 时正常 redact_text
                new[k] = [_redact_message_item(item, include_prompts=include_prompts) for item in v]
            else:
                new[k] = _redact_json_value(v, include_prompts=include_prompts)
        return new
    if isinstance(value, list):
        return [_redact_json_value(item, include_prompts=include_prompts) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value  # int / bool / None / float 原样


def _redact_message_item(item: Any, *, include_prompts: bool) -> Any:
    """处理 messages[] 里的单个消息 dict。

    include_prompts=False 时,content 字段整段替换为 prompt marker(保留结构字段如 role)。
    include_prompts=True 时,正常 redact_text(保留原文但脱敏 secrets)。
    """
    if not isinstance(item, dict):
        return _redact_json_value(item, include_prompts=include_prompts)
    new: Dict[str, Any] = {}
    for k, v in item.items():
        if k.lower() == "content" and not include_prompts:
            new[k] = _marker("prompt")
        else:
            new[k] = _redact_json_value(v, include_prompts=include_prompts)
    return new


def redact_body(  # noqa: PLR0911
    body: Optional[Union[bytes, str, dict, list]],
    *,
    include_prompts: bool = False,
) -> Tuple[Any, Optional[str]]:
    """脱敏 body。

    Returns:
        (redacted_value, parse_error_msg)
        - JSON 路径成功: (dict_or_list, None)
        - JSON 路径失败: (None, "json: <reason>")
        - 文本路径(纯字符串): (str, None)
        - 二进制 / None: (None, "binary" / None)
    """
    if body is None:
        return None, None
    if isinstance(body, (dict, list)):
        return _redact_json_value(body, include_prompts=include_prompts), None
    if isinstance(body, bytes):
        # 试图解析为 UTF-8 JSON
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None, "binary"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            # 不是 JSON:按 spec §4.5 返回 (None, "json: <reason>") 让 caller 区分于 binary
            return None, f"json: {e.msg}"
        return _redact_json_value(parsed, include_prompts=include_prompts), None
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as e:
            return None, f"json: {e.msg}"
        return _redact_json_value(parsed, include_prompts=include_prompts), None
    return None, "unsupported_type"
