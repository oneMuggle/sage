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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.memory import scope as memory_scope

logger = logging.getLogger(__name__)

OP_ADD = "add"
OP_UPDATE = "update"
OP_NOOP = "noop"

#: 相似度 >= NOOP_THRESHOLD 视为同一条事实（不写）
NOOP_THRESHOLD = 0.97
#: UPDATE_THRESHOLD <= 相似度 < NOOP_THRESHOLD 视为同一事实的更新（取代）
UPDATE_THRESHOLD = 0.78


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a[:400], b[:400]).ratio()


@dataclass
class Candidate:
    """一条与本次写入同归属、可能冲突的活跃记忆。"""

    id: str
    memory_type: str  # episodic | semantic
    content: str
    similarity: float
    row: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """冲突消解结果。``target_ids`` 为被取代（UPDATE）或被复用（NOOP）的行。"""

    op: str
    targets: List[Candidate] = field(default_factory=list)

    @property
    def superseded_ids(self) -> List[str]:
        return [c.id for c in self.targets]


class MemoryConflictResolver:
    """写入前冲突消解（启发式默认可用；LLM 钩子可选）。"""

    def __init__(
        self,
        episodic,
        semantic,
        candidate_limit: int = 5,
        llm_decide: Optional[Callable[[str, List[Candidate]], Optional[List[Dict[str, Any]]]]] = None,
    ) -> None:
        self.episodic = episodic
        self.semantic = semantic
        self.candidate_limit = candidate_limit
        self.llm_decide = llm_decide

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

        # LLM 钩子（返回 None → 回退启发式）
        if self.llm_decide is not None:
            try:
                ops = self.llm_decide(content, candidates)
                decision = self._from_llm_ops(ops, candidates)
                if decision is not None:
                    return decision
            except Exception as exc:  # noqa: BLE001 — LLM 失败不阻塞写入
                logger.debug(f"冲突消解 LLM 决策失败，回退启发式: {exc}")

        # 启发式：取每个候选的相似度；NOOP 优先于 UPDATE
        noop_hits = [c for c in candidates if c.similarity >= NOOP_THRESHOLD]
        if noop_hits:
            best = max(noop_hits, key=lambda c: c.similarity)
            return Decision(op=OP_NOOP, targets=[best])
        update_hits = [
            c for c in candidates if UPDATE_THRESHOLD <= c.similarity < NOOP_THRESHOLD
        ]
        if update_hits:
            update_hits.sort(key=lambda c: c.similarity, reverse=True)
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
    "UPDATE_THRESHOLD",
]
