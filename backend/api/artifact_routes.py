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
    if suffix == "html" or suffix == "htm":
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
