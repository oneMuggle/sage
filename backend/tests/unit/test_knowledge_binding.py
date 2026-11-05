"""M2-Task 1 — KnowledgeBinding 数据模型测试。

``KnowledgeBinding`` 是专家知识绑定的唯一 schema 来源：CRUD 路由
（Task 2）用它校验请求，``AgentProfile.knowledge_bindings``（dataclass
中的 ``List[Dict]``）用它的 ``model_dump()`` 落库，检索路由层（Task 3）
用 ``source_type`` 决定扇出目标。

锁定的契约:

1. 五种 ``source_type`` 全部可通过 ``model_validate`` 往返；
2. 未知 source_type / 未知字段 → ValidationError（``extra='forbid'``
   用 ``class Config`` 写法，pydantic v1/v2 双兼容，见
   ``test_workspace_pydantic_v1_compat.py``）；
3. ``id`` / ``created_at`` 有默认值且唯一；
4. 必填文本字段拒绝空串。
"""

import pytest
from pydantic import ValidationError

from backend.agents.knowledge_binding import KNOWLEDGE_SOURCE_TYPES, KnowledgeBinding

pytestmark = pytest.mark.unit

BASE = {
    "agent_id": "sp_writer",
    "source_type": "wiki_project",
    "source_id": "proj_123",
    "name": "写作 Wiki",
}


@pytest.mark.parametrize("source_type", KNOWLEDGE_SOURCE_TYPES)
def test_each_source_type_roundtrips(source_type):
    binding = KnowledgeBinding(**{**BASE, "source_type": source_type})

    assert binding.source_type == source_type
    restored = KnowledgeBinding.model_validate(binding.model_dump())
    assert restored == binding


def test_defaults_generate_short_unique_id_and_timestamp():
    first = KnowledgeBinding(**BASE)
    second = KnowledgeBinding(**BASE)

    assert len(first.id) == 12
    int(first.id, 16)  # 十六进制短 hash
    assert first.id != second.id
    assert first.created_at > 0
    assert first.filters == {}


def test_filters_roundtrip():
    binding = KnowledgeBinding(**BASE, filters={"tag": "style", "prefix": "wiki/writing/"})

    dumped = binding.model_dump()
    assert dumped["filters"] == {"tag": "style", "prefix": "wiki/writing/"}


def test_unknown_source_type_rejected():
    with pytest.raises(ValidationError):
        KnowledgeBinding(**{**BASE, "source_type": "lancedb"})


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        KnowledgeBinding(**BASE, surprise="field")


@pytest.mark.parametrize("field", ["agent_id", "source_id", "name"])
def test_required_text_fields_reject_empty_strings(field):
    with pytest.raises(ValidationError):
        KnowledgeBinding(**{**BASE, field: ""})


def test_created_at_rejects_non_numeric_string():
    with pytest.raises(ValidationError):
        KnowledgeBinding(**BASE, created_at="yesterday")
