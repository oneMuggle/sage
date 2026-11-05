# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""专家包 API 路由组（M1-D，spec §8.3）。

两个端点:

- ``GET /specialists/{agent_id}/export`` — 导出专家包为 ``.sage`` zip
- ``POST /specialists/import`` — 从上传的 zip 包导入专家

zip 包结构见 ``backend.services.specialist_exporter`` 与
``backend.services.specialist_importer`` 的模块 docstring。

路由无 prefix，经 ``legacy_router`` include 后实际路径为
``/api/v1/specialists/*``（与 ``/api/v1/agents/*`` 同构）。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.agents.knowledge_binding import (
    KnowledgeBinding,
    KnowledgeSourceType,
)
from backend.api.settings_models import model_dump_compat, model_validate_compat
from backend.data.database import make_with_db_lock

router = APIRouter()
logger = logging.getLogger(__name__)


def with_db_lock(func):
    """装饰器：包在全局 ``_SQLITE_LOCK`` 内（D3 make_with_db_lock 模式）。"""
    return make_with_db_lock(globals())(func)


@router.get("/specialists/{agent_id}/export")
def export_specialist_package(agent_id: str):
    """导出专家包为 ``.sage`` zip（spec §8.3 导出）。

    - 200 + zip 文件（Content-Disposition: attachment）
    - 404 — 专家不存在（agents 表或数据目录缺失）
    - 400 — agent_id 非法
    """
    from backend.services.specialist_exporter import export_specialist

    try:
        zip_path = export_specialist(agent_id)
    except ValueError as exc:
        # 非法 agent_id vs agents 表无此专家 → 区分处理
        message = str(exc)
        if "非法 agent_id" in message:
            raise HTTPException(
                status_code=400, detail={"type": "invalid_agent_id", "message": message}
            )
        raise HTTPException(
            status_code=404, detail={"type": "agent_not_found", "message": message}
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"type": "agent_not_found", "message": str(exc)}
        )

    # FileResponse 完毕后清理临时目录（BackgroundTask 延迟删除）
    from starlette.background import BackgroundTask

    def _cleanup() -> None:
        shutil.rmtree(zip_path.parent, ignore_errors=True)

    return FileResponse(
        path=str(zip_path),
        filename=f"{agent_id}.sage",
        media_type="application/zip",
        background=BackgroundTask(_cleanup),
    )


@router.post("/specialists/import")
def import_specialist_package(file: UploadFile = File(...)):
    """从上传的 ``.sage`` zip 包导入专家（spec §8.3 导入）。

    - 200 + ``{"id": <new_id>, "name": <display_name>, "dropped_bindings": <int>}``
      其中 ``dropped_bindings`` 为跨机器不可移植（非 ``specialist_private``）而
      被丢弃的知识绑定数量
    - 400 — 格式非法 / persona.md 缺失 / 安全扫描失败 / 大小超限
    """
    from backend.services.specialist_importer import import_specialist

    # 保存上传文件到临时目录
    tmp_dir = tempfile.mkdtemp(prefix="sage-upload-")
    try:
        upload_path = Path(tmp_dir) / "upload.sage"
        with upload_path.open("wb") as f:
            # 分块写（避免一次性读入内存）
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        try:
            result = import_specialist(upload_path)
        except ValueError as exc:
            logger.warning("专家导入失败: %s", exc)
            raise HTTPException(
                status_code=400, detail={"type": "import_failed", "message": str(exc)}
            )
        except Exception as exc:  # noqa: BLE001 — 兜底 500
            logger.error("专家导入异常: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"type": "import_error", "message": f"导入失败: {exc}"},
            )

        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =====================================================================
# M4-Task 2 — 内置模板库（spec §9）
# =====================================================================


@router.get("/specialists/templates")
def list_specialist_templates():
    """返回内置专家模板元数据列表（spec §M4 模板库）。

    响应: ``{"templates": [{id, name, tagline, avatar, description, skill_count}]}``
    顺序由 ``specialist_templates._TEMPLATE_ORDER`` 决定。不含 system_prompt 正文。
    """
    from backend.services.specialist_templates import list_templates

    return {"templates": list_templates()}


@router.post(
    "/specialists/templates/{template_id}/instantiate",
    status_code=201,
)
def instantiate_specialist_template(template_id: str):
    """从内置模板一键创建专家（spec §M4 模板库）。

    - 201 + ``{"id", "name", "template_id", "dropped_bindings"}``
    - 404 — 模板不存在 / id 非法
    - 400 — 物化失败（agents 行冲突、注入扫描失败等）
    """
    from backend.services.specialist_templates import instantiate_template

    try:
        return instantiate_template(template_id)
    except ValueError as exc:
        message = str(exc)
        if "模板不存在" in message:
            raise HTTPException(
                status_code=404,
                detail={"type": "template_not_found", "message": message},
            )
        raise HTTPException(
            status_code=400,
            detail={"type": "template_instantiate_failed", "message": message},
        )


# =====================================================================
# M2-Task 2 — 知识绑定 CRUD（spec §6.1）
# =====================================================================


class KnowledgeBindingCreatePayload(BaseModel):
    """``POST /specialists/{agent_id}/knowledge`` 请求体。

    与 ``KnowledgeBinding`` 的区别：不含 ``id`` / ``created_at``——两者
    由服务端生成，客户端不能指定（``extra='forbid'`` 会拒绝多余字段）。
    """

    agent_id: str = Field(min_length=1, max_length=64)
    source_type: KnowledgeSourceType
    source_id: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=200)
    filters: Dict[str, Any] = Field(default_factory=dict)

    class Config:  # noqa: D401 — Pydantic v1/v2 双兼容配置
        extra = "forbid"


def _get_specialist_profile(repo: Any, agent_id: str) -> Dict[str, Any]:
    """取专家 profile；不存在 → 404。"""
    profile = repo.get(agent_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )
    return profile


def _bump_version(profile: Dict[str, Any]) -> int:
    return int(profile.get("version", 1)) + 1


def _parse_bindings(raw_bindings: Any) -> list:
    """把 DB 里的原始 dict 列表反序列化为 ``KnowledgeBinding``。

    脏数据（历史遗留 / 手改 DB）单条跳过并记 warning，避免整列表 500。
    """
    parsed = []
    for raw in raw_bindings or []:
        try:
            parsed.append(model_validate_compat(KnowledgeBinding, raw))
        except Exception as exc:  # noqa: BLE001 — 单条脏数据不拖垮整个列表
            logger.warning("跳过非法知识绑定 %r: %s", raw, exc)
    return parsed


@router.get("/specialists/{agent_id}/knowledge")
@with_db_lock
def list_specialist_knowledge(agent_id: str):
    """列出专家的知识绑定（按 ``created_at`` 升序）。

    - 200 + ``[KnowledgeBinding, ...]``
    - 404 — 专家不存在
    """
    from backend.data.agent_repo import AgentRepository

    profile = _get_specialist_profile(AgentRepository(), agent_id)
    parsed = _parse_bindings(profile.get("knowledge_bindings"))
    parsed.sort(key=lambda b: b.created_at)
    return [model_dump_compat(b) for b in parsed]


@router.post("/specialists/{agent_id}/knowledge", status_code=201)
@with_db_lock
def create_specialist_knowledge(agent_id: str, data: KnowledgeBindingCreatePayload):
    """新增一条知识绑定。

    - 201 + 新建的 ``KnowledgeBinding``（含生成的 ``id`` / ``created_at``）
    - 404 — 专家不存在
    - 422 — 字段校验失败 / body ``agent_id`` 与路径不一致
    """
    from backend.data.agent_repo import AgentRepository

    if data.agent_id != agent_id:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "agent_id_mismatch",
                "message": (
                    f"body agent_id {data.agent_id!r} does not match path "
                    f"{agent_id!r}"
                ),
            },
        )

    repo = AgentRepository()
    profile = _get_specialist_profile(repo, agent_id)

    binding = KnowledgeBinding(
        agent_id=agent_id,
        source_type=data.source_type,
        source_id=data.source_id,
        name=data.name,
        filters=dict(data.filters),
    )
    bindings = list(profile.get("knowledge_bindings") or [])
    bindings.append(model_dump_compat(binding))

    repo.update(
        agent_id,
        {"knowledge_bindings": bindings, "version": _bump_version(profile)},
    )
    return model_dump_compat(binding)


@router.delete("/specialists/{agent_id}/knowledge/{binding_id}", status_code=204)
@with_db_lock
def delete_specialist_knowledge(agent_id: str, binding_id: str):
    """删除一条知识绑定。

    - 204 — 删除成功
    - 404 — 专家不存在 / binding_id 不归属该专家
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    profile = _get_specialist_profile(repo, agent_id)

    bindings = list(profile.get("knowledge_bindings") or [])
    remaining = [b for b in bindings if b.get("id") != binding_id]
    if len(remaining) == len(bindings):
        raise HTTPException(
            status_code=404,
            detail={
                "type": "binding_not_found",
                "message": (
                    f"binding {binding_id!r} not found for agent {agent_id!r}"
                ),
            },
        )

    repo.update(
        agent_id,
        {"knowledge_bindings": remaining, "version": _bump_version(profile)},
    )
    return Response(status_code=204)


__all__ = ["router"]
