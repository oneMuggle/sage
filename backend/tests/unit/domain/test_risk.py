"""R143 — 工具风险分级领域模型单元测试。

覆盖：classify 五级优先链（overrides > declared > 按名兜底表 > 元数据
启发式 > READ 兜底）、is_consequential、RiskClass 取值、兜底表内容。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.domain.risk import (
    EXTERNAL_TOOLS,
    SHELL_TOOLS,
    WRITE_TOOLS,
    RiskClass,
    classify,
    is_consequential,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 优先链
# ---------------------------------------------------------------------------


def test_override_wins_over_everything():
    def override(name):
        return RiskClass.READ  # 把 bash 降级为 READ

    result = classify(
        "bash",
        metadata={"requires_approval": True},
        overrides=override,
        declared={},
    )
    assert result == RiskClass.READ


def test_override_returning_none_defers():
    result = classify(
        "web_search",
        metadata=None,
        overrides=lambda name: None,
        declared={"web_search": RiskClass.EXTERNAL},
    )
    assert result == RiskClass.EXTERNAL  # 覆盖未命中 → 交给 declared


def test_declared_beats_base_table_and_metadata():
    result = classify(
        "web_search",
        metadata={"requires_approval": True},
        declared={"web_search": RiskClass.READ},
    )
    assert result == RiskClass.READ


def test_base_table_entries():
    assert classify("write_file") == RiskClass.WRITE_LOCAL
    assert classify("memory_save") == RiskClass.WRITE_LOCAL
    assert classify("bash") == RiskClass.EXEC
    assert classify("web_search") == RiskClass.EXTERNAL
    assert classify("web_fetch") == RiskClass.EXTERNAL
    assert classify("http_download") == RiskClass.EXTERNAL


def test_metadata_requires_approval_object_attribute():
    tool = SimpleNamespace(requires_approval=True)
    assert classify("mcp_dynamic", metadata=tool) == RiskClass.EXTERNAL


def test_metadata_requires_approval_mapping_key():
    assert classify("mcp_dynamic", metadata={"requires_approval": True}) == RiskClass.EXTERNAL
    assert classify("mcp_dynamic", metadata={"requires_approval": False}) == RiskClass.READ


def test_unknown_tool_defaults_to_read():
    assert classify("totally_unknown") == RiskClass.READ


# ---------------------------------------------------------------------------
# is_consequential / 常量
# ---------------------------------------------------------------------------


def test_is_consequential():
    assert is_consequential(RiskClass.READ) is False
    for risk in (RiskClass.WRITE_LOCAL, RiskClass.EXEC, RiskClass.EXTERNAL):
        assert is_consequential(risk) is True


def test_risk_class_values():
    assert RiskClass.READ == "read"
    assert RiskClass.WRITE_LOCAL == "write_local"
    assert RiskClass.EXEC == "exec"
    assert RiskClass.EXTERNAL == "external"


def test_fallback_tables_content():
    assert frozenset({"write_file", "memory_save"}) == WRITE_TOOLS
    assert frozenset({"bash"}) == SHELL_TOOLS
    assert frozenset({"web_search", "web_fetch", "http_download"}) == EXTERNAL_TOOLS
