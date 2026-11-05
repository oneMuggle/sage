# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""黄金任务集加载 + 确定性评分 + 可注入 runner（M4-T4，spec §11）。

职责边界（避免膨胀）:

- **加载**: ``load_golden_tasks()`` 读 ``golden_tasks.json``；
  ``tasks_for_template(id)`` 按模板分组；``all_template_ids()`` 返回全部模板 id。
- **评分**: 纯函数 ``evaluate_task(task, runner_output)`` 与 ``aggregate_report(...)``。
  检查器全部确定性: ``keywords_all / keywords_any / forbidden / refusal / regex / max_chars``。
- **Runner**: 抽象为 ``(profile, task) -> {"output", "tool_calls", "tokens"}`` 异步回调；
  测试全部注入假 runner，CI 不发起真实网络请求；默认 runner
  ``default_llm_runner`` 复用 ``_build_compaction_llm_callable()`` 装配的 LLM
  客户端（无配置时抛 RuntimeError）。
- **运行**: ``run_golden_eval(profile, task_ids=None, runner=None)`` 串跑全部/
  部分任务；单任务 runner 异常不影响其他任务，记入 ``error`` 字段。

与 ``agent_eval_runs`` 表（M4 持久化）的协作:
- 本模块不直接访问数据库；路由层负责将 ``run_golden_eval`` 返回的报告
  写入 ``agent_eval_runs`` 表并分配 run_id。
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

#: runner 签名: (profile, task) -> {"output": str, "tool_calls": list, "tokens": int}
RunnerFn = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Dict[str, Any]]]

#: 默认拒答模式（中英文）—— refusal 检查器在输出匹配这些模式时判为「已拒答」
DEFAULT_REFUSAL_PATTERNS: List[str] = [
    r"我(?:无法|不能)(?:帮您|回答|提供|执行)",
    r"抱歉[，,]\s*我(?:无法|不能)",
    r"sorry[, ]?\s*I\s+(?:can'?t|cannot|am\s+not\s+able\s+to)",
    r"as\s+an?\s+AI,?\s+(?:I'?m|I\s+)?(?:can'?t|cannot|unable\s+to)",
]

#: 数据文件: golden_tasks.json（与模块同目录）
GOLDEN_TASKS_PATH = Path(__file__).with_name("golden_tasks.json")


# =====================================================================
# 数据加载
# =====================================================================


def load_golden_tasks() -> List[Dict[str, Any]]:
    """读取 golden_tasks.json 的任务列表。

    文件存在则返回 ``data["tasks"]``（list）；文件缺失或 schema 非法
    抛 ValueError（路由层会 500）。
    """
    if not GOLDEN_TASKS_PATH.is_file():
        raise ValueError(f"黄金任务集数据文件缺失: {GOLDEN_TASKS_PATH}")
    try:
        with GOLDEN_TASKS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"黄金任务集解析失败: {exc}") from exc
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("golden_tasks.json 顶层需含 tasks 数组")
    return tasks


def tasks_for_template(
    template_id: str, tasks: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """返回指定模板的全部任务（保留顺序）。"""
    tasks = tasks or load_golden_tasks()
    return [t for t in tasks if t.get("template_id") == template_id]


def all_template_ids(tasks: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """返回所有模板 id（按首次出现顺序去重）。"""
    tasks = tasks or load_golden_tasks()
    seen: Set[str] = set()
    out: List[str] = []
    for t in tasks:
        tpl = t.get("template_id")
        if tpl and tpl not in seen:
            seen.add(tpl)
            out.append(tpl)
    return out


def template_id_from_agent_id(agent_id: str) -> Optional[str]:
    """从模板实例化的 ``agent_id`` 中推断 template_id。

    实例化命名 ``specialist-<template>-<6hex>``；非模板专家返回 None。
    """
    if not isinstance(agent_id, str):
        return None
    m = re.match(r"^specialist-([a-z][a-z0-9-]{1,30})-[0-9a-f]{6}$", agent_id)
    return m.group(1) if m else None


# =====================================================================
# 确定性评分
# =====================================================================


def _evaluate_check(check: Dict[str, Any], output: str) -> bool:  # noqa: PLR0911 — 每种检查 kind 一个早退分支
    """单个检查器。非法 kind → False（保守失败，不抛异常污染整体报告）。"""
    kind = check.get("kind")
    value = check.get("value")
    if not isinstance(kind, str):
        return False

    if kind == "keywords_all":
        kws = value if isinstance(value, list) else []
        return all(isinstance(kw, str) and kw.lower() in output.lower() for kw in kws)
    if kind == "keywords_any":
        kws = value if isinstance(value, list) else []
        return any(isinstance(kw, str) and kw.lower() in output.lower() for kw in kws)
    if kind == "forbidden":
        kws = value if isinstance(value, list) else []
        return not any(
            isinstance(kw, str) and kw.lower() in output.lower() for kw in kws
        )
    if kind == "refusal":
        patterns = value if isinstance(value, list) else DEFAULT_REFUSAL_PATTERNS
        try:
            return not bool(
                re.search("|".join(patterns), output, re.IGNORECASE)
            )
        except re.error:
            logger.warning("refusal 正则编译失败, 保守判为通过")
            return True
    if kind == "regex":
        pattern = check.get("pattern")
        if not isinstance(pattern, str):
            return False
        try:
            return bool(re.search(pattern, output))
        except re.error:
            logger.warning("regex 检查器编译失败: %r", pattern)
            return False
    if kind == "max_chars":
        if not isinstance(value, int):
            return False
        return len(output) <= value
    return False


def evaluate_task(
    task: Dict[str, Any], runner_output: Dict[str, Any]
) -> Dict[str, Any]:
    """按任务 checks 逐条评分,返回单任务报告。

    ``runner_output`` 至少含 ``output: str``;可选 ``tool_calls``/``tokens``。
    """
    output = runner_output.get("output", "") or ""
    if not isinstance(output, str):
        output = str(output)

    checks = task.get("checks") if isinstance(task.get("checks"), list) else []
    check_results: List[Dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        check_results.append(
            {
                "check": check.get("kind"),
                "passed": _evaluate_check(check, output),
            }
        )

    tokens = runner_output.get("tokens", 0)
    if not isinstance(tokens, int) or tokens < 0:
        try:
            tokens = int(tokens)
        except (TypeError, ValueError):
            tokens = 0

    tool_calls = runner_output.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []

    return {
        "task_id": task.get("id"),
        "template_id": task.get("template_id"),
        "topic": task.get("topic"),
        "passed": all(c["passed"] for c in check_results) if check_results else False,
        "checks": check_results,
        "tokens": tokens,
        "tool_calls": tool_calls,
        "output_length": len(output),
    }


def aggregate_report(
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """聚合全部任务结果为整体报告。"""
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    errored = sum(1 for r in results if r.get("error"))
    total_tokens = sum(int(r.get("tokens") or 0) for r in results)

    by_template: Dict[str, Dict[str, Any]] = {}
    for r in results:
        tpl = r.get("template_id") or "unknown"
        bucket = by_template.setdefault(tpl, {"total": 0, "passed": 0, "tokens": 0})
        bucket["total"] += 1
        if r.get("passed"):
            bucket["passed"] += 1
        bucket["tokens"] += int(r.get("tokens") or 0)

    for bucket in by_template.values():
        bucket["pass_rate"] = (
            bucket["passed"] / bucket["total"] if bucket["total"] else 0.0
        )

    return {
        "total_tasks": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "pass_rate": passed / total if total else 0.0,
        "total_tokens": total_tokens,
        "by_template": by_template,
        "task_results": results,
    }


# =====================================================================
# Runner
# =====================================================================


async def default_llm_runner(
    profile: Dict[str, Any], task: Dict[str, Any]
) -> Dict[str, Any]:
    """默认 runner:复用压缩摘要的 LLM 装配逻辑,单轮调用。

    无可用配置时抛 RuntimeError（路由层会捕获并整体记为 error）。
    tokens/tool_calls 在此 runner 中均为 0/[]（compaction 装配返回的
    callable 是 ``complete(prompt) -> str``,无 usage 回传）。
    """
    from backend.api.chat_session_lifecycle import _build_compaction_llm_callable

    complete = _build_compaction_llm_callable()
    if complete is None:
        raise RuntimeError("LLM endpoint 未配置（无法执行黄金任务集评测）")

    from backend.chat.specialist_prompt_composer import compose_system_prompt_simple

    system = compose_system_prompt_simple(profile)
    user_prompt = task.get("prompt") or ""
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise ValueError(f"任务 prompt 为空: {task.get('id')}")

    # 合并为单字符串（complete 走 user 单消息通道）
    combined = f"{system}\n\n## 用户任务\n\n{user_prompt}"
    output = await complete(combined)
    return {"output": output or "", "tool_calls": [], "tokens": 0}


# =====================================================================
# 运行
# =====================================================================


async def run_golden_eval(
    profile: Dict[str, Any],
    *,
    task_ids: Optional[List[str]] = None,
    runner: Optional[RunnerFn] = None,
) -> Dict[str, Any]:
    """跑指定 profile 的黄金任务集。

    Args:
        profile: 完整 AgentProfile 字典（system_prompt 等必须齐全）
        task_ids: 指定任务 id 子集；None 跑全部
        runner: 自定义 runner；默认 ``default_llm_runner``（生产用，会真实调 LLM）

    Returns:
        ``aggregate_report`` 输出 + ``started_at`` / ``finished_at`` 毫秒时间戳。
    """
    runner_fn = runner or default_llm_runner
    all_tasks = load_golden_tasks()

    if task_ids:
        selected_ids: Set[str] = set(task_ids)
        selected = [t for t in all_tasks if t.get("id") in selected_ids]
        unknown = selected_ids - {t.get("id") for t in selected}
        if unknown:
            logger.warning("黄金任务集: 未知 task_id 被忽略: %s", sorted(unknown))
    else:
        selected = all_tasks

    if not selected:
        empty = aggregate_report([])
        empty["started_at"] = int(time.time() * 1000)
        empty["finished_at"] = int(time.time() * 1000)
        return empty

    started_at = int(time.time() * 1000)
    results: List[Dict[str, Any]] = []
    for task in selected:
        try:
            runner_output = await runner_fn(profile, task)
        except Exception as exc:  # noqa: BLE001 — runner 异常不中断其它任务
            logger.warning(
                "黄金任务 %s 运行失败: %s", task.get("id"), exc
            )
            results.append(
                {
                    "task_id": task.get("id"),
                    "template_id": task.get("template_id"),
                    "topic": task.get("topic"),
                    "error": str(exc),
                    "passed": False,
                    "checks": [],
                    "tokens": 0,
                    "tool_calls": [],
                    "output_length": 0,
                }
            )
            continue
        results.append(evaluate_task(task, runner_output))
    finished_at = int(time.time() * 1000)

    report = aggregate_report(results)
    report["started_at"] = started_at
    report["finished_at"] = finished_at
    return report


def new_run_id() -> str:
    """生成评测 run id（uuid4 hex）。"""
    return uuid.uuid4().hex


__all__ = [
    "RunnerFn",
    "DEFAULT_REFUSAL_PATTERNS",
    "GOLDEN_TASKS_PATH",
    "load_golden_tasks",
    "tasks_for_template",
    "all_template_ids",
    "template_id_from_agent_id",
    "evaluate_task",
    "aggregate_report",
    "default_llm_runner",
    "run_golden_eval",
    "new_run_id",
]
