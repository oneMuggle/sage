"""AICapability 抽象基类及数据类"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class CapabilityKind(Enum):
    """多模态能力类型"""
    TTS = "tts"
    ASR = "asr"
    IMAGE_GEN = "image_gen"


@dataclass(frozen=True)
class CapabilityConfig:
    """从 settings 解析出的端点配置"""
    base_url: str
    api_key: str
    model: str
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIHttpRequest:
    """标准化的 HTTP 请求构建结果"""
    url: str
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = None       # JSON body
    data: Any = None       # FormData (multipart uploads, e.g. ASR)
    timeout: float = 60.0


@dataclass(frozen=True)
class AIHttpResponse:
    """标准化的响应"""
    status_code: int
    content: bytes
    json: Optional[Dict] = None
    content_type: str = ""


class AICapability(ABC):
    """所有多模态能力的基类 — 模板方法模式"""

    kind: CapabilityKind
    settings_slot: str  # e.g. "ttsModel", "asrModel", "imageGenModel"

    @abstractmethod
    def build_request(self, config: CapabilityConfig, **kwargs) -> AIHttpRequest:
        """构建上游 API 请求"""

    @abstractmethod
    def parse_response(self, response: AIHttpResponse, **kwargs) -> Any:
        """解析上游 API 响应"""

    async def execute(self, config: CapabilityConfig, **kwargs) -> Any:
        """模板方法：构建请求 → 发送 → 解析"""
        req = self.build_request(config, **kwargs)
        async with httpx.AsyncClient() as client:
            raw = await client.request(
                method=req.method,
                url=req.url,
                headers=req.headers,
                json=req.body,
                data=req.data,
                timeout=req.timeout,
            )
            is_json = raw.headers.get("content-type", "").startswith("application/json")
            resp = AIHttpResponse(
                status_code=raw.status_code,
                content=raw.content,
                json=raw.json() if is_json else None,
                content_type=raw.headers.get("content-type", ""),
            )
        return self.parse_response(resp, **kwargs)

    def load_config(self) -> Optional[CapabilityConfig]:
        """从 app_settings 读取本能力的端点配置"""
        from backend.data.settings_repo import SettingsRepository
        raw = SettingsRepository().get_json("app_settings")
        if not raw:
            return None
        selection = (raw.get("modelSelections") or {}).get(self.settings_slot)
        if not selection or not selection.get("endpointId"):
            return None
        for ep in raw.get("endpoints", []):
            if ep["id"] == selection["endpointId"]:
                return CapabilityConfig(
                    base_url=ep["baseUrl"].rstrip("/"),
                    api_key=ep.get("apiKey") or "",
                    model=selection.get("modelId") or ep.get("modelId") or "",
                )
        return None
