"""确认门控后回读权威计划 —— orch_plan_block.load_confirmed_plan_items 单测。

覆盖 plan 回读的每条兜底分支（调用方据 None 回落内存 plan_items，原行为）：
1. 正常读库 → 返回计划条目；
2. run 不存在 / plan_json 为空 → None；
3. plan_json 不是合法 JSON → None（降级不抛错）；
4. plan_json 顶层不是 dict / tasks 不是 list → None；
5. tasks 里混入非 dict 或缺 task_id 的条目 → 过滤后返回，全废则 None；
6. 读库抛异常 → None（logger.warning 降级铁律）。
"""

from __future__ import annotations

import json

import pytest

from backend.api.orch_plan_block import load_confirmed_plan_items
from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """tmp DB + 重置全局 _db 单例。"""
    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()
    return OrchRunRepository()


def _insert(repo: OrchRunRepository, run_id: str, plan_json: str) -> None:
    repo.upsert(
        OrchRun(
            run_id=run_id,
            session_id="s-1",
            status="running",
            created_at=1000,
            plan_json=plan_json,
        )
    )


def test_returns_confirmed_items(repo: OrchRunRepository) -> None:
    """用户在计划卡确认窗口内的编辑/修订已落库 → 原样读回。"""
    _insert(
        repo,
        "orch-ok",
        json.dumps(
            {
                "tasks": [
                    {"task_id": "t1", "agent_id": "researcher", "goal": "改过的目标"},
                    {"task_id": "t2", "agent_id": "writer", "goal": "G2", "depends_on": ["t1"]},
                ],
                "reasoning": "先调研后写作",
            },
            ensure_ascii=False,
        ),
    )
    items = load_confirmed_plan_items("orch-ok")
    assert items is not None
    assert [it["task_id"] for it in items] == ["t1", "t2"]
    assert items[0]["goal"] == "改过的目标"
    # depends_on 等扩展字段必须保留（conductor 的依赖图靠它）
    assert items[1]["depends_on"] == ["t1"]


def test_returns_none_when_run_missing(repo: OrchRunRepository) -> None:
    assert load_confirmed_plan_items("orch-nope") is None


def test_returns_none_when_plan_json_empty(repo: OrchRunRepository) -> None:
    _insert(repo, "orch-empty", "")
    assert load_confirmed_plan_items("orch-empty") is None


def test_returns_none_on_malformed_json(repo: OrchRunRepository) -> None:
    _insert(repo, "orch-bad-json", "{不是 JSON")
    assert load_confirmed_plan_items("orch-bad-json") is None


@pytest.mark.parametrize(
    "plan_json",
    [
        '["tasks"]',  # 顶层是 list 而非 dict
        '{"reasoning": "没有 tasks 键"}',
        '{"tasks": "t1,t2"}',  # tasks 不是 list
        "{}",
    ],
)
def test_returns_none_on_unexpected_shape(repo: OrchRunRepository, plan_json: str) -> None:
    _insert(repo, "orch-shape", plan_json)
    assert load_confirmed_plan_items("orch-shape") is None


def test_filters_junk_entries_but_keeps_valid_ones(repo: OrchRunRepository) -> None:
    """非 dict 或缺 task_id 的条目被剔除，合法条目照常返回。"""
    _insert(
        repo,
        "orch-junk",
        json.dumps(
            {
                "tasks": [
                    "t1",
                    {"agent_id": "primary", "goal": "缺 task_id"},
                    {"task_id": "", "agent_id": "primary", "goal": "空 task_id"},
                    {"task_id": "t2", "agent_id": "writer", "goal": "G2"},
                ]
            },
            ensure_ascii=False,
        ),
    )
    items = load_confirmed_plan_items("orch-junk")
    assert items is not None
    assert [it["task_id"] for it in items] == ["t2"]


def test_returns_none_when_all_entries_filtered_out(repo: OrchRunRepository) -> None:
    _insert(
        repo,
        "orch-all-junk",
        json.dumps({"tasks": ["t1", {"goal": "no id"}]}, ensure_ascii=False),
    )
    assert load_confirmed_plan_items("orch-all-junk") is None


def test_returns_none_when_repo_read_raises(repo: OrchRunRepository, monkeypatch) -> None:
    """读库抛异常 → None 降级（logger.warning），绝不阻塞 producer。"""
    _insert(
        repo,
        "orch-boom",
        json.dumps({"tasks": [{"task_id": "t1", "goal": "G"}]}, ensure_ascii=False),
    )

    def _explode(_run_id: str):
        raise RuntimeError("db locked")

    monkeypatch.setattr(OrchRunRepository, "get", _explode)
    assert load_confirmed_plan_items("orch-boom") is None
