"""TodoService 阶段 0 新行为测试：全文搜索 / 重复实例 / 子任务 / 批量 / 导出。

从 ``test_todo_service.py`` 拆分（架构棘轮 800 行上限）。fixture 与原文件
保持一致：每个用例独立临时库。
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services import todo_fts as todo_fts_module
from backend.services.todo_service import TodoService


@pytest.fixture()
def todo_service():
    """Create TodoService with temporary database"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()

        service = TodoService(db)

        yield service

        db.close()


# --- 全文搜索（FTS5 + LIKE 降级） ---


def test_search_by_chinese_title(todo_service):
    """q 命中标题中的中文关键词，且 count 与 list 一致。"""
    todo_service.create_todo(title="交周报")
    todo_service.create_todo(title="买牛奶")

    results = todo_service.list_todos(q="周报")

    assert [t.title for t in results] == ["交周报"]
    assert todo_service.count_todos(q="周报") == 1


def test_search_matches_description(todo_service):
    """q 同时搜索描述字段。"""
    todo_service.create_todo(title="Task A", description="联系老师讨论论文")
    todo_service.create_todo(title="Task B", description="整理照片")

    results = todo_service.list_todos(q="论文")

    assert [t.title for t in results] == ["Task A"]


def test_search_combines_with_status_filter(todo_service):
    """搜索条件与状态过滤叠加生效。"""
    old = todo_service.create_todo(title="交周报旧版")
    todo_service.complete_todo(old.id)
    todo_service.create_todo(title="交周报新版")

    pending = todo_service.list_todos(q="周报")
    assert [t.title for t in pending] == ["交周报新版"]
    assert todo_service.count_todos(q="周报", include_completed=True) == 2


def test_search_no_match_returns_empty(todo_service):
    todo_service.create_todo(title="买牛奶")
    assert todo_service.list_todos(q="量子力学") == []
    assert todo_service.count_todos(q="量子力学") == 0


def test_search_index_updates_after_update_and_delete(todo_service):
    """FTS 索引随 update / delete 显式同步，不残留旧词。

    查询侧与记忆搜索一致是 jieba 分词 + OR 语义，关键词需选无重叠 token
    （"苹果"/"香蕉"），避免共享子词造成误命中。
    """
    todo = todo_service.create_todo(title="苹果任务")

    todo_service.update_todo(todo.id, title="香蕉任务")
    assert todo_service.list_todos(q="苹果") == []
    assert [t.id for t in todo_service.list_todos(q="香蕉")] == [todo.id]

    todo_service.delete_todo(todo.id)
    assert todo_service.list_todos(q="香蕉") == []


def test_search_like_fallback_when_fts_unavailable(todo_service, monkeypatch):
    """FTS 不可用（返回 None）时降级为 LIKE，搜索仍然可用。"""
    todo_service.create_todo(title="论文初稿")
    monkeypatch.setattr(todo_fts_module, "match_ids", lambda db, q: None)

    assert [t.title for t in todo_service.list_todos(q="论文")] == ["论文初稿"]


# --- 重复任务生成 ---


def test_complete_recurring_todo_spawns_next_instance(todo_service):
    """完成循环待办后自动创建下一实例，due_at 为 cron 的下一次触发时间。"""
    created = todo_service.create_todo(
        title="每日站会",
        due_at=(datetime.now() - timedelta(hours=1)).isoformat(),
        priority="high",
        recurrence_rule="0 9 * * *",
    )

    todo_service.complete_todo(created.id)

    todos = todo_service.list_todos()
    assert len(todos) == 1
    spawned = todos[0]
    assert spawned.id != created.id
    assert spawned.title == "每日站会"
    assert spawned.priority == "high"
    assert spawned.status == "pending"
    assert spawned.is_recurring is True
    assert spawned.recurrence_rule == "0 9 * * *"
    next_due = datetime.fromisoformat(spawned.due_at)
    assert next_due > datetime.now()
    assert (next_due.hour, next_due.minute) == (9, 0)


def test_complete_non_recurring_todo_spawns_nothing(todo_service):
    created = todo_service.create_todo(title="一次性任务")
    todo_service.complete_todo(created.id)
    assert todo_service.list_todos() == []


def test_complete_twice_does_not_spawn_duplicate_recurrence(todo_service):
    """幂等：重复完成同一循环待办只派生一个下一实例。

    PUT /todos/{id} 在详情面板保存时会带上当前 status，重复提交同一份
    payload 不应凭空多出明天的任务副本。
    """
    created = todo_service.create_todo(title="每日站会", recurrence_rule="0 9 * * *")

    todo_service.complete_todo(created.id)
    twice = todo_service.complete_todo(created.id)

    assert twice is not None
    assert twice.status == "completed"
    pending = todo_service.list_todos()
    assert len(pending) == 1
    assert pending[0].status == "pending"


def test_complete_recurring_with_invalid_cron_still_completes(todo_service):
    """cron 非法时 fail-open：完成操作本身仍然成功，只是不生成实例。"""
    created = todo_service.create_todo(
        title="坏规则", recurrence_rule="not-a-cron"
    )

    completed = todo_service.complete_todo(created.id)

    assert completed is not None
    assert completed.status == "completed"
    assert todo_service.list_todos() == []


# --- 子任务（parent_id） ---


def test_create_subtask(todo_service):
    parent = todo_service.create_todo(title="父任务")
    child = todo_service.create_todo(title="子任务", parent_id=parent.id)

    assert child.parent_id == parent.id


def test_create_subtask_rejects_missing_parent(todo_service):
    with pytest.raises(ValueError, match="not found"):
        todo_service.create_todo(title="孤儿", parent_id=99999)


def test_create_subtask_rejects_third_level(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)

    with pytest.raises(ValueError, match="depth"):
        todo_service.create_todo(title="孙", parent_id=child.id)


def test_update_todo_cannot_be_own_parent(todo_service):
    parent = todo_service.create_todo(title="父")
    with pytest.raises(ValueError, match="own parent"):
        todo_service.update_todo(parent.id, parent_id=parent.id)


def test_update_todo_with_children_cannot_become_subtask(todo_service):
    root = todo_service.create_todo(title="根")
    todo_service.create_todo(title="子", parent_id=root.id)
    other = todo_service.create_todo(title="另一个顶层")

    # 把有子任务的顶层挂到另一个顶层下会形成三级层级 → 拒绝
    with pytest.raises(ValueError, match="cannot become a subtask"):
        todo_service.update_todo(root.id, parent_id=other.id)


def test_update_todo_can_clear_parent(todo_service):
    parent = todo_service.create_todo(title="父")
    child = todo_service.create_todo(title="子", parent_id=parent.id)

    updated = todo_service.update_todo(child.id, parent_id=None)

    assert updated is not None
    assert updated.parent_id is None


# --- 批量操作 ---


def test_complete_many(todo_service):
    t1 = todo_service.create_todo(title="A")
    t2 = todo_service.create_todo(title="B")

    result = todo_service.complete_many([t1.id, t2.id, 99999])

    assert result == {"completed": 2, "missing": [99999]}
    assert todo_service.count_todos() == 0


def test_delete_many(todo_service):
    t1 = todo_service.create_todo(title="A")
    t2 = todo_service.create_todo(title="B")

    deleted = todo_service.delete_many([t1.id, 99999])

    assert deleted == 1
    assert todo_service.get_todo(t1.id) is None
    assert todo_service.get_todo(t2.id) is not None


# --- 导出 ---


def test_export_json(todo_service):
    import json as _json

    todo_service.create_todo(title="写方案", priority="high", project_tag="Sage")
    done = todo_service.create_todo(title="已完成项")
    todo_service.complete_todo(done.id)

    out = todo_service.export_todos(include_completed=False, fmt="json")

    assert out["format"] == "json"
    assert out["filename"].endswith(".json")
    data = _json.loads(out["content"])
    titles = [item["title"] for item in data]
    assert "写方案" in titles
    assert "已完成项" not in titles


def test_export_markdown(todo_service):
    todo_service.create_todo(title="写方案", priority="high", project_tag="Sage")
    done = todo_service.create_todo(title="已完成项")
    todo_service.complete_todo(done.id)

    out = todo_service.export_todos(include_completed=True, fmt="md")

    assert out["format"] == "md"
    assert out["filename"].endswith(".md")
    assert "- [ ] 写方案" in out["content"]
    assert "- [x] 已完成项" in out["content"]
    assert "优先级: high" in out["content"]
    assert "项目: Sage" in out["content"]
