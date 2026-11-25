"""SkillSimilarityService - 技能相似度计算（M1 结构化去重）

用 embedding 向量化技能的 description + when_to_use + triggers，
计算余弦相似度，找出重叠的技能对。作为 ConsolidationService.scan()
的前置预筛，替代纯 LLM 文本分析。

降级策略：embedding 端点不可用时退化为 TF-IDF 关键词匹配。

设计要点
--------

- **best-effort**：所有异常只 warning，不抛错 —— 去重预筛是增强能力，
  不得阻塞巡检主流程。
- **缓存**：同一会话内 embedding 缓存，避免重复请求。
- **无外部依赖**：复用项目已有的 embedding HTTP 端点（wiki/embeddings.py）。
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 相似度阈值（高于此值视为疑似重复）
DEFAULT_DUPLICATE_THRESHOLD = 0.85
# embedding 缓存大小（LRU）
EMBEDDING_CACHE_SIZE = 200


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度（纯 Python，无 numpy 依赖）。

    复用 wiki/vectorstore.py 的算法，维度不一致时返回 0.0。
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))  # noqa: B905
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _skill_text(skill: Dict[str, Any]) -> str:
    """拼接技能的语义描述文本（embedding 输入）。"""
    parts = []
    desc = skill.get("description", "")
    if desc:
        parts.append(desc)
    when = skill.get("when_to_use", "")
    if when:
        parts.append(when)
    triggers = skill.get("triggers", [])
    if triggers:
        parts.append(" ".join(triggers) if isinstance(triggers, list) else str(triggers))
    return "\n".join(parts)


class SkillSimilarityService:
    """基于 embedding 的技能相似度计算。

    Example:
        >>> service = SkillSimilarityService(embed_config=my_cfg)
        >>> pairs = await service.find_duplicates(skills)
        >>> pairs
        [("skill-a", "skill-b", 0.91), ...]
    """

    def __init__(
        self,
        embed_config: Any = None,
        threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    ) -> None:
        self.embed_config = embed_config
        self.threshold = threshold
        self._cache: OrderedDict[str, List[float]] = OrderedDict()

    async def compute_embedding(self, text: str) -> Optional[List[float]]:
        """计算文本的 embedding 向量。

        优先使用项目已有的 embedding HTTP 端点；
        端点不可用或请求失败返回 None。
        """
        if not text or not self.embed_config:
            return None

        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]

        try:
            from backend.services.http_client import http_post
            from backend.wiki.embeddings import (
                build_embed_request,
                parse_embed_response,
            )

            req = build_embed_request(self.embed_config, [text])
            response = await http_post(req.url, req.headers, req.body)
            vectors = parse_embed_response(response, self.embed_config.dim)
            if not vectors:
                return None
            vec = vectors[0]
            self._cache[text] = vec
            if len(self._cache) > EMBEDDING_CACHE_SIZE:
                self._cache.popitem(last=False)
            return vec
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.debug("embedding 计算失败（将降级到 TF-IDF）: %s", exc)
            return None

    async def find_duplicates(
        self,
        skills: List[Dict[str, Any]],
        threshold: Optional[float] = None,
    ) -> List[Tuple[str, str, float]]:
        """找出相似度超过阈值的技能对。

        Args:
            skills: [{name, description, when_to_use, triggers, ...}]
            threshold: 相似度阈值，缺省用实例默认值

        Returns:
            [(name_a, name_b, similarity), ...] 按相似度降序
        """
        if len(skills) < 2:
            return []

        thresh = threshold if threshold is not None else self.threshold

        # 尝试 embedding 路径
        if self.embed_config is not None:
            result = await self._find_duplicates_embedding(skills, thresh)
            if result is not None:
                return result

        # 降级到 TF-IDF
        return self._find_duplicates_tfidf(skills, thresh)

    async def _find_duplicates_embedding(
        self,
        skills: List[Dict[str, Any]],
        threshold: float,
    ) -> Optional[List[Tuple[str, str, float]]]:
        """基于 embedding 的相似度计算。embedding 全部失败返回 None（触发降级）。"""
        embeddings: Dict[str, List[float]] = {}
        for skill in skills:
            name = skill.get("name", "")
            if not name:
                continue
            text = _skill_text(skill)
            vec = await self.compute_embedding(text)
            if vec is not None:
                embeddings[name] = vec

        # 全部失败 → 返回 None 让调用方降级
        if not embeddings:
            return None

        # 计算两两相似度
        pairs: List[Tuple[str, str, float]] = []
        names = list(embeddings.keys())
        for i, name_a in enumerate(names):
            vec_a = embeddings[name_a]
            for name_b in names[i + 1:]:
                vec_b = embeddings[name_b]
                sim = cosine_similarity(vec_a, vec_b)
                if sim >= threshold:
                    pairs.append((name_a, name_b, round(sim, 4)))

        return sorted(pairs, key=lambda x: -x[2])

    def _find_duplicates_tfidf(
        self,
        skills: List[Dict[str, Any]],
        threshold: float,
    ) -> List[Tuple[str, str, float]]:
        """TF-IDF 降级方案（无 embedding 端点时使用）。"""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            logger.debug("sklearn 不可用，无法进行 TF-IDF 降级")
            return []

        texts = []
        names = []
        for skill in skills:
            name = skill.get("name", "")
            if not name:
                continue
            text = _skill_text(skill)
            if not text:
                continue
            texts.append(text)
            names.append(name)

        if len(texts) < 2:
            return []

        try:
            vectorizer = TfidfVectorizer()
            matrix = vectorizer.fit_transform(texts)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TF-IDF 计算失败: %s", exc)
            return []

        pairs: List[Tuple[str, str, float]] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                row_i = matrix.getrow(i)
                row_j = matrix.getrow(j)
                dot = (row_i.multiply(row_j)).sum()
                norm_i = math.sqrt((row_i.multiply(row_i)).sum())
                norm_j = math.sqrt((row_j.multiply(row_j)).sum())
                sim = 0.0 if norm_i == 0 or norm_j == 0 else dot / (norm_i * norm_j)
                if sim >= threshold:
                    pairs.append((names[i], names[j], round(float(sim), 4)))

        return sorted(pairs, key=lambda x: -x[2])


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_similarity_service: Optional[SkillSimilarityService] = None


def get_similarity_service() -> SkillSimilarityService:
    """获取全局 SkillSimilarityService 单例。

    惰性初始化：首次调用时尝试获取 embedding 配置；
    配置不可用则创建无 embedding 的实例（自动降级到 TF-IDF）。
    """
    global _similarity_service
    if _similarity_service is None:
        embed_config = _try_get_embed_config()
        _similarity_service = SkillSimilarityService(embed_config=embed_config)
    return _similarity_service


def reset_similarity_service() -> None:
    """重置单例（测试用）。"""
    global _similarity_service
    _similarity_service = None


def _try_get_embed_config() -> Any:
    """尝试获取 embedding 配置（best-effort）。"""
    try:
        from backend.services.attachment_rag import get_embed_config
        return get_embed_config()
    except Exception as exc:  # noqa: BLE001
        logger.debug("embedding 配置获取失败（将降级到 TF-IDF）: %s", exc)
        return None
