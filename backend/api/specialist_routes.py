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

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter()
logger = logging.getLogger(__name__)


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

    - 200 + ``{"id": <new_id>, "name": <display_name>}``
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


__all__ = ["router"]
