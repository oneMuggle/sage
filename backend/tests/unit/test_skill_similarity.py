"""SkillSimilarityService 单元测试。

覆盖：
- cosine_similarity 纯 Python 实现
- _skill_text 拼接逻辑
- find_duplicates TF-IDF 降级路径
- 单例管理
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from backend.skills.similarity import (
    SkillSimilarityService,
    _skill_text,
    cosine_similarity,
    get_similarity_service,
    reset_similarity_service,
)

# ------------------------------------------------------------------ #
# cosine_similarity
# ------------------------------------------------------------------ #

class TestCosineSimilarity:
    """纯 Python 余弦相似度测试。"""

    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_dimension_mismatch(self):
        assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0

    def test_partial_similarity(self):
        a = [1.0, 0.0]
        b = [1.0, 1.0]
        expected = 1.0 / math.sqrt(2)
        assert cosine_similarity(a, b) == pytest.approx(expected)


# ------------------------------------------------------------------ #
# _skill_text
# ------------------------------------------------------------------ #

class TestSkillText:
    """技能文本拼接测试。"""

    def test_full_skill(self):
        skill = {
            "name": "test-skill",
            "description": "搜索学术论文",
            "when_to_use": "用户需要查找论文时",
            "triggers": ["搜索", "论文"],
        }
        text = _skill_text(skill)
        assert "搜索学术论文" in text
        assert "用户需要查找论文时" in text
        assert "搜索" in text
        assert "论文" in text

    def test_empty_skill(self):
        assert _skill_text({}) == ""

    def test_description_only(self):
        skill = {"description": "仅描述"}
        assert _skill_text(skill) == "仅描述"

    def test_triggers_as_string(self):
        skill = {"triggers": "search query"}
        text = _skill_text(skill)
        assert "search query" in text


# ------------------------------------------------------------------ #
# SkillSimilarityService
# ------------------------------------------------------------------ #

class TestSkillSimilarityService:
    """相似度服务测试。"""

    def test_find_duplicates_empty(self):
        service = SkillSimilarityService()
        assert service._find_duplicates_tfidf([], 0.85) == []

    def test_find_duplicates_single(self):
        service = SkillSimilarityService()
        skills = [{"name": "only-one", "description": "唯一技能"}]
        assert service._find_duplicates_tfidf(skills, 0.85) == []

    def test_tfidf_finds_similar_pair(self):
        """TF-IDF 应能识别描述高度相似的技能对（需要 sklearn）。"""
        pytest.importorskip("sklearn")
        service = SkillSimilarityService(embed_config=None)
        skills = [
            {
                "name": "academic-search",
                "description": "search academic papers and literature reviews",
                "when_to_use": "user needs to find academic papers and literature",
            },
            {
                "name": "paper-search",
                "description": "search academic papers and literature reviews",
                "when_to_use": "user needs to find academic papers and literature",
            },
            {
                "name": "code-review",
                "description": "code review and quality check tool",
                "when_to_use": "user submits code for review",
            },
        ]
        pairs = service._find_duplicates_tfidf(skills, threshold=0.5)
        similar_names = {(a, b) for a, b, _ in pairs}
        assert ("academic-search", "paper-search") in similar_names or \
               ("paper-search", "academic-search") in similar_names

    def test_tfidf_no_false_positive(self):
        """TF-IDF 不应将不相似的技能标记为重复（需要 sklearn）。"""
        pytest.importorskip("sklearn")
        service = SkillSimilarityService(embed_config=None)
        skills = [
            {"name": "search", "description": "academic paper search and literature review"},
            {"name": "code-review", "description": "code review and quality check tool for developers"},
        ]
        pairs = service._find_duplicates_tfidf(skills, threshold=0.85)
        assert len(pairs) == 0

    @pytest.mark.asyncio()
    async def test_find_duplicates_with_mock_embedding(self):
        """mock embedding 端点测试 embedding 路径。"""
        mock_config = MagicMock()
        mock_config.dim = 3
        service = SkillSimilarityService(embed_config=mock_config)

        sample_skills = [
            {
                "name": "academic-search",
                "description": "搜索学术论文",
                "when_to_use": "用户需要查找学术论文时",
                "triggers": ["搜索", "论文"],
            },
            {
                "name": "paper-search",
                "description": "检索学术论文",
                "when_to_use": "用户需要检索学术论文时",
                "triggers": ["检索", "论文"],
            },
            {
                "name": "code-review",
                "description": "代码审查工具",
                "when_to_use": "用户提交代码需要审查时",
                "triggers": ["代码", "审查"],
            },
        ]

        # mock embedding：前两个技能向量相近，第三个不同
        async def mock_embed(text):
            if "搜索学术论文" in text or "检索学术论文" in text:
                return [1.0, 0.1, 0.0]
            return [0.0, 0.0, 1.0]

        service.compute_embedding = mock_embed

        pairs = await service.find_duplicates(sample_skills, threshold=0.85)
        assert len(pairs) >= 1
        pair_names = {(a, b) for a, b, _ in pairs}
        assert ("academic-search", "paper-search") in pair_names

    @pytest.mark.asyncio()
    async def test_fallback_to_tfidf_on_embedding_failure(self):
        """embedding 全部失败时降级到 TF-IDF（需要 sklearn）。"""
        pytest.importorskip("sklearn")
        mock_config = MagicMock()
        mock_config.dim = 3
        service = SkillSimilarityService(embed_config=mock_config)

        sample_skills = [
            {
                "name": "academic-search",
                "description": "search academic papers and literature reviews",
                "when_to_use": "user needs to find academic papers",
            },
            {
                "name": "paper-search",
                "description": "search academic papers and literature reviews",
                "when_to_use": "user needs to find academic papers",
            },
        ]

        async def mock_embed_fail(text):
            return None

        service.compute_embedding = mock_embed_fail

        pairs = await service.find_duplicates(sample_skills, threshold=0.5)
        assert isinstance(pairs, list)
        assert len(pairs) >= 1


# ------------------------------------------------------------------ #
# Singleton
# ------------------------------------------------------------------ #

class TestSingleton:
    """单例管理测试。"""

    def test_get_similarity_service_returns_instance(self):
        reset_similarity_service()
        service = get_similarity_service()
        assert isinstance(service, SkillSimilarityService)

    def test_reset_clears_singleton(self):
        reset_similarity_service()
        s1 = get_similarity_service()
        reset_similarity_service()
        s2 = get_similarity_service()
        assert s1 is not s2
