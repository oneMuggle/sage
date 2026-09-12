"""能力注册表 — 集中管理所有多模态能力"""

from __future__ import annotations

from typing import Dict, List, Optional

from .capability import AICapability, CapabilityKind


class CapabilityRegistry:
    """能力注册表"""

    _capabilities: Dict[CapabilityKind, AICapability] = {}

    @classmethod
    def register(cls, capability: AICapability) -> None:
        cls._capabilities[capability.kind] = capability

    @classmethod
    def get(cls, kind: CapabilityKind) -> Optional[AICapability]:
        return cls._capabilities.get(kind)

    @classmethod
    def available(cls) -> List[CapabilityKind]:
        """返回已配置可用的能力列表（load_config 返回非 None）"""
        return [k for k, cap in cls._capabilities.items()
                if cap.load_config() is not None]

    @classmethod
    def all_kinds(cls) -> List[CapabilityKind]:
        return list(cls._capabilities.keys())


def register_all_capabilities() -> None:
    """注册所有多模态能力"""
    from .asr import ASRCapability
    from .image_gen import ImageGenCapability
    from .tts import TTSCapability

    CapabilityRegistry.register(TTSCapability())
    CapabilityRegistry.register(ASRCapability())
    CapabilityRegistry.register(ImageGenCapability())
