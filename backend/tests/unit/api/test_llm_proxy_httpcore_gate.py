"""R117 — llm_proxy httpcore 版本门单元测试（1.0 系列放行语义）。

背景：原实现用精确相等 ``!= "1.0.9"`` 做门禁，任何补丁波动（旧锁解析出
1.0.0~1.0.8、新环境升到 1.0.10+）都会让 LLM 代理的固定 IP 传输整体不可用。
修复后按 (major, minor) 系列门禁：1.0.x 放行，0.x / 1.1+ 拒绝。
与 upstream_security 的同款门禁保持一致语义。
"""

from __future__ import annotations

import httpcore
import pytest

import backend.api.llm_proxy_routes as lpr

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
@pytest.mark.parametrize("version", ["1.0.0", "1.0.9", "1.0.12"])
async def test_client_accepts_httpcore_1_0_series(monkeypatch, version):
    monkeypatch.setattr(httpcore, "__version__", version)
    client = lpr._client_for_resolved_address("93.184.216.34")
    try:
        backend = client._transport._pool._network_backend
        assert isinstance(backend, lpr._FixedIPNetworkBackend)
    finally:
        await client.aclose()


@pytest.mark.parametrize("version", ["0.15.0", "1.1.0", "2.0.0"])
def test_client_rejects_out_of_series_httpcore(monkeypatch, version):
    monkeypatch.setattr(httpcore, "__version__", version)
    with pytest.raises(RuntimeError, match="Unsupported httpcore version"):
        lpr._client_for_resolved_address("93.184.216.34")
