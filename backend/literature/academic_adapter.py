"""把 SiteProfile 包装成现有 AcademicSiteAdapter 协议要求的形状。"""

from __future__ import annotations

from typing import Any

from .guidance import render_search_guidance
from .models import SiteProfile, render_search_url


class ProfileBackedAdapter:
    """Profile 驱动的站点适配器；不 import skills 层，靠 duck typing。"""

    def __init__(self, profile: SiteProfile):
        self._profile = profile

    @property
    def name(self) -> str:
        return self._profile.id

    @property
    def profile(self) -> SiteProfile:
        return self._profile

    def build_search_url(self, query: str, **kwargs: Any) -> str:
        return render_search_url(
            self._profile, query, limit=int(kwargs.get("limit", 10))
        )

    def render_guidance(self, query: str, **kwargs: Any) -> str:
        return render_search_guidance(self._profile, query, **kwargs)
