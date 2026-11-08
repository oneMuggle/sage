"""sage-guide 专家端到端流程集成测试（M5）。

覆盖 M5 测试矩阵的「提问 → 检索注入 → 读配置 → 写配置 → 回读」链路：

1. profile 种子：工具白名单、知识绑定、记忆隔离策略、权限档位
2. sage_docs 检索：真实 FTS5 + 中文分词，命中携带完整 ``loc``
3. KnowledgeRetriever 路由：``sage_docs`` 绑定经默认检索器产出 ``RetrievedChunk``
4. 配置读写回读：``read_sage_config`` → ``update_sage_config`` → 再读

不发真实 LLM 请求（与 §133 测试矩阵一致：假 runner / 真实工具）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from backend.agents.knowledge_binding import KnowledgeBinding
from backend.agents.knowledge_retriever import KnowledgeRetriever, _search_sage_docs
from backend.agents.profiles import create_default_agents
from backend.domain.tool_names import CONFIG_TOOLS, SELF_STATUS_TOOLS
from backend.tools.config_tool import ReadSageConfigTool, UpdateSageConfigTool

pytestmark = pytest.mark.integration


def _guide_profile():
    for profile in create_default_agents():
        if profile.id == "sage-guide":
            return profile
    raise AssertionError("sage-guide 不在默认种子中")


def _docs_root(tmp_path: Path) -> Path:
    """与单元测试一致的最小文档集：够区分两篇文档即可。"""
    root = tmp_path / "docs"
    files = {
        "user-manual/07-chat.md": (
            "# 对话\n\nSage 默认的重试次数是三次。\n\n"
            "## 重试设置\n\n在设置页面可以调整重试次数与超时时间。\n"
        ),
        "user-manual/08-settings.md": (
            "# 设置\n\n权限模式分为只读、提示、工作区写入、完全访问四种。\n"
        ),
        "technical/README.md": "# 技术手册\n\n后端服务默认监听 8765 端口。\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture()
def docs_env(tmp_path, monkeypatch):
    """把 SAGE_DOCS_DIR / SAGE_DOCS_INDEX_DIR 指向临时目录。"""
    root = _docs_root(tmp_path)
    monkeypatch.setenv("SAGE_DOCS_DIR", str(root))
    monkeypatch.setenv("SAGE_DOCS_INDEX_DIR", str(tmp_path / "index"))
    return root


# ---------------------------------------------------------------------------
# 1. Profile 种子
# ---------------------------------------------------------------------------


def test_sage_guide_profile_contract():
    profile = _guide_profile()

    assert profile.role == "specialist"
    assert profile.source == "builtin"
    assert profile.permission_mode == "workspace_write"
    assert profile.model_config.temperature == pytest.approx(0.3)
    assert profile.max_iterations == 12


def test_sage_guide_tools_cover_self_awareness_without_memory():
    """工具面：配置自省 + 状态自省 + 提问；记忆工具必须缺席（隐私边界）。"""
    tools = set(_guide_profile().tools)

    assert set(CONFIG_TOOLS).issubset(tools)
    assert set(SELF_STATUS_TOOLS).issubset(tools)
    assert "ask_user_question" in tools
    # 记忆隔离：向导不应读写用户记忆。
    assert not {"memory_search", "memory_store", "memory_list"} & tools


def test_sage_guide_memory_policy_blocks_private_reads_and_auto_extract():
    policy = _guide_profile().memory_policy

    assert policy["read_scopes"] == []
    assert policy["auto_extract"] is False


def test_sage_guide_binds_bundled_sage_docs():
    bindings = [KnowledgeBinding(**raw) for raw in _guide_profile().knowledge_bindings]

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.source_type == "sage_docs"
    assert binding.agent_id == "sage-guide"
    assert binding.source_id == "bundled"


# ---------------------------------------------------------------------------
# 2. sage_docs 检索（真实 FTS5）
# ---------------------------------------------------------------------------


def _binding() -> KnowledgeBinding:
    return KnowledgeBinding(
        id="sage-guide-docs",
        agent_id="sage-guide",
        source_type="sage_docs",
        source_id="bundled",
        name="Sage 内置文档库",
    )


def test_sage_docs_searcher_returns_source_hits_with_loc(docs_env):
    hits = _search_sage_docs(_binding(), "重试次数", None, 5)

    assert hits
    top = hits[0]
    # chunk_index 取决于标题切分，不断言具体值，只锁定前缀与定位字段。
    assert top.doc_id.startswith("user-manual/07-chat.md::")
    assert top.loc["page_path"] == "user-manual/07-chat.md"
    assert top.loc["heading"]
    assert top.loc["start_line"] >= 1
    assert isinstance(top.loc["chunk_index"], int)
    assert "重试" in top.content


def test_sage_docs_searcher_fail_open_without_docs_root(monkeypatch):
    """文档根目录解析为 None 时返回空列表 —— 知识库故障不能拖垮对话。"""
    monkeypatch.setattr(
        "backend.services.sage_docs.search.resolve_docs_root", lambda: None
    )

    assert _search_sage_docs(_binding(), "重试次数", None, 5) == []


# ---------------------------------------------------------------------------
# 3. KnowledgeRetriever 路由
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_retriever_routes_sage_docs_binding_to_fused_chunks(docs_env):
    retriever = KnowledgeRetriever()

    chunks = await retriever.retrieve([_binding()], "重试次数", limit=3)

    assert chunks
    top = chunks[0]
    assert top.source_type == "sage_docs"
    assert top.binding_name == "Sage 内置文档库"
    assert top.agent_id == "sage-guide"
    assert top.loc["page_path"] == "user-manual/07-chat.md"
    assert "重试" in top.content


def _counting_searcher():
    """返回一个可统计调用次数的 sage_docs 假检索器。"""

    def _searcher(binding, query, query_vector, limit):
        _searcher.calls += 1  # type: ignore[attr-defined]
        return []

    _searcher.calls = 0  # type: ignore[attr-defined]
    return _searcher


@pytest.mark.asyncio()
async def test_retriever_deduplicates_same_binding():
    """同一 (source_type, source_id) 的重复绑定只检索一次（去重键无 agent 维度）。"""
    searcher = _counting_searcher()
    retriever = KnowledgeRetriever(searchers={"sage_docs": searcher})

    await retriever.retrieve([_binding(), _binding()], "重试次数")

    assert searcher.calls == 1


# ---------------------------------------------------------------------------
# 4. 配置读写回读
# ---------------------------------------------------------------------------


class _MemorySettingsRepo:
    """内存版 SettingsRepository：让 read → update → read 真实往返。"""

    def __init__(self, initial: Dict[str, Any]) -> None:
        self._store: Dict[str, Any] = {"app_settings": dict(initial)}

    def get_json(self, key: str) -> Any:
        return self._store.get(key)

    def set_json(self, key: str, value: Any, category: str = "general") -> None:
        self._store[key] = value


def test_config_update_round_trip(monkeypatch):
    repo = _MemorySettingsRepo(
        {"orch": {"maxLaneIterations": 8, "maxSubagentIterations": 6}}
    )
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", lambda: repo)

    read_tool = ReadSageConfigTool()
    update_tool = UpdateSageConfigTool()

    before = read_tool.execute(section="orch")
    assert before.success is True
    # section='orch' 时 data 直接就是 orch 字典（见 ReadSageConfigTool.execute）。
    assert before.content["data"]["maxLaneIterations"] == 8

    updated = update_tool.execute(
        target="orch",
        updates={"maxLaneIterations": 12, "maxSubagentIterations": 10},
    )
    assert updated.success is True
    assert updated.content["updated_fields"] == {
        "maxLaneIterations": 12,
        "maxSubagentIterations": 10,
    }

    after = read_tool.execute(section="orch")
    assert after.success is True
    assert after.content["data"]["maxLaneIterations"] == 12
    assert after.content["data"]["maxSubagentIterations"] == 10


def test_config_update_rejects_out_of_whitelist_key(monkeypatch):
    repo = _MemorySettingsRepo({"orch": {}})
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", lambda: repo)

    result = UpdateSageConfigTool().execute(
        target="orch",
        updates={"maxIterationsCeiling": 99999},
    )

    assert result.success is False
    assert "禁止修改" in result.error
    # 拒绝路径不得落库。
    assert repo.get_json("app_settings")["orch"] == {}
