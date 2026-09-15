# backend/api/artifact_routes.py
"""Artifact(产物)相关 API 路由。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.data import artifact_reader, artifact_repo, artifact_version_repo

router = APIRouter(prefix="/sessions/{session_id}/artifacts", tags=["artifacts"])


@router.get("")
def list_artifacts(session_id: str) -> dict:
    """列出指定 session 的所有产物。"""
    items = artifact_repo.list_artifacts(session_id)
    return {"artifacts": [a.to_dict() for a in items]}


@router.get("/{artifact_id}/content")
def get_artifact_content(session_id: str, artifact_id: str) -> dict:
    """读取产物内容:文本返回 content,图片/PDF 返回 data_url,office 返回 HTML。

    F11 (round4 批次 D): PDF 走 base64 data URL,前端 iframe 内嵌渲染。
    C-2 (round5 批次 C): docx/xlsx/pptx 走后端转换的全转义 HTML 预览。
    kind 判定带后缀兜底——历史产物注册时后缀曾归为 "text"。
    """
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    from pathlib import Path

    suffix = Path(artifact.path).suffix.lower().lstrip(".")
    if artifact.kind == "pdf" or suffix == "pdf":
        return artifact_reader.read_pdf(artifact_id)
    if artifact.kind == "image":
        return artifact_reader.read_image(artifact_id)
    if artifact.kind in ("docx", "xlsx", "pptx") or suffix in ("docx", "xlsx", "pptx"):
        kind = artifact.kind if artifact.kind in ("docx", "xlsx", "pptx") else suffix
        return artifact_reader.read_office(artifact_id, kind=kind)
    # P1-3.5 (UI 优化方案 2026-09-13): HTML 产物返回 kind="html"，前端用沙盒 iframe 渲染
    if suffix in ("html", "htm"):
        result = artifact_reader.read_text(artifact_id)
        result["kind"] = "html"
        return result
    return artifact_reader.read_text(artifact_id)


@router.post("/{artifact_id}/reveal")
def reveal_artifact(session_id: str, artifact_id: str) -> dict:
    """在系统文件管理器中显示产物。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return artifact_reader.reveal_in_file_manager(artifact_id)


# ==================== Version History (Phase 2 M2) ====================


@router.get("/{artifact_id}/versions")
def list_artifact_versions(session_id: str, artifact_id: str) -> dict:
    """列出指定产物的所有版本（元数据，不含内容）。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    versions = artifact_version_repo.list_versions(artifact_id)
    return {"versions": versions}


@router.get("/{artifact_id}/versions/{version_num}")
def get_artifact_version(session_id: str, artifact_id: str, version_num: int) -> dict:
    """获取指定版本的完整内容。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    version = artifact_version_repo.get_version(artifact_id, version_num)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    return version


class RestoreVersionRequest(BaseModel):
    """恢复请求体"""
    version_num: int
    note: str = "restore"


@router.post("/{artifact_id}/versions/restore")
def restore_artifact_version(
    session_id: str, artifact_id: str, req: RestoreVersionRequest
) -> dict:
    """恢复到指定版本（创建新版本，历史不删除）。

    读取目标版本的快照内容，计算 hash，创建新版本。
    """
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # 获取目标版本内容
    target_version = artifact_version_repo.get_version(artifact_id, req.version_num)
    if target_version is None:
        raise HTTPException(status_code=404, detail="Target version not found")

    # 读取原文件确定 snapshot_dir
    artifact_path = Path(artifact.path)
    snapshot_dir = str(artifact_path.parent / ".snapshots")

    # 创建新版本（内容来自目标版本）
    content = target_version["content"]
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    new_version = artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=content_hash,
        snapshot_dir=snapshot_dir,
        note=req.note,
    )

    return {
        "restored_from": req.version_num,
        "new_version": new_version,
    }


class UpdateArtifactRequest(BaseModel):
    """更新产物内容请求体（Phase 2 M2：apply edit）。"""
    base_hash: str
    content: str
    note: str = "edit"


@router.put("/{artifact_id}")
async def update_artifact_content(
    session_id: str, artifact_id: str, req: UpdateArtifactRequest
) -> dict:
    """原子替换产物内容，创建新版本。

    - 验证 base_hash 与当前文件匹配（乐观并发控制）
    - 冲突 → 409 Conflict
    - 超限/不存在 → 400/404
    """
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        new_version = await artifact_version_repo.apply_edit(
            artifact_id=artifact_id,
            artifact_path=artifact.path,
            base_hash=req.base_hash,
            new_content=req.content,
            note=req.note,
        )
    except artifact_version_repo.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"version": new_version}
