"""MemoryConflictResolver — Mem0 风格写入冲突消解（P3 scope 轴）

Mem0 的核心经验：记忆写入不应该是无脑 append。新事实进来时，先与
**同归属**的活跃记忆比对，四选一：

- ``NOOP``  — 已有等价事实（完全一致 / 近重复），跳过写入；
- ``UPDATE``— 已有同一主题但已变化的事实（高相似但不同），写新行 +
  把旧行标记 ``invalid_at``（``supersedes_id`` 指向旧行），旧行退出检索；
- ``ADD``   — 全新事实，正常写入。
  （DELETE 语义保留给 P4 反思任务，需要 LLM 判定"新事实否定旧事实"。）

归属对齐（防跨项目误伤）：候选只有在 scope + project_key 与本次写入
**完全一致**时才参与判定——A 项目的记忆永远不会被 B 项目的写入取代。

判定策略默认是确定性的字符相似度（SequenceMatcher），零依赖零延迟；
``llm_decide`` 预留 LLM 决策钩子（返回 None 时回退启发式），供后续
接 extractor 同款 LLM 客户端。

当进程内存在**语义嵌入器**（``is_semantic=True`` 的 Onnx/Model
Embedder）时，候选额外带一路语义相似度（余弦）。语义近邻只用于
**触发 UPDATE**（写新行 + 旧行失效），不触发 NOOP —— 语义相近但取值
不同的两条记忆（如"用户住在上海" vs "用户住在北京"）必须让新事实取代
旧事实，NOOP 会把过时事实留在库里。

同一理由，字面 NOOP 带额外拒绝**否定极性相反**的候选：只插入一个"不"
的句子字面仍有 0.98 以上，但事实相反，此时改判 UPDATE。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend.memory import scope as memory_scope

logger = logging.getLogger(__name__)

OP_ADD = "add"
OP_UPDATE = "update"
OP_NOOP = "noop"

#: 相似度 >= NOOP_THRESHOLD 视为同一条事实（不写）
NOOP_THRESHOLD = 0.97
#: UPDATE_THRESHOLD <= 相似度 < NOOP_THRESHOLD 视为同一事实的更新（取代）
UPDATE_THRESHOLD = 0.78
#: 语义相似度 >= SEMANTIC_UPDATE_THRESHOLD 视为同一事实的更新（取代）。
#: 仅在语义嵌入器可用时生效；HashEmbedder（缺省）下整条语义路径关闭。
SEMANTIC_UPDATE_THRESHOLD = 0.90
#: 语义取代的目标须与最高分候选相差不超过此值 —— 语义分数对模板化短句
#: 普遍偏高（"喜欢用 Python"/"喜欢用 Rust" 常 >0.90），不设裕度会一次
#: 失效多条互不相关的事实。只塌缩近似并列的候选。
SEMANTIC_TARGET_MARGIN = 0.02

#: 否定词 —— 插入一个"不"就能反转事实，而字面相似度仍可能 >= 0.97
#: （长句"…使用 ruff…" vs "…不使用 ruff…" 实测 0.988）。中文按字符匹配，
#: "非常/无论/未来"这类词会误报；误报只会把 NOOP 降级成 UPDATE（多一次
#: 取代），比把新事实当重复丢掉安全。
_NEGATION_RE = re.compile(
    r"不|没|无|非|未|别|勿|\b(?:not|no|never|without|none|nobody|nothing)\b|n['’]t",
    re.IGNORECASE,
)


def _has_negation(text: str) -> bool:
    return bool(text) and _NEGATION_RE.search(text) is not None


def _negation_flipped(a: str, b: str) -> bool:
    """两边否定极性不同（一边含否定词、另一边不含）。"""
    return _has_negation(a) != _has_negation(b)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:400], b[:400]).ratio()


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度；维度不符或零向量返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


@dataclass
class Candidate:
    """一条与本次写入同归属、可能冲突的活跃记忆。"""

    id: str
    memory_type: str  # episodic | semantic
    content: str
    similarity: float
    row: Dict[str, Any] = field(default_factory=dict)
    #: 语义相似度（余弦）；无语义嵌入器或编码失败时为 None
    semantic_similarity: Optional[float] = None


@dataclass
class Decision:
    """冲突消解结果。``target_ids`` 为被取代（UPDATE）或被复用（NOOP）的行。"""

    op: str
    targets: List[Candidate] = field(default_factory=list)

    @property
    def superseded_ids(self) -> List[str]:
        return [c.id for c in self.targets]


def _literal_noop_decision(
    content: str, candidates: List[Candidate]
) -> Optional[Decision]:
    """字面近重复（>= NOOP_THRESHOLD）→ NOOP 决策；无命中返回 None。

    NOOP 只认字面近重复：语义近但取值不同的事实必须让新事实取代旧事实。
    否定极性相反的近重复（"…使用 ruff…" vs "…不使用 ruff…"）字面仍有
    0.98 以上但事实相反，同样禁止 NOOP。
    """
    hits = [
        c
        for c in candidates
        if c.similarity >= NOOP_THRESHOLD
        and not _negation_flipped(content, c.content)
    ]
    if not hits:
        return None
    return Decision(op=OP_NOOP, targets=[max(hits, key=lambda c: c.similarity)])


class MemoryConflictResolver:
    """写入前冲突消解（启发式默认可用；LLM 钩子可选）。"""

    def __init__(
        self,
        episodic,
        semantic,
        candidate_limit: int = 5,
        llm_decide: Optional[Callable[[str, List[Candidate]], Optional[List[Dict[str, Any]]]]] = None,
        embedder=None,
    ) -> None:
        """
        Args:
            embedder: 语义嵌入器实例，或返回实例的可调用（``() -> Embedder``）。
                传可调用是为了支持运行时热切换嵌入模式（用户改设置后
                同一 resolver 立刻用上新嵌入器，无需重建）。
                缺省 / 非语义嵌入器（``is_semantic=False``）时整条语义
                路径关闭，行为退化为纯字面判定。
        """
        self.episodic = episodic
        self.semantic = semantic
        self.candidate_limit = candidate_limit
        self.llm_decide = llm_decide
        self.embedder = embedder

    # ---- 嵌入器 ------------------------------------------------------------

    def _current_embedder(self):
        """取当前语义嵌入器；不可用（非语义 / 取不到 / 异常）时返回 None。"""
        source = self.embedder
        if source is None:
            return None
        try:
            # 嵌入器实例带 encode(); 工厂函数/Mock 自动属性也可能"可调用"，
            # 故先认实例形态，再退回按工厂调用。
            embedder = source if hasattr(source, "encode") else source()
        except Exception as exc:  # noqa: BLE001 — 取嵌入器失败按不可用处理
            logger.debug(f"获取嵌入器失败，语义判定关闭: {exc}")
            return None
        if embedder is None or not getattr(embedder, "is_semantic", False):
            return None
        return embedder

    def _semantic_similarity(self, a: str, b: str) -> Optional[float]:
        """语义相似度（余弦）；无语义嵌入器或编码失败时返回 None。"""
        embedder = self._current_embedder()
        if embedder is None or not a or not b:
            return None
        try:
            vec_a = embedder.encode(a)
            vec_b = embedder.encode(b)
        except Exception as exc:  # noqa: BLE001 — 编码失败退化为字面判定
            logger.debug(f"语义编码失败，退化为字面判定: {exc}")
            return None
        return _cosine_similarity(vec_a, vec_b)

    def _calculate_similarity(self, a: str, b: str) -> float:
        """混合相似度：字面（SequenceMatcher）与语义（嵌入余弦）取较高者。

        语义嵌入器不可用时退化为纯字面。

        注意：**判定不走这里** —— ``resolve`` 用三条独立判定带（字面
        NOOP / 字面 UPDATE / 语义 UPDATE），因为混合后的单一分数无法
        区分"同一事实的改述"与"取值相反的事实"。本方法是诊断/验收用的
        便利接口，逐条 ``encode``（两次往返），不要放进热路径。
        """
        literal = _similarity(a, b)
        semantic = self._semantic_similarity(a, b)
        if semantic is None:
            return literal
        return max(literal, semantic)

    def _annotate_semantic(self, content: str, candidates: List[Candidate]) -> None:
        """批量给候选标注语义相似度（就地写 ``candidate.semantic_similarity``）。

        编码失败时保持 None —— 判定退化为纯字面，绝不因嵌入器故障阻断写入。
        """
        embedder = self._current_embedder()
        if embedder is None or not candidates:
            return
        texts = [content] + [c.content for c in candidates]
        try:
            vectors = embedder.encode_batch(texts)
        except Exception as exc:  # noqa: BLE001 — 批量编码失败按无标注处理
            logger.debug(f"批量语义编码失败，退化为字面判定: {exc}")
            return
        if not vectors or len(vectors) != len(texts):
            return
        base = vectors[0]
        for cand, vec in zip(candidates, vectors[1:]):
            cand.semantic_similarity = _cosine_similarity(base, vec)

    # ---- 判定 --------------------------------------------------------------

    def resolve(
        self,
        content: str,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
        project_key: Optional[str] = None,
    ) -> Decision:
        """对新写入内容给出 ADD / UPDATE / NOOP 决策。

        scope/project_key 未显式给出时按存储层同款规则（finalize_scope）
        推导，保证候选归属与真正落库时一致。
        """
        content = (content or "").strip()
        if not content:
            return Decision(op=OP_ADD)

        db = getattr(self.episodic, "db", None) or getattr(self.semantic, "db", None)
        write_scope, write_key = memory_scope.finalize_scope(
            db, scope, project_key, session_id
        )

        candidates = self._find_candidates(content, write_scope, write_key)
        if not candidates:
            return Decision(op=OP_ADD)

        # 字面近重复即可判 NOOP，语义编码对此毫无帮助 —— 先短路，省掉
        # 整批编码（HTTP 端点下是最贵的一步）。配了 LLM 钩子时仍让钩子
        # 先裁决（钩子可把近重复升级为 UPDATE），不短路。
        if self.llm_decide is None:
            noop = _literal_noop_decision(content, candidates)
            if noop is not None:
                return noop

        # 语义近邻标注（仅语义嵌入器可用时生效）
        self._annotate_semantic(content, candidates)

        # LLM 钩子（返回 None → 回退启发式）
        if self.llm_decide is not None:
            try:
                ops = self.llm_decide(content, candidates)
                decision = self._from_llm_ops(ops, candidates)
                if decision is not None:
                    return decision
            except Exception as exc:  # noqa: BLE001 — LLM 失败不阻塞写入
                logger.debug(f"冲突消解 LLM 决策失败，回退启发式: {exc}")

        return self._heuristic_decision(content, candidates)

    def _heuristic_decision(
        self, content: str, candidates: List[Candidate]
    ) -> Decision:
        """启发式判定：三条独立带（字面 NOOP / 字面 UPDATE / 语义 UPDATE）。"""
        # NOOP 只认字面近重复（≥0.97）—— 语义近但取值不同的事实必须让
        # 新事实取代旧事实，NOOP 会留下过时数据。
        noop = _literal_noop_decision(content, candidates)
        if noop is not None:
            return noop
        # 语义取代只塌缩近似并列的候选（见 SEMANTIC_TARGET_MARGIN）：
        # 短模板句的语义分普遍偏高，不设裕度会一次失效多条无关事实。
        best_semantic = max(
            (c.semantic_similarity or 0.0 for c in candidates), default=0.0
        )
        semantic_floor = max(
            SEMANTIC_UPDATE_THRESHOLD, best_semantic - SEMANTIC_TARGET_MARGIN
        )
        update_hits = [
            c
            for c in candidates
            if UPDATE_THRESHOLD <= c.similarity < NOOP_THRESHOLD
            # 否定极性相反的字面近重复：NOOP 被否决后必须落 UPDATE，
            # 否则会掉到 ADD 产生两条并存。
            or (
                c.similarity >= NOOP_THRESHOLD
                and _negation_flipped(content, c.content)
            )
            or (
                c.semantic_similarity is not None
                and c.semantic_similarity >= semantic_floor
            )
        ]
        if update_hits:
            update_hits.sort(
                key=lambda c: max(c.similarity, c.semantic_similarity or 0.0),
                reverse=True,
            )
            return Decision(op=OP_UPDATE, targets=update_hits)
        return Decision(op=OP_ADD)

    def _find_candidates(
        self, content: str, write_scope: str, write_key: Optional[str]
    ) -> List[Candidate]:
        """在同归属的活跃记忆中找候选（episodic + semantic 两路）。"""
        query = content[:80]
        pooled: List[Candidate] = []
        seen_ids = set()
        for store, memory_type in (
            (self.episodic, "episodic"),
            (self.semantic, "semantic"),
        ):
            try:
                rows = store.search(
                    query, limit=self.candidate_limit, session_id=None
                )
            except Exception as exc:  # noqa: BLE001 — 检索失败按无候选处理
                logger.debug(f"冲突候选检索失败({memory_type}): {exc}")
                continue
            for row in rows:
                rid = row.get("id")
                if not rid or rid in seen_ids:
                    continue
                # 归属对齐：仅同 scope（project 时同 key）可被取代
                if (row.get("scope") or memory_scope.SCOPE_USER) != write_scope:
                    continue
                if write_scope == memory_scope.SCOPE_PROJECT and (
                    row.get("project_key") != write_key
                ):
                    continue
                seen_ids.add(rid)
                pooled.append(
                    Candidate(
                        id=rid,
                        memory_type=memory_type,
                        content=row.get("content", "") or "",
                        similarity=_similarity(content, row.get("content", "") or ""),
                        row=dict(row),
                    )
                )
        pooled.sort(key=lambda c: c.similarity, reverse=True)
        return pooled[: self.candidate_limit * 2]

    @staticmethod
    def _from_llm_ops(
        ops: Optional[List[Dict[str, Any]]], candidates: List[Candidate]
    ) -> Optional[Decision]:
        """把 LLM 输出的 [{op, target_id}] 映射为 Decision；非法输入返回 None。"""
        if not ops:
            return None
        by_id = {c.id: c for c in candidates}
        noop, update = [], []
        for entry in ops:
            op = str(entry.get("op", "")).upper()
            target = by_id.get(str(entry.get("target_id", "")))
            if target is None:
                continue
            if op == "NOOP":
                noop.append(target)
            elif op == "UPDATE":
                update.append(target)
        if noop:
            return Decision(op=OP_NOOP, targets=[noop[0]])
        if update:
            return Decision(op=OP_UPDATE, targets=update)
        return None

    # ---- 应用 --------------------------------------------------------------

    def apply_update(
        self,
        decision: Decision,
        save_fn: Callable[..., str],
        content: str,
        memory_type: str,
        **save_kwargs: Any,
    ) -> Tuple[str, str]:
        """执行 UPDATE：写新行（supersedes 第一条被取代记忆）并把全部目标置失效。

        Args:
            save_fn: 实际写入函数（``manager.memorize`` 风格），须接受
                ``supersedes_id`` / ``scope`` / ``project_key`` kwarg。
            memory_type: 新行落哪个层（由调用方 classify）。
            save_kwargs: 透传给 save_fn 的其余参数（importance/session_id…）。

        Returns:
            (new_id, op)。新行归属沿用决策时的 scope/project_key。
        """
        store_by_type = {
            "episodic": self.episodic,
            "semantic": self.semantic,
        }
        superseded = decision.superseded_ids
        # 与候选同层同归属优先：supersedes 链首元素决定新行归属
        first = decision.targets[0]
        scope, project_key = self._inherit_attribution(first)
        for cand in decision.targets:
            store = store_by_type.get(cand.memory_type)
            if store is None:
                continue
            try:
                store.invalidate(cand.id)
            except Exception as exc:  # noqa: BLE001 — 失效失败退化为 append
                logger.warning(f"冲突失效失败({cand.id}): {exc}")
        new_id = save_fn(
            content=content,
            memory_type=memory_type,
            supersedes_id=superseded[0] if superseded else None,
            scope=scope,
            project_key=project_key,
            **save_kwargs,
        )
        return new_id or "", OP_UPDATE

    @staticmethod
    def _inherit_attribution(candidate: Candidate) -> Tuple[str, Optional[str]]:
        row = candidate.row
        return (
            row.get("scope") or memory_scope.SCOPE_USER,
            row.get("project_key"),
        )


__all__ = [
    "Candidate",
    "Decision",
    "MemoryConflictResolver",
    "NOOP_THRESHOLD",
    "OP_ADD",
    "OP_NOOP",
    "OP_UPDATE",
    "SEMANTIC_TARGET_MARGIN",
    "SEMANTIC_UPDATE_THRESHOLD",
    "UPDATE_THRESHOLD",
]
