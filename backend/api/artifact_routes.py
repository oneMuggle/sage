# backend/api/artifact_routes.py
"""Artifact(产物)相关 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.data import artifact_reader, artifact_repo

router = APIRouter(prefix="/sessions/{session_id}/artifacts", tags=["artifacts"])


@router.get("")
def list_artifacts(session_id: str) -> dict:
    """列出指定 session 的所有产物。"""
    items = artifact_repo.list_artifacts(session_id)
    return {"artifacts": [a.to_dict() for a in items]}


@router.get("/{artifact_id}/content")
def get_artifact_content(session_id: str, artifact_id: str) -> dict:
    """读取产物内容:文本返回 content,图片返回 data_url。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.kind == "image":
        return artifact_reader.read_image(artifact_id)
    return artifact_reader.read_text(artifact_id)


@router.post("/{artifact_id}/reveal")
def reveal_artifact(session_id: str, artifact_id: str) -> dict:
    """在系统文件管理器中显示产物。"""
    artifact = artifact_repo.get_artifact(artifact_id)
    if artifact is None or artifact.session_id != session_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return artifact_reader.reveal_in_file_manager(artifact_id)
