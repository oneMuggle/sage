"""``test_confirm_marker`` — ``confirm_marker.py`` 单元测试（2026-10-28）。

覆盖：
- ``mark()`` 对 4 类规则的触发（文件删除 / 外部 API / 数据库写 / 特权操作）
- ``mark()`` 对正常步骤的放行（不触发）
- ``mark()`` 对 dict / 字符串 / 对象 三种输入的兼容
- ``mark_batch()`` 批量标记
- ``matched_categories()`` 多规则同时触发
- 空输入 / 空 goal / 未知步骤 → False（不确认）
- 大小写不敏感
- 中文 + 英文混合 goal
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.orchestration.confirm_marker import (
    mark,
    mark_batch,
    matched_categories,
)

# ── 文件删除规则 ──────────────────────────────────────────────────────────────


def test_mark_file_delete_rm_rf() -> None:
    assert mark("rm -rf ./dist") is True


def test_mark_file_delete_chinese() -> None:
    assert mark("删除旧的构建文件") is True


def test_mark_file_delete_unlink() -> None:
    assert mark("unlink stale lock file") is True


def test_mark_file_delete_permanent() -> None:
    assert mark("永久删除所有临时文件") is True


# ── 外部 API 调用规则 ─────────────────────────────────────────────────────────


def test_mark_external_api_chinese() -> None:
    assert mark("调用 GitHub API 创建 issue") is True


def test_mark_external_api_fetch() -> None:
    assert mark("fetch('https://api.example.com/data')") is True


def test_mark_external_api_requests() -> None:
    assert mark("requests.post(url, json=payload)") is True


def test_mark_external_api_webhook() -> None:
    assert mark("send webhook to Slack") is True


def test_mark_external_api_post_url() -> None:
    assert mark("POST https://api.example.com/v1/upload") is True


# ── 数据库写操作规则 ─────────────────────────────────────────────────────────


def test_mark_db_write_insert() -> None:
    assert mark("INSERT INTO users (name) VALUES ('test')") is True


def test_mark_db_write_update() -> None:
    assert mark("UPDATE users SET active = 1 WHERE id = 42") is True


def test_mark_db_write_delete_from() -> None:
    assert mark("DELETE FROM sessions WHERE expired = true") is True


def test_mark_db_write_drop_table() -> None:
    assert mark("DROP TABLE legacy_data") is True


def test_mark_db_write_chinese() -> None:
    assert mark("写入数据库中的用户记录") is True


# ── 特权操作规则 ─────────────────────────────────────────────────────────────


def test_mark_privileged_force_push() -> None:
    assert mark("force push to main branch") is True


def test_mark_privileged_push_force_flag() -> None:
    assert mark("git push origin main --force") is True


def test_mark_privileged_npm_publish() -> None:
    assert mark("npm publish --tag latest") is True


def test_mark_privileged_deploy() -> None:
    assert mark("deploy to production server") is True


def test_mark_privileged_release_chinese() -> None:
    assert mark("发布 v2.0.0 版本") is True


# ── 正常步骤（不触发确认） ───────────────────────────────────────────────────


def test_mark_normal_read_file() -> None:
    assert mark("读取配置文件并验证格式") is False


def test_mark_normal_write_local_file() -> None:
    assert mark("写入本地日志文件") is False


def test_mark_normal_run_tests() -> None:
    assert mark("运行单元测试套件") is False


def test_mark_normal_git_add_commit() -> None:
    assert mark("git add . && git commit -m 'fix: typo'") is False


def test_mark_normal_create_file() -> None:
    assert mark("创建新文件 utils/helper.py") is False


def test_mark_normal_read_database() -> None:
    """只读数据库操作不应触发确认。"""
    assert mark("SELECT * FROM users WHERE active = 1") is False


def test_mark_normal_git_push_normal() -> None:
    """普通 git push（不带 --force）不应触发确认。"""
    assert mark("git push origin feat/new-feature") is False


# ── 输入形态兼容 ─────────────────────────────────────────────────────────────


def test_mark_dict_with_goal() -> None:
    """dict 输入（TaskPlanItem 形态）从 goal 字段提取文本。"""
    step = {"task_id": "t1", "agent_id": "a1", "goal": "rm -rf ./dist"}
    assert mark(step) is True


def test_mark_dict_without_goal() -> None:
    """dict 无 goal 字段 → False。"""
    step = {"task_id": "t1", "agent_id": "a1"}
    assert mark(step) is False


def test_mark_object_with_goal_attr() -> None:
    """对象有 goal 属性 → duck-typing 提取。"""
    step = SimpleNamespace(task_id="t1", goal="deploy to production")
    assert mark(step) is True


def test_mark_empty_string() -> None:
    assert mark("") is False


def test_mark_whitespace_only() -> None:
    assert mark("   ") is False


def test_mark_none_like_dict() -> None:
    """dict 的 goal 为空字符串 → False。"""
    step = {"goal": ""}
    assert mark(step) is False


# ── 大小写不敏感 ─────────────────────────────────────────────────────────────


def test_mark_case_insensitive_rm() -> None:
    assert mark("RM -RF ./dist") is True


def test_mark_case_insensitive_deploy() -> None:
    assert mark("DEPLOY to production") is True


def test_mark_case_insensitive_insert() -> None:
    assert mark("insert into users values (1)") is True


# ── 批量标记 ─────────────────────────────────────────────────────────────────


def test_mark_batch_mixed_steps() -> None:
    steps = [
        "读取配置文件",          # False
        "rm -rf ./dist",         # True
        "运行测试",              # False
        "deploy to production",  # True
    ]
    result = mark_batch(steps)
    assert result == [False, True, False, True]


def test_mark_batch_empty() -> None:
    assert mark_batch([]) == []


# ── matched_categories ───────────────────────────────────────────────────────


def test_matched_categories_single() -> None:
    cats = matched_categories("rm -rf ./dist")
    assert "file_delete" in cats


def test_matched_categories_multiple() -> None:
    """一个 goal 可能同时触发多条规则。"""
    cats = matched_categories("deploy 并 force push 到远程")
    assert "privileged" in cats
    assert len(cats) >= 1


def test_matched_categories_empty_for_normal_step() -> None:
    cats = matched_categories("读取配置文件并验证")
    assert cats == []


def test_matched_categories_empty_for_empty_input() -> None:
    assert matched_categories("") == []


# ── 边缘案例 ─────────────────────────────────────────────────────────────────


def test_mark_goal_with_mixed_languages() -> None:
    """中英文混合 goal —— 中文部分触发规则。"""
    assert mark("清理 temp 文件并删除旧的日志文件") is True


def test_mark_partial_match_not_false_positive() -> None:
    """包含 'release' 子串但非独立词 —— 仍应触发（\b 边界对中文无效，
    但 release 在英文上下文中匹配即可）。"""
    assert mark("update release notes") is True


def test_mark_only_task_id_no_goal() -> None:
    """dict 只有 task_id，无 goal → 放行。"""
    assert mark({"task_id": "t-42", "agent_id": "a-1"}) is False


# ── ReDoS 回归（code review HIGH: 无界 .* 导致多项式回溯） ────────────────────


def test_mark_bounded_regex_pathological_input_is_fast() -> None:
    """超长填充文本不应让正则回溯爆炸 —— 修复前 16k 填充耗时 ~1.8s。

    修复手段：把所有 ``.*`` 收窄为 ``[^\\n]{0,200}``，并把 ``_extract_goal``
    的输出截断到 ``_MAX_GOAL_CHARS``（4096）。两者叠加后耗时应在毫秒级。
    """
    import time

    payload = "删除" + "x" * 16384 + "文件"
    start = time.perf_counter()
    mark(payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 100, f"regex 匹配耗时 {elapsed_ms:.1f}ms，疑似回溯爆炸"


def test_mark_bounded_regex_still_matches_normal_input() -> None:
    """收窄 ``.`` 后规则语义不变 —— 正常长度的中文步骤仍应命中。"""
    assert mark("删除所有旧的迁移脚本文件") is True
    assert mark("调用外部 API 同步数据") is True
    assert mark("批量更新用户表中的状态字段") is True
    assert mark("推送到远程仓库") is True

