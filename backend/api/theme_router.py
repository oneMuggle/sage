"""CSS 主题 API 路由"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.theme_storage import ThemeStorage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["theme"])

# Use ThemeStorage's default (which honors SAGE_USER_DATA_DIR when set by
# the packaged Electron app). Previously hardcoded
# `Path(__file__).parent.parent / "data" / "themes"` — that resolved to the
# bundled resources/backend/data/themes which is read-only when Sage is
# installed to C:\Program Files\Sage and raised PermissionError on save/list.
_storage = ThemeStorage()


class ThemeCssPayload(BaseModel):
    """主题 CSS 载荷"""

    id: str
    name: str = Field(min_length=1, max_length=32)
    cover: Optional[str] = None
    css: str = Field(min_length=1, max_length=8192)
    appearance: str = Field(pattern="^(light|dark)$")
    created_at: int
    updated_at: int


class DeleteRequest(BaseModel):
    """删除请求"""

    id: str


@router.post("/save")
def save_theme(payload: ThemeCssPayload) -> dict:
    """保存主题"""
    theme_id = _storage.save(payload.model_dump())
    return {"id": theme_id}


@router.get("/list")
def list_themes() -> List[dict]:
    """列出所有主题"""
    return _storage.list()


@router.post("/delete")
def delete_theme(req: DeleteRequest) -> dict:
    """删除主题"""
    ok = _storage.delete(req.id)
    return {"ok": ok}


@router.get("/get/{theme_id}")
def get_theme(theme_id: str) -> dict:
    """获取单个主题"""
    data = _storage.get(theme_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Theme not found")
    return data
