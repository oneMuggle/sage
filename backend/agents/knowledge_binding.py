"""M2-Task 1 — 知识绑定数据模型（spec §6.1）。

单一真相源，三处消费：

1. CRUD 路由（Task 2）用它的 ``model_validate`` 校验请求；
2. ``AgentProfile.knowledge_bindings``（``List[Dict]``）用它的
   ``model_dump`` 落库 / 反序列化；
3. 检索路由层（Task 3）按 ``source_type`` 扇出到对应存储。

锁定的契约:

- ``source_type`` 为五选一的字面量（wiki_project / zotero_collection /
  project_material / workspace_fts / specialist_private）。
- 严格 ``extra='forbid'``，避免脏字段渗入 ``AgentProfile`` 持久化。
- ``id`` 为 12 位十六进制短 hash（uuid4 截断），保证唯一性与稳定长度。
- ``created_at`` 默认当前 Unix 秒时间戳。

Pydantic v1/v2 双兼容:

- 使用 ``class Config: extra = "forbid"``（``ConfigDict`` 在 v1 下被静默
  忽略，见 ``test_workspace_pydantic_v1_compat.py``）。
- 所有类型注解用 ``from typing import ...``，避免 ``list[...]`` 仅在
  3.9+ 可用的陷阱。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Literal, Tuple

from pydantic import BaseModel, Field

KNOWLEDGE_SOURCE_TYPES: Tuple[str, ...] = (
    "wiki_project",
    "zotero_collection",
    "project_material",
    "workspace_fts",
    "specialist_private",
)

#: 与 ``KNOWLEDGE_SOURCE_TYPES`` 一致，用于静态类型标注。
KnowledgeSourceType = Literal[
    "wiki_project",
    "zotero_collection",
    "project_material",
    "workspace_fts",
    "specialist_private",
]

#: 绑定 id 长度（uuid4 hex 截断为 12，与内部去重 / 日志展示权衡）。
_BINDING_ID_LEN = 12


def _new_binding_id() -> str:
    return uuid.uuid4().hex[:_BINDING_ID_LEN]


def _now_unix() -> int:
    return int(time.time())


class KnowledgeBinding(BaseModel):
    """一条专家知识绑定。

    ``agent_id`` 同时承担「归属专家」与「路由到对应存储」双重语义——
    ``specialist_private`` 用它定位 ``~/.sage/specialists/<id>/vectors.json``，
    其余 ``source_type`` 则用 ``source_id`` 标识外部存储实例。
    """

    id: str = Field(
        default_factory=_new_binding_id, min_length=1, max_length=64,
        description="绑定唯一 id（默认 12 位 hex 短 hash）。",
    )
    agent_id: str = Field(min_length=1, max_length=64, description="所属专家 id。")
    source_type: KnowledgeSourceType
    source_id: str = Field(
        min_length=1, max_length=1024,
        description=(
            "外部源标识：wiki_project → project_id；zotero_collection → "
            "collection_key；project_material → project_id；workspace_fts → "
            "workspace 路径；specialist_private → 通常等于 agent_id。"
        ),
    )
    name: str = Field(min_length=1, max_length=200, description="展示名。")
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "可选过滤条件（按 source_type 语义不同）：如 wiki 的 tag/路径前缀、"
            "zotero 的年份范围。"
        ),
    )
    created_at: int = Field(
        default_factory=_now_unix, description="绑定创建时间（Unix 秒）。",
    )

    class Config:  # noqa: D401 — Pydantic v1/v2 双兼容配置
        extra = "forbid"
