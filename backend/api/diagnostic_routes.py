"""诊断包 HTTP 端点。

- GET  /preview   看目前采集了几条 + 时间范围 + URL 样例
- POST /export    生成 zip bytes(由调用方决定落盘位置)

受 LocalAuthMiddleware 保护(SAGE_LOCAL_AUTH_TOKEN)。**不**为诊断接口开洞。
"""
from __future__ import annotations

import io as _io
import logging
from typing import List

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel  # pydantic v1 兼容

from backend.services.llm_trace.exporter import export_to_zip_bytes
from backend.services.llm_trace.recorder import LlmTraceRecorder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


class PreviewResponse(BaseModel):
    count: int
    oldestTs: str | None = None  # noqa: N815 — camelCase 对齐前端
    newestTs: str | None = None  # noqa: N815
    sampleUrls: List[str] = []  # noqa: N815
    version: str = "1"

    class Config:
        allow_population_by_field_name = True


@router.get("/preview", response_model=PreviewResponse)
def get_preview() -> PreviewResponse:
    """给设置页卡片用的轻量预览。不返回 body,只返回元信息。"""
    snap = LlmTraceRecorder.snapshot()
    if not snap:
        return PreviewResponse(count=0)
    sample_urls = [r.upstream_url for r in snap[:10]]
    return PreviewResponse(
        count=len(snap),
        oldestTs=snap[0].ts.isoformat().replace("+00:00", "Z"),
        newestTs=snap[-1].ts.isoformat().replace("+00:00", "Z"),
        sampleUrls=sample_urls,
    )


def _get_app_version() -> str:
    try:
        from backend import __version__  # type: ignore
        return __version__
    except Exception:
        return "unknown"


def _get_config_snapshot() -> str:
    try:
        from backend.config import get_config_yaml_text  # type: ignore
        return get_config_yaml_text()
    except Exception:
        return ""


@router.post("/export")
def post_export(
    include_prompts: bool = Query(default=False),
    include_hostname: bool = Query(default=False),
) -> StreamingResponse:
    """生成诊断包 zip,直接 stream bytes 给调用方(不在后端落临时文件)。"""
    records = LlmTraceRecorder.snapshot()
    zip_bytes = export_to_zip_bytes(
        records=records,
        include_prompts=include_prompts,
        include_hostname=include_hostname,
        app_version=_get_app_version(),
        config_snapshot=_get_config_snapshot(),
    )
    return StreamingResponse(
        _io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="diagnostic.zip"'},
    )


# ==================== 搜索引擎健康自检（Round 9 R9-2） ====================


class EngineHealth(BaseModel):
    name: str
    configured: bool
    ok: bool
    latencyMs: int = 0  # noqa: N815 — camelCase 对齐前端
    detail: str = ""

    class Config:
        allow_population_by_field_name = True


class SearchEnginesHealthResponse(BaseModel):
    engines: List[EngineHealth] = []

    class Config:
        allow_population_by_field_name = True


@router.get("/search-engines", response_model=SearchEnginesHealthResponse)
def get_search_engines_health() -> SearchEnginesHealthResponse:
    """逐个探测当前配置的搜索引擎链（设置页"测试连通性"用）。

    对每个引擎发一次最小真实查询（SearchEngine.check）：Bing/DDG 探可达性与
    解析，Tavily/智谱探 key 有效性；未配置 key 的 API 引擎如实话报"未配置"。
    全部已知引擎都出现在响应里——用户能看出"哪个引擎没配/哪个引擎不通"。
    串行执行，总时长受各引擎 30s 超时约束。
    """
    from backend.tools.http_factory import build_client
    from backend.tools.search_config import load_search_config
    from backend.tools.search_engines import resolve_engine_chain

    config = load_search_config()
    chain_by_name = {engine.name: engine for engine in resolve_engine_chain(config)}

    engines_report: List[EngineHealth] = []
    for name in ("bing", "ddg", "tavily", "zhipu"):
        engine = chain_by_name.get(name)
        if engine is None:
            engines_report.append(
                EngineHealth(
                    name=name,
                    configured=False,
                    ok=False,
                    latencyMs=0,
                    detail="未配置（缺 API key 或不在引擎链）",
                )
            )
            continue
        with build_client(timeout=30.0) as client:
            outcome = engine.check(client)
        engines_report.append(
            EngineHealth(
                name=engine.name,
                configured=True,
                ok=bool(outcome.get("ok")),
                latencyMs=int(outcome.get("latency_ms", 0)),
                detail=str(outcome.get("detail", "")),
            )
        )

    return SearchEnginesHealthResponse(engines=engines_report)
