"""API 路由 dispatch（P2 双轨）。

``API_MODE`` 环境变量决定走哪条路径：

- ``hex``（默认）：加载 ``hex_routes``，调用 ChatService
- ``legacy``：加载 ``legacy_routes``，保留 P0/P1 行为（一键回滚）

注意
----
hex 路径只覆盖核心 ``/chat`` 端点（走 ChatService），
legacy 路径覆盖全部端点（/chat、/sessions、/memory、/evolution、/interrupt）。
在 hex 模式下，``/chat`` 由 hex_routes 提供，其它端点暂不提供
（这是 P2 末的有意收窄，P3+ 逐步迁移）。
"""

import os

_API_MODE = os.environ.get("API_MODE", "hex").lower()

if _API_MODE == "hex":
    from backend.api.hex_routes import router  # noqa: F401, E402, PLC0415
elif _API_MODE == "legacy":
    from backend.api.legacy_routes import router  # noqa: F401, E402, PLC0415
else:
    raise ValueError(f"API_MODE must be 'hex' or 'legacy', got: {_API_MODE!r}")
