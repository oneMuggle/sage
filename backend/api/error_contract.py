"""
API 错误契约 (S7-2, P7)

本模块是 legacy 路由错误响应信封的单一来源, 并记录双轨契约现状与
迁移方向 —— 避免新增端点时再发明第三种错误形状。

现行两条 wire 契约 (前端同时兼容):

1. **legacy 信封** — ``error_json()`` / 既有 200+error 端点:

       HTTP <status>            (新式, 优先)
       {"ok": false, "error": "<机器码>", "message": "<人读文案>", ...extra}

   前端 ``invoke`` 漏斗 (desktopInvoke) 把非 2xx 的 status 解析进
   ``InvokeError.status_code``, 错误码按 ``error`` 字段分支。

2. **hex 契约** — ``HTTPException(status_code=4xx/5xx, detail=...)``:

       HTTP 4xx/5xx + {"detail": "<人读文案或对象>"}

迁移方向: **新端点一律走 HTTP 状态码 + legacy 信封** (error_json);
历史 200+error 端点保持原样 (改状态码会破坏前端既有分支), 逐步迁移。
不要发明第三种形状。
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


def error_json(
    status_code: int,
    code: str,
    message: str,
    **extra: object,
) -> JSONResponse:
    """构造 legacy 错误信封响应: HTTP 状态码 + {ok:false, error, message}。

    Args:
        status_code: HTTP 状态码 (4xx 客户端错误 / 5xx 上游或服务端错误)
        code: 机器可读错误码 (如 "compact_in_progress")
        message: 人读文案 (前端 toast 直接展示)
        **extra: 附加字段 (如 compact 的 before/after/removed)
    """
    payload: dict = {"ok": False, "error": code, "message": message}
    payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)
