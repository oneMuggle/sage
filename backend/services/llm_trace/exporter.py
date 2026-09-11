"""把 ring buffer 中的 TraceRecord 组装为 zip bytes。

zip 内部文件:
- manifest.json    schema_version / app_version / redactor_version / trace_count / generated_at
- system.json      os / python / electron / app / hostname(可选)
- config.yaml      config 快照(经 redactor 脱敏 api_key 等)
- trace.jsonl      每行一条 TraceRecord,经 redactor 二层脱敏(T7 实现)
- README.txt       给支持人员的人读说明

体积策略(T7):单条 body > 512KB 截断,单条 > 1MB 整条丢弃 body,总 zip ≤ 5MB。
"""
from __future__ import annotations

import io
import json
import platform
import socket
import sys
import zipfile
from datetime import datetime, timezone
from typing import List, Optional

from backend.services.llm_trace.recorder import TraceRecord
from backend.services.llm_trace.redactor import (
    redact_body,
    redact_headers,
    redact_text,
    redact_url,
)

SCHEMA_VERSION = "1"
REDACTOR_VERSION = "1"
APP_VERSION_DEFAULT = "unknown"


def _build_manifest(
    trace_count: int,
    app_version: str,
    *,
    include_prompts: bool,
    include_hostname: bool,
) -> bytes:
    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "app_version": app_version,
            "redactor_version": REDACTOR_VERSION,
            "trace_count": trace_count,
            "include_prompts": include_prompts,
            "include_hostname": include_hostname,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # noqa: UP017
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _build_system(*, include_hostname: bool) -> bytes:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "python_version": sys.version.split()[0],
        "app_version": APP_VERSION_DEFAULT,
    }
    if include_hostname:
        try:
            info["hostname"] = socket.gethostname()
        except Exception:  # pragma: no cover - sandbox 内 hostname 不可用
            info["hostname"] = None
    return json.dumps(info, ensure_ascii=False).encode("utf-8")


def _build_config_snapshot(raw: str) -> bytes:
    """对 config 文本走 redact_text 扫 secrets(API key / token / password 等)。"""
    if not raw:
        return b""
    return redact_text(raw).encode("utf-8")


_README_TEMPLATE = """\
Sage 诊断包 — 解包说明
=========================

本文件由 Sage 桌面端导出,用于离线问题排查。**包含 LLM 调用细节,
即使默认脱敏,请人工 review 后再外发。**

文件清单:
- manifest.json    版本与生成元信息(safe to share)
- system.json      系统信息(主机名仅在导出时勾选才包含)
- config.yaml      Sage 配置快照(secrets 已脱敏)
- trace.jsonl      最近 50 次 LLM 调用,每行一条 JSON
- README.txt       本文件

trace.jsonl 每行字段:
- trace_id         UUID,可与 backend/logs/sage_*.log 中 trace= 字段对齐
- ts               ISO 8601 UTC 时间戳
- endpoint         本地端点(始终是 /api/v1/chat/completions)
- upstream_url     实际转发的上游 URL(关键! 出错时看这里)
- upstream_method  HTTP 方法
- request.headers  已脱敏的请求头
- request.body_json  已脱敏的请求体 JSON(若可解析)
- response.status  上游返回的 HTTP 状态码
- response.body_text 已脱敏的响应文本
- response.error   上游返回的错误消息(若有)
- duration_ms      调用耗时
- error_class      错误分类:upstream_401 / tls_failed / timeout / ...

快速诊断流程:
1. 看 manifest.json 确认版本对应
2. 看 trace.jsonl 最后几行(最近调用)
3. 若 401:确认 upstream_url 正确 + Authorization 头存在
4. 若 5xx:看 response.error 字段
5. 若 timeout:看 duration_ms 与 response 是否为空
"""


def export_to_zip_bytes(
    records: List[TraceRecord],
    *,
    include_prompts: bool,
    include_hostname: bool,
    app_version: str,
    config_snapshot: str,
) -> bytes:
    """组装诊断包为 zip bytes,返回。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. manifest
        zf.writestr("manifest.json", _build_manifest(
            len(records), app_version,
            include_prompts=include_prompts, include_hostname=include_hostname,
        ))
        # 2. system
        zf.writestr("system.json", _build_system(include_hostname=include_hostname))
        # 3. config (经脱敏)
        zf.writestr("config.yaml", _build_config_snapshot(config_snapshot))
        # 4. trace.jsonl —— T7 实现 body 截断 + 二层脱敏
        trace_lines = []
        for rec in records:
            trace_lines.append(_serialize_record(rec, include_prompts=include_prompts))
        zf.writestr("trace.jsonl", "\n".join(trace_lines).encode("utf-8"))
        # 5. README
        zf.writestr("README.txt", _README_TEMPLATE)
    return buf.getvalue()


def _serialize_record(rec: TraceRecord, *, include_prompts: bool) -> str:
    """单条 record 序列化为一行 JSON。第二层脱敏在此发生。"""
    # headers / url 已经在 recorder.append 走过一遍,这里再走一遍确保 invariant
    req_body_obj, req_body_err = redact_body(rec.request_body, include_prompts=include_prompts)
    resp_body_obj, resp_body_err = redact_body(rec.response_body, include_prompts=False)
    obj = {
        "trace_id": rec.trace_id,
        "ts": rec.ts.isoformat().replace("+00:00", "Z"),
        "endpoint": rec.endpoint,
        "upstream_url": redact_url(rec.upstream_url),
        "upstream_method": rec.upstream_method,
        "request": {
            "headers": redact_headers(rec.request_headers),
            "body_bytes": len(rec.request_body),
            "body_json": req_body_obj,
            "body_parse_error": req_body_err,
        },
        "response": {
            "status": rec.response_status,
            "headers": redact_headers(rec.response_headers),
            "streamed": rec.response_streamed,
            "body_bytes": len(rec.response_body),
            "body_text": (resp_body_obj if isinstance(resp_body_obj, str) else None),
            "body_truncated": False,  # T7 实现
            "body_encoding": "binary" if resp_body_err == "binary" else "utf-8",
            "error": _extract_error_message(rec.response_body, rec.response_status),
        },
        "duration_ms": rec.duration_ms,
        "error_class": rec.error_class,
    }
    return json.dumps(obj, ensure_ascii=False)


def _extract_error_message(body: bytes, status: Optional[int]) -> Optional[str]:
    """从 JSON 响应体里抽出 error.message 字段(若有)。"""
    if body is None or status is None or status < 400:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict) and "message" in err:
                return redact_text(str(err["message"]))
            if "message" in parsed:
                return redact_text(str(parsed["message"]))
    except Exception:
        pass
    return None
