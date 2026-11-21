"""文献调研领域层：站点 profile、检索结果模型与适配器。

设计约束：本包不依赖 backend.tools / backend.api；站点差异放在 profile
（YAML）里，而不是代码分支里。
"""

from .models import (
    PaperRecord,
    SiteProfile,
    SiteProfileError,
    is_logged_in,
    profile_from_dict,
    render_search_url,
)

__all__ = [
    "PaperRecord",
    "SiteProfile",
    "SiteProfileError",
    "is_logged_in",
    "profile_from_dict",
    "render_search_url",
]
