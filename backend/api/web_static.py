"""Web 模式静态资源的 MIME 兜底。

Vite 产物的入口是 ``<script type="module">``，浏览器会对其做严格 MIME
检查。Windows 上 ``mimetypes`` 初始化时会读取注册表里的 Content Type，
部分内网机器的历史软件把 ``.js`` 登记成 ``text/plain``；Starlette 的
``StaticFiles`` 据此下发 ``Content-Type: text/plain``，浏览器拒绝执行，
网页模式整页白屏（表现为 index.html 里 8 秒后的"当前浏览器无法加载
Sage"提示）。
"""

from __future__ import annotations

import mimetypes

# 只覆盖浏览器对 MIME 敏感的资源类型；其余扩展名仍走系统/注册表映射。
WEB_STATIC_MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
}


def register_web_static_mime_types() -> None:
    """把 Web 资源扩展名强制映射为标准 MIME，覆盖注册表读到的值。"""
    for suffix, mime_type in WEB_STATIC_MIME_TYPES.items():
        mimetypes.add_type(mime_type, suffix)
