"""验证 jieba 中文分词在记忆搜索中的应用。"""

import tempfile

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import SemanticMemory

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_db() -> Database:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


# ==================== EpisodicMemory 中文搜索 ====================


def test_episodic_chinese_search_single_word(tmp_db: Database) -> None:
    """搜索单个中文词应能匹配包含该词的记录。"""
    em = EpisodicMemory(tmp_db)
    em.save("用户喜欢火锅", importance=5)
    em.save("用户偏好日料", importance=5)

    # 搜索 "火锅" 应只匹配第一条
    results = em.search("火锅")
    assert len(results) >= 1
    assert any("火锅" in r["content"] for r in results)


def test_episodic_chinese_search_multi_word(tmp_db: Database) -> None:
    """搜索多个中文词应匹配包含任一词的记录。"""
    em = EpisodicMemory(tmp_db)
    em.save("用户喜欢火锅", importance=5)
    em.save("明天开会讨论项目", importance=5)
    em.save("周末去爬山", importance=5)

    # 搜索 "火锅 开会" 应匹配前两条
    results = em.search("火锅 开会")
    contents = [r["content"] for r in results]
    assert any("火锅" in c for c in contents)
    assert any("开会" in c for c in contents)


def test_episodic_chinese_search_no_match(tmp_db: Database) -> None:
    """搜索不存在的词应返回空。"""
    em = EpisodicMemory(tmp_db)
    em.save("用户喜欢火锅", importance=5)

    results = em.search("区块链")
    assert len(results) == 0


# ==================== SemanticMemory 中文搜索 ====================


def test_semantic_chinese_search_single_word(tmp_db: Database) -> None:
    """语义记忆搜索单个中文词。"""
    sm = SemanticMemory(tmp_db)
    sm.save("Python 是一种编程语言")
    sm.save("JavaScript 用于前端开发")

    results = sm.search("编程语言")
    assert len(results) >= 1
    assert any("Python" in r["content"] for r in results)


def test_semantic_chinese_search_multi_word(tmp_db: Database) -> None:
    """语义记忆搜索多个中文词。"""
    sm = SemanticMemory(tmp_db)
    sm.save("Python 是一种编程语言")
    sm.save("SQLite 是嵌入式数据库")
    sm.save("React 是前端框架")

    # 搜索 "数据库 前端" 应匹配后两条
    results = sm.search("数据库 前端")
    contents = [r["content"] for r in results]
    assert any("数据库" in c for c in contents)
    assert any("前端" in c for c in contents)


def test_semantic_empty_query_returns_recent(tmp_db: Database) -> None:
    """空查询应返回最近记录。"""
    sm = SemanticMemory(tmp_db)
    sm.save("第一条")
    sm.save("第二条")

    results = sm.search("")
    assert len(results) == 2


def test_semantic_search_with_tags(tmp_db: Database) -> None:
    """带标签筛选的搜索。"""
    sm = SemanticMemory(tmp_db)
    sm.save("Python 教程", tags=["python", "教程"])
    sm.save("JavaScript 教程", tags=["js", "教程"])

    results = sm.search("教程", tags=["python"])
    assert len(results) >= 1
    assert all("python" in r.get("tags", []) for r in results)
