"""``confirm_marker`` — 规则引擎：自动标记需要用户确认的 plan 步骤。

纯规则匹配，无 LLM 调用。用于 complex plan 执行时，在破坏性 / 不可逆步骤前
暂停并向用户请求显式确认（Phase 3 Week 4）。

规则矩阵:

+-------------------+---------------------------------------+
| 类别              | 触发关键词                            |
+===================+=======================================+
| 文件删除          | 删除, 移除, rm -rf, rm, unlink, shred |
| 外部 API 调用     | API 调用, HTTP 请求, fetch, webhook   |
| 数据库写操作      | INSERT, UPDATE, DELETE FROM, DROP     |
| 特权操作          | force push, publish, deploy, release  |
+-------------------+---------------------------------------+

设计约束:
- 零网络依赖，零 LLM 依赖
- 输入为 step dict（含 ``goal`` 文本字段）或纯字符串
- 返回 bool：True = 需要确认，False = 自动放行
- 大小写不敏感匹配
- 不识别的步骤一律放行（False）—— 避免过度打扰用户
"""
from __future__ import annotations

import re
from typing import Any, List, Mapping, Tuple, Union

# ============================================================================
# Rule definitions
# ============================================================================

# Each rule: (category_name, compiled_regex)
# 编译一次，反复使用 —— 避免每次 mark() 都 re.compile。

_RULES: List[Tuple[str, re.Pattern[str]]] = [
    # ── 文件删除 ──────────────────────────────────────────────────────────
    (
        "file_delete",
        re.compile(
            r"rm\s+-rf"        # rm -rf
            r"|rm\s+-r\b"      # rm -r
            r"|\brm\s+\S+"     # rm <path> (rm 后跟参数)
            r"|删除[^\n]{0,200}文件"  # 中文：删除文件（有界，防 ReDoS）
            r"|移除[^\n]{0,200}文件"  # 中文：移除文件
            r"|unlink\b"       # Python os.unlink / shutil
            r"|shred\b"        # GNU shred
            r"|永久删除"        # 中文：永久删除
            r"|批量删除"        # 中文：批量删除
            r"|清空[^\n]{0,200}目录"  # 中文：清空目录
            ,
            re.IGNORECASE,
        ),
    ),
    # ── 外部 API 调用 ─────────────────────────────────────────────────────
    (
        "external_api",
        re.compile(
            r"调用[^\n]{0,200}API"  # 中文：调用 API（有界）
            r"|API\s*调用"     # 中文：API 调用
            r"|HTTP\s*请求"    # 中文：HTTP 请求
            r"|发送[^\n]{0,200}请求"  # 中文：发送请求（到外部）
            r"|webhook"        # webhook
            r"|fetch\("        # JS fetch()
            r"|requests\."     # Python requests.get/post
            r"|httpx\."        # Python httpx
            r"|curl\s+"        # curl 命令
            r"|POST\s+https?://"  # 直接 POST 到 URL
            r"|PUT\s+https?://"   # 直接 PUT 到 URL
            ,
            re.IGNORECASE,
        ),
    ),
    # ── 数据库写操作 ──────────────────────────────────────────────────────
    (
        "db_write",
        re.compile(
            r"\bINSERT\s+INTO\b"      # SQL INSERT
            r"|\bUPDATE\s+\w+\s+SET\b"  # SQL UPDATE
            r"|\bDELETE\s+FROM\b"     # SQL DELETE
            r"|\bDROP\s+TABLE\b"      # SQL DROP TABLE
            r"|\bALTER\s+TABLE\b"     # SQL ALTER TABLE
            r"|\bTRUNCATE\s+TABLE\b"  # SQL TRUNCATE
            r"|\bCREATE\s+TABLE\b"    # SQL CREATE TABLE (DDL 也算)
            r"|写入数据库"             # 中文：写入数据库
            r"|数据库[^\n]{0,200}写入"  # 中文：数据库写入（有界）
            r"|批量[^\n]{0,200}插入"  # 中文：批量插入
            r"|批量[^\n]{0,200}更新"  # 中文：批量更新
            r"|\.execute\("           # SQLAlchemy / DB-API execute
            r"|\.commit\(\)"          # 显式 commit
            ,
            re.IGNORECASE,
        ),
    ),
    # ── 特权操作 ─────────────────────────────────────────────────────────
    (
        "privileged",
        re.compile(
            r"force\s*push"           # git push --force / -f
            r"|push\s+[^\n]{0,200}--force"  # git push --force 变体（有界）
            r"|push\s+[^\n]{0,200}-f\b"  # git push -f
            r"|\bnpm\s+publish\b"     # npm publish
            r"|\bpip\s+upload\b"      # twine upload / pip upload
            r"|\btwine\s+upload\b"    # PyPI twine
            r"|\bdeploy\b"            # deploy (广义部署)
            r"|\brelease\b"           # release (发布)
            r"|\bpublish\s+package\b" # publish package
            r"|发布[^\n]{0,200}版本"  # 中文：发布版本
            r"|推送[^\n]{0,200}远程"  # 中文：推送远程（强推）
            ,
            re.IGNORECASE,
        ),
    ),
]

#: 提取 goal 后的输入上限 —— 规则引擎是同步正则匹配，病态超长文本
#: 没必要完整扫一遍。4096 已足够覆盖任意合理步骤描述。
_MAX_GOAL_CHARS = 4096


# ============================================================================
# Public API
# ============================================================================


StepLike = Union[str, Mapping[str, Any]]


def mark(step: StepLike) -> bool:
    """判断步骤是否需要用户确认。

    参数:
        step: 步骤描述。可以是：
              - 纯字符串（goal 文本）
              - dict/Mapping（含 ``goal`` 字段，例如 TaskPlanItem）
              - 任意带 ``goal`` 属性的对象（duck-typing）

    返回:
        True = 该步骤触发至少一条规则，执行前应暂停请求确认
        False = 无规则匹配，自动放行

    设计决策:
        - 只匹配 ``goal`` 文本（人类可读的步骤描述），不匹配 task_id / agent_id
        - 未知类别一律放行 —— 避免误报打断用户
        - 大小写不敏感（``re.IGNORECASE`` 已在编译时设置）
    """
    text = _extract_goal(step)
    if not text:
        return False

    return any(pattern.search(text) for _category, pattern in _RULES)


def mark_batch(steps: List[StepLike]) -> List[bool]:
    """批量标记。返回与输入等长的 bool 列表。"""
    return [mark(s) for s in steps]


def matched_categories(step: StepLike) -> List[str]:
    """返回该步骤触发的所有规则类别名称（调试 / 日志用）。

    未触发任何规则 → 空列表。
    """
    text = _extract_goal(step)
    if not text:
        return []

    return [
        category
        for category, pattern in _RULES
        if pattern.search(text)
    ]


# ============================================================================
# Internals
# ============================================================================


def _extract_goal(step: StepLike) -> str:
    """从多种输入形态中提取 goal 文本。

    返回 strip 后截断至 ``_MAX_GOAL_CHARS`` 的字符串 —— 规则引擎是同步
    正则匹配，病态超长文本无扫描必要，统一截断避免 ReDoS 向量。
    """
    raw: str
    if isinstance(step, str):
        raw = step
    elif isinstance(step, Mapping):
        raw = str(step.get("goal", ""))
    else:
        goal = getattr(step, "goal", None)
        if goal is None:
            return ""
        raw = str(goal)
    return raw.strip()[:_MAX_GOAL_CHARS]
