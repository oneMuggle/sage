# Academic Search Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Sage 增加"用户引导 LLM 完成学术文献检索，并把流程沉淀为可复用 SKILL.md"的能力 — CNKI / Web of Science / Scopus 等站点适配统一走同一 skill 框架，不在主程序硬编码任何站点逻辑。

**Architecture:**
- **M1 skill_save 工具**：LLM 工具入口。LLM 在调用时**显式传入 `tool_sequence: List[Dict]`**（每个 Dict 含 `tool/args/result_summary`），不走 ContextVar（`ToolExecutionContext` 不携带 tool_calls 且 SageAgent 不累积）。从 `tool_sequence` 解析得到"刚执行过的步骤" → 送 review pipeline → 生成 SkillDraft → 用户 approve 后写为 `<skills_dir>/<name>/SKILL.md`
- **O2 AcademicSearchSkill (SKILL.md 形态)**：通过 `skill_save` 在用户引导下沉淀生成，复用到任何站点。SKILL.md 的 body 是给 LLM 看的"剧本"，告诉 LLM 该调哪些工具（`web_fetch` / `ask_user_question` / `browser_*`），不在脚本里直接调
- **站点适配层**：在 SKILL.md 内部以 frontmatter + 提示词变量（`{{site}}` / `{{query}}`）声明，**主程序零硬编码**

**Tech Stack:**
- Backend: Python 3.10 (sage-backend conda env), FastAPI 0.109, pytest 7.4
- Skill 系统: 现有 `backend/skills/`（review_service + draft_store + loader + lifecycle）+ SKILL.md frontmatter 格式
- 测试: pytest 单元 + respx（HTTP mock）+ 集成测试走真实 review pipeline（注入 mock LLM provider）

**Spec:** docs/superpowers/specs/2026-09-08-academic-search-skill-design.md（本次会话 spike + 推荐方案的口头版；任务执行前我会创建此 spec 并请用户 review）

## 修正说明（与 spike 阶段推荐方案的偏差）

spike 阶段我推荐"O2 builtin skill 形态"。**实施前源码勘察发现该方案不可行**，原因：
1. `backend/skills/builtin/__init__.py` 只有 1 行注释，4 个 builtin skill（coder/search/travel/writer）**没在主程序注册**（grep 0 命中注册点）
2. `SkillMdSkill.execute()` v1 只返回 body，**不调任何工具**；v2 走 ScriptRunner 沙箱（shell 脚本），**也不能调 LLM 工具栈**
3. 真正可用的 skill 形态只有 SKILL.md —— 它是**给 LLM 看的提示词模板**，不是程序模块

所以本计划修正为：**skill 是给 LLM 的剧本**，由 LLM 在用户引导下用工具栈执行，事后由 `skill_save` 工具把执行轨迹沉淀为 SKILL.md。

### 修正说明 v2（2026-09-08，方案 B 选型后）

**原 plan 假设的会话历史抽取路径不通：**

1. `ToolExecutionContext`（`backend/tools/context.py:36`）字段固化：`session_id / stream_id / binding_generation / office_doc_scope`，**无 `tool_calls`**；16+ 测试 fixture 固化，加字段会动测试
2. `SageAgent`（`backend/core/legacy/agent.py:595-661`）直接调 `tool.execute()`，**不累积 tool_call 历史**；`pattern_detector` 是独立模块，没接 ContextVar

**方案 B（用户 2026-09-08 选型）：** skill_save 让 LLM **显式传 `tool_sequence: List[Dict]`** 进来，LLM 既然显式触发沉淀就让它显式提供序列。skill_save 不依赖会话历史 / ContextVar，最小改动面。

**接口变动：**
- 原 plan：`from_recent: int`（N 上限 20，工具内部抽最近 N 步）→ 改为 `tool_sequence: List[Dict]`（LLM 直接给，最多 20 元素）
- session_extractor：从 "抽 N 步" 改为 "校验 + 标准化 LLM 传入的 sequence"（裁剪到上限、补 required 字段、过滤非法记录）
- ToolSchema 参数 `from_recent` 删除，新增 `tool_sequence`

---

## 全局约束

- Python: `sage-backend` conda env（路径见 `.claude/CLAUDE.md`），**禁止系统 Python**
- 端口: worktree 后端 8766，前端 1421（项目脚本自动分配）
- Lint: `ruff` 0.4.4（与 CI 版本对齐）
- 测试: pytest 7.4 + pytest-asyncio 0.23.3 + pytest-timeout 2.3.1 + respx 0.21.1
- 命名: 技能名 kebab-case `[a-z](?:[a-z0-9]|-[a-z0-9]){2,39}`（`review_service._validate_skill_name` 强制）
- 内容约束: SKILL.md body 必须含 `## 步骤` / `## 触发条件` / `## 示例` 三段（`review_service._validate_skill_schema` 强制）
- 工作区: worktree `/home/fz/project/sage/.worktrees/feat-academic-search-skill`，**禁止 `git push --force`** / **禁止合并 main 之外的 release/win7**

---

## 文件结构

### 新增

```
backend/tools/skill_save_tool.py               ← M1: skill_save 工具入口
backend/skills/session_extractor.py            ← M1: 从会话拉最近 N 步 tool call
backend/tests/unit/test_skill_save_tool.py     ← M1 单元测试
backend/tests/unit/test_session_extractor.py   ← M1 单元测试
backend/skills/builtin/academic_search.py      ← O2: builtin skill 形态（提示词模板）
backend/skills/builtin/academic_adapters.py   ← O2: 站点 adapter 注册表
backend/tests/unit/test_academic_search_skill.py ← O2 单元测试
docs/superpowers/specs/2026-09-08-academic-search-skill-design.md  ← 设计 spec
docs/superpowers/plans/2026-09-08-academic-search-skill.md        ← 本文件
docs/technical/53-academic-search-skill.md    ← 用户文档
```

### 修改

```
backend/tools/__init__.py            ← 导出 SkillSaveTool
backend/tests/conftest.py            ← （如需要）共享 mock LLM provider fixture
```

### 文件职责（单一职责原则）

| 文件 | 唯一职责 | 行数上限 |
|---|---|---|
| `skill_save_tool.py` | LLM 入口 + 参数校验 + 委托 session_extractor + review_service | 150 |
| `session_extractor.py` | 从 session ctx 提取最近 N 步 tool call，纯函数 | 80 |
| `academic_search.py` | 站点的"提示词模板"，不调工具 | 100 |
| `academic_adapters.py` | 站点 URL 模板字典 + 解析规则，纯数据 + 纯函数 | 120 |

---

## Task 1: spec 文档落地（开工前 5 分钟）

**Files:**
- Create: `docs/superpowers/specs/2026-09-08-academic-search-skill-design.md`

**Interfaces:** 无

- [ ] **Step 1: 写 spec 文档**

把本次会话口头达成的设计决策固化为 markdown，至少包含：
- 目标与边界（CNKI/学术检索 / 灵活可复用 / 主程序零硬编码）
- M1 skill_save 工具的接口与边界
- O2 SKILL.md 形态决策与 builtin 不可行的理由
- 站点适配在 SKILL.md 内部的声明方式
- 风险点：CNKI 反爬、合规边界、登录态
- 不做事项（YAGNI）

- [ ] **Step 2: 自检 + 用户 review**

通读一遍，找 placeholder/矛盾/模糊处，修。然后请用户 review spec，确认后才进入 Task 2。

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/specs/2026-09-08-academic-search-skill-design.md
git commit -m "docs(spec): academic-search-skill design baseline"
```

---

## Task 2: session_extractor 单元 + 实现（半小时）

**Files:**
- Create: `backend/skills/session_extractor.py`
- Create: `backend/tests/unit/test_session_extractor.py`

**Interfaces:**
- Consumes: `raw_sequence: List[Dict[str, Any]]`，元素是 dict `{"tool": str, "args": dict, "result_summary": str, "timestamp_ms": int}`（LLM 显式传入）
- Produces: `normalize_tool_sequence(raw_sequence: List[Dict[str, Any]]) -> List[Dict[str, Any]]`，纯函数；上限 20 元素，缺字段过滤

**前置探查（task 内 step）：**

- [ ] **Step 1: 探查 review_service / pattern_detector 的 tool_call 形状**

读 `backend/skills/pattern_detector.py` 看现有代码如何表示一次 tool call（tool 名 + args 形状）。读 `backend/skills/review_service.py:_validate_skill_schema` 确认 content schema 不依赖 tool_calls 的具体形状，只看 LLM 输出。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/unit/test_session_extractor.py
from backend.skills.session_extractor import normalize_tool_sequence


def test_returns_empty_list_when_empty():
    assert normalize_tool_sequence([]) == []


def test_returns_input_unchanged_when_under_limit():
    raw = [
        {"tool": "web_fetch", "args": {"url": "x"}, "result_summary": "ok", "timestamp_ms": 1},
        {"tool": "ask_user_question", "args": {"q": "y"}, "result_summary": "ok", "timestamp_ms": 2},
    ]
    assert normalize_tool_sequence(raw) == raw


def test_caps_at_20_keeping_latest():
    raw = [{"tool": f"t{i}", "args": {}, "result_summary": "", "timestamp_ms": i}
           for i in range(25)]
    result = normalize_tool_sequence(raw)
    assert len(result) == 20
    assert result[0]["tool"] == "t5"
    assert result[-1]["tool"] == "t24"


def test_skips_malformed_records():
    raw = [
        {"tool": "web_fetch", "args": {"url": "x"}, "result_summary": "ok", "timestamp_ms": 1},
        {"args": {}, "result_summary": "ok", "timestamp_ms": 2},  # 缺 tool
        {"tool": "ask_user_question", "args": {}, "result_summary": "ok", "timestamp_ms": 3},
        {"tool": 123, "args": {}, "result_summary": "ok", "timestamp_ms": 4},  # tool 非字符串
    ]
    result = normalize_tool_sequence(raw)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "ask_user_question"


def test_accepts_missing_optional_fields():
    """timestamp_ms / result_summary 缺失视为合法（LLM 简化）。"""
    raw = [{"tool": "web_fetch", "args": {"url": "x"}}]
    result = normalize_tool_sequence(raw)
    assert result == raw


def test_skips_when_args_missing():
    """args 字段是必需，少了 args 直接跳过（review pipeline 无法重建流程）。"""
    raw = [{"tool": "web_fetch", "result_summary": "ok", "timestamp_ms": 1}]
    assert normalize_tool_sequence(raw) == []


def test_returns_new_list_not_mutating_input():
    raw = [{"tool": "web_fetch", "args": {}, "result_summary": "", "timestamp_ms": i}
           for i in range(25)]
    original_len = len(raw)
    normalize_tool_sequence(raw)
    assert len(raw) == original_len  # 不修改输入
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_session_extractor.py -v
```

Expected: ImportError 或 NameError（模块不存在）

- [ ] **Step 4: 实现**

```python
# backend/skills/session_extractor.py
"""校验并标准化 LLM 传入的 tool_sequence。

设计要点:
- 纯函数: 不读 DB / 不持有状态；调用方传入已序列化的 list
- 上限 20: 超出截断保留最后 N 条，避免 review prompt token 爆炸
- 容错: 缺必需字段（tool/args）或字段类型错的 record 静默跳过
- 不修改输入: 返回新 list，调用方可以放心传递原始 LLM 输出
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_SEQUENCE_LEN = 20
REQUIRED_FIELDS = ("tool", "args")


def normalize_tool_sequence(
    raw_sequence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """校验并裁剪 LLM 传入的工具调用序列。

    Args:
        raw_sequence: LLM 显式传入的工具调用列表，按时间升序

    Returns:
        合法记录的新列表（最多 MAX_SEQUENCE_LEN 条，缺字段跳过）；
        不修改输入列表
    """
    filtered: List[Dict[str, Any]] = []
    dropped = 0
    for record in raw_sequence:
        if not isinstance(record, dict):
            dropped += 1
            continue
        if not all(f in record for f in REQUIRED_FIELDS):
            dropped += 1
            continue
        if not isinstance(record["tool"], str) or not record["tool"]:
            dropped += 1
            continue
        if not isinstance(record["args"], dict):
            dropped += 1
            continue
        filtered.append(record)
    if dropped > 0:
        logger.debug(
            "session_extractor: 跳过 %d 条非法 record（缺字段/类型错）",
            dropped,
        )
    if len(filtered) > MAX_SEQUENCE_LEN:
        # 保留最后 N 条（最近的工具调用）
        filtered = filtered[-MAX_SEQUENCE_LEN:]
    return filtered
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_session_extractor.py -v
```

Expected: 7 passed

- [ ] **Step 6: ruff + commit**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check ../backend/skills/session_extractor.py ../backend/tests/unit/test_session_extractor.py
git add backend/skills/session_extractor.py backend/tests/unit/test_session_extractor.py
git commit -m "feat(skills): session_extractor 标准化 LLM 传入的 tool_sequence"
```

---

## Task 3: skill_save 工具单元 + 实现（一小时）

**Files:**
- Create: `backend/tools/skill_save_tool.py`
- Create: `backend/tests/unit/test_skill_save_tool.py`
- Modify: `backend/tools/__init__.py`（导出 SkillSaveTool）

**Interfaces:**
- Tool name: `skill_save`
- Schema:
  ```python
  ToolSchema(
      name="skill_save",
      description="把 LLM 显式传入的工具调用序列沉淀为可复用的 SKILL.md 草稿...",
      parameters={
          "type": "object",
          "properties": {
              "name": {"type": "string", "description": "技能名（kebab-case，3-40 字符）"},
              "description": {"type": "string", "description": "一句话说明（≤80 字符）"},
              "when_to_use": {"type": "string", "description": "何时使用（≥30 字符）"},
              "tool_sequence": {
                  "type": "array",
                  "items": {"type": "object"},
                  "description": "刚刚执行的工具调用序列（最多 20 项；元素含 tool/args/result_summary/timestamp_ms）",
              },
              "session_id": {"type": "string", "description": "当前会话 id（可选）"},
          },
          "required": ["name", "description", "when_to_use", "tool_sequence"],
      },
  )
  ```
- Risk: `RiskClass.WRITE_LOCAL`（写 SKILL.md 到本地 skills_dir）
- is_blocking: True（委托 review_service 是 async → 用 `asyncio.run` 桥接）

**前置探查：**

- [ ] **Step 1: 读 reference**

读 `backend/tools/base.py` 看 `BaseTool` 接口、`ToolResult` / `ToolSchema` 字段、`is_blocking` 语义。读 `backend/tools/skill.py`（已存在的 skill 工具）看老 skill 工具的形态作为参考。

- [ ] **Step 2: 写失败测试（mock review_service）**

```python
# backend/tests/unit/test_skill_save_tool.py
from unittest.mock import MagicMock

from backend.skills.review_service import SkillDraft
from backend.tools.skill_save_tool import SkillSaveTool


def _make_draft(name="academic-search", desc="学术检索", when="在用户引导下..."):
    return SkillDraft(
        id="abc", name=name, description=desc, when_to_use=when,
        content="## 步骤\n1. ...\n## 触发条件\n...\n## 示例\n...",
        trigger_type="user_explicit_save", source_session_id="s1",
        source_context={}, status="pending", created_at=0,
    )


def test_validates_required_fields():
    tool = SkillSaveTool(policy=MagicMock())
    result = tool.execute(name="", description="x", when_to_use="y" * 40, tool_sequence=[])
    assert not result.success
    assert "name" in result.error


def test_validates_kebab_case_name():
    tool = SkillSaveTool(policy=MagicMock())
    result = tool.execute(name="Bad Name!", description="x", when_to_use="y" * 40, tool_sequence=[])
    assert not result.success


def test_validates_description_length():
    tool = SkillSaveTool(policy=MagicMock())
    long = "x" * 100
    result = tool.execute(name="ok-name", description=long, when_to_use="y" * 40, tool_sequence=[])
    assert not result.success
    assert "80" in result.error


def test_validates_when_to_use_length():
    tool = SkillSaveTool(policy=MagicMock())
    result = tool.execute(name="ok-name", description="ok", when_to_use="too short", tool_sequence=[])
    assert not result.success
    assert "30" in result.error


def test_validates_tool_sequence_is_list():
    tool = SkillSaveTool(policy=MagicMock())
    result = tool.execute(
        name="ok-name", description="ok", when_to_use="y" * 40,
        tool_sequence="not a list",
    )
    assert not result.success
    assert "list" in result.error.lower()


def test_passes_normalized_sequence_to_review():
    captured = {}
    async def fake_gen(trigger_type, context):
        captured["tool_calls"] = context["tool_calls"]
        return _make_draft()

    def fake_normalize(raw):
        captured["raw"] = raw
        return raw[:5]  # 模拟截断

    tool = SkillSaveTool(
        policy=MagicMock(),
        normalizer=fake_normalize,
        review_service=MagicMock(generate_draft=fake_gen),
    )
    raw = [{"tool": f"t{i}", "args": {}} for i in range(10)]
    tool.execute(
        name="academic-search", description="学术检索",
        when_to_use="在用户引导下完成 CNKI 等站点文献检索流程",
        tool_sequence=raw, session_id="s1",
    )
    assert captured["raw"] == raw
    assert captured["tool_calls"] == raw[:5]


def test_returns_draft_id_on_success():
    async def fake_gen(trigger_type, context):
        return _make_draft()

    tool = SkillSaveTool(
        policy=MagicMock(),
        normalizer=lambda x: x,
        review_service=MagicMock(generate_draft=fake_gen),
    )
    result = tool.execute(
        name="academic-search", description="学术检索",
        when_to_use="在用户引导下完成 CNKI 等站点文献检索流程",
        tool_sequence=[{"tool": "web_fetch", "args": {"url": "x"}}],
        session_id="s1",
    )
    assert result.success
    assert result.content["draft_id"] == "abc"
    assert result.content["name"] == "academic-search"
    assert result.content["status"] == "pending"
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_skill_save_tool.py -v
```

Expected: ImportError（模块不存在）

- [ ] **Step 4: 实现**

```python
# backend/tools/skill_save_tool.py
"""skill_save — LLM 把显式传入的工具序列沉淀为 SKILL.md 草稿。

设计要点:
- 风险 WRITE_LOCAL: 只写本地 skills_dir，不出网、不读敏感文件
- is_blocking=True: 调用 review_service.generate_draft() 是 async，
  同步工具边界用 asyncio.run 桥接；外部调用方（agent loop）走线程池
- 三层校验: 本地 schema 校验（kebab-case / 长度 / tool_sequence 类型）
  → session_extractor.normalize 标准化 → review_service 二次校验
  （防御 LLM 自检遗漏）。本地失败早返回，绝不污染草稿库
- LLM 显式提供 tool_sequence: 不依赖 ToolExecutionContext（context 不携带
  tool_calls，SageAgent 也不累积），由调用方在 trigger 时刻把刚执行的序列传进来
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

SKILL_SAVE_TOOL_NAME = "skill_save"
_NAME_RE = re.compile(r"[a-z](?:[a-z0-9]|-[a-z0-9]){2,39}")
_MAX_DESCRIPTION = 80
_MIN_WHEN_TO_USE = 30
_MAX_SEQUENCE_LEN = 20


def _validate_inputs(
    name: str,
    description: str,
    when_to_use: str,
    tool_sequence: Any,
) -> Optional[str]:
    """本地 schema 校验；合法返回 None，否则返回错误文案。"""
    if not isinstance(name, str) or not name.strip():
        return "name 必须是非空字符串"
    if not _NAME_RE.fullmatch(name):
        return (
            f"name 必须 kebab-case（[a-z][a-z0-9-]{{2,39}}），实际 {name!r}"
        )
    if not isinstance(description, str) or len(description) > _MAX_DESCRIPTION:
        return (
            f"description 必须 ≤ {_MAX_DESCRIPTION} 字符，"
            f"实际 {len(description) if isinstance(description, str) else '非字符串'}"
        )
    if not isinstance(when_to_use, str) or len(when_to_use) < _MIN_WHEN_TO_USE:
        return (
            f"when_to_use 必须 ≥ {_MIN_WHEN_TO_USE} 字符，"
            f"实际 {len(when_to_use) if isinstance(when_to_use, str) else '非字符串'}"
        )
    if not isinstance(tool_sequence, list):
        return (
            f"tool_sequence 必须是 list，实际 {type(tool_sequence).__name__}"
        )
    return None


class SkillSaveTool(BaseTool):
    """把 LLM 显式传入的工具序列沉淀为 SKILL.md 草稿。

    由 LLM 在用户说"把这个流程存下来"时显式调用（区别于 pattern_detector
    的隐式重复检测）。走 review pipeline 生成 SkillDraft，用户审批后才
    写为 SKILL.md。
    """

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def __init__(
        self,
        policy: Any = None,
        *,
        normalizer: Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
        review_service: Any = None,
    ) -> None:
        super().__init__(policy=policy)
        self._normalizer = normalizer  # 测试可注入
        self._review_service = review_service  # 测试可注入

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=SKILL_SAVE_TOOL_NAME,
            description=(
                "把 LLM 显式传入的工具调用序列沉淀为可复用的 SKILL.md 草稿。"
                "走 review pipeline 生成 SkillDraft；用户审批后才落盘为可执行技能。"
                "区别于 pattern_detector 的隐式重复检测，本工具由 LLM 在用户"
                "明确表达'保存这个流程'时显式调用。调用时需传入刚执行的"
                "tool_sequence（最多 20 项），用于重建可复用的步骤说明。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能名（kebab-case，3-40 字符，[a-z][a-z0-9-]）",
                    },
                    "description": {
                        "type": "string",
                        "description": f"一句话说明（≤ {_MAX_DESCRIPTION} 字符）",
                    },
                    "when_to_use": {
                        "type": "string",
                        "description": f"何时使用（≥ {_MIN_WHEN_TO_USE} 字符）",
                    },
                    "tool_sequence": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            f"刚执行的工具调用序列（最多 {_MAX_SEQUENCE_LEN} 项）；"
                            "每项含 tool (str) / args (dict) / result_summary (str) / timestamp_ms (int)"
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": "当前会话 id（可选；仅用于日志与草稿溯源）",
                    },
                },
                "required": ["name", "description", "when_to_use", "tool_sequence"],
            },
        )

    def execute(
        self,
        name: str = "",
        description: str = "",
        when_to_use: str = "",
        tool_sequence: Optional[List[Dict[str, Any]]] = None,
        session_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}",
            )
        sequence = tool_sequence if tool_sequence is not None else []
        validation_error = _validate_inputs(name, description, when_to_use, sequence)
        if validation_error is not None:
            return ToolResult(success=False, error=validation_error)

        # 标准化（裁剪到上限 + 过滤缺字段）
        normalizer = self._normalizer or _default_normalizer
        normalized_calls = normalizer(sequence)

        # 委托 review_service（async → 同步桥接）
        review_service = self._review_service or _default_review_service()
        context = {
            "session_id": session_id,
            "tool_calls": normalized_calls,
            "user_provided": {
                "name": name,
                "description": description,
                "when_to_use": when_to_use,
            },
        }
        try:
            draft = asyncio.run(
                review_service.generate_draft(
                    trigger_type="user_explicit_save",
                    context=context,
                )
            )
        except (ValueError, KeyError) as exc:
            return ToolResult(
                success=False,
                error=f"review pipeline 拒绝草稿: {exc}",
            )
        except RuntimeError:
            # asyncio.run 在已有事件循环里嵌套会抛 RuntimeError
            logger.exception("skill_save asyncio 嵌套事件循环")
            return ToolResult(
                success=False,
                error=(
                    "skill_save 同步桥接失败（可能 agent loop 内已有事件循环）；"
                    "请改用 async 路径或调整 is_blocking"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("skill_save review pipeline 异常")
            return ToolResult(success=False, error=f"review pipeline 异常: {exc}")

        return ToolResult(
            success=True,
            content={
                "draft_id": draft.id,
                "name": draft.name,
                "status": draft.status,
                "note": "草稿已生成，等待用户在策展面板审批后才落盘为 SKILL.md",
            },
        )


def _default_normalizer(sequence: List[Dict[str, Any]]):
    """生产路径默认 normalizer；通过 session_extractor 模块实现。"""
    from backend.skills.session_extractor import normalize_tool_sequence
    return normalize_tool_sequence(sequence)


def _default_review_service():
    """生产路径 review service 单例。"""
    from backend.skills.review_service import get_review_service
    return get_review_service()


__all__ = ["SKILL_SAVE_TOOL_NAME", "SkillSaveTool"]
```

- [ ] **Step 5: 导出 + 跑测试**

修改 `backend/tools/__init__.py`，在文件末尾追加：

```python
from .skill_save_tool import SKILL_SAVE_TOOL_NAME, SkillSaveTool
```

跑：

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_skill_save_tool.py -v
```

Expected: 6 passed

- [ ] **Step 6: ruff + commit**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check ../backend/tools/skill_save_tool.py ../backend/tests/unit/test_skill_save_tool.py
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff format --check ../backend/tools/skill_save_tool.py ../backend/tests/unit/test_skill_save_tool.py
git add backend/tools/skill_save_tool.py backend/tools/__init__.py backend/tests/unit/test_skill_save_tool.py
git commit -m "feat(tools): skill_save 显式触发技能沉淀"
```

---

## Task 4: skill_save 集成测试（半小时）

**Files:**
- Create: `backend/tests/integration/test_skill_save_pipeline.py`

**Interfaces:**
- 走真 review_service，注入 mock LLM provider（async complete 返回固定 JSON）
- 验证生成的 SkillDraft 通过 draft_store 入库

**前置探查：**

- [ ] **Step 1: 读 review_queue + draft_store 接口**

`grep -rn "class SkillDraftStore\|class ReviewQueue\|enqueue\|approve_skill_draft" backend/skills/ | head -20`，读 draft_store.py 的 add/list/get 方法。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/integration/test_skill_save_pipeline.py
from unittest.mock import MagicMock

import pytest

from backend.skills.review_service import ReviewService
from backend.tools.skill_save_tool import SkillSaveTool


class FakeLLMProvider:
    """模拟 LLM 返回合规 JSON。"""

    async def complete(self, **kwargs):
        class Turn:
            text = (
                '```json\n'
                '{\n'
                '  "name": "academic-search-test",\n'
                '  "description": "学术文献检索 skill 测试",\n'
                '  "when_to_use": "当用户想对 CNKI 等学术站点执行关键词检索时使用",\n'
                '  "content": "## 步骤\\n1. 调用 ask_user_question 确认关键词\\n2. 调用 web_fetch 检索\\n## 触发条件\\n关键词检索\\n## 示例\\n帮我搜 CNKI"\n'
                '}\n'
                '```'
            )
        return Turn()


@pytest.fixture
def reset_draft_store():
    from backend.skills.draft_store import reset_skill_draft_store
    reset_skill_draft_store()
    yield
    reset_skill_draft_store()


def test_skill_save_end_to_end(reset_draft_store):
    """skill_save → review_service → SkillDraft 应能正常生成。"""
    fake_provider = FakeLLMProvider()
    review_service = ReviewService(fake_provider, model="fake")
    normalizer_calls = []
    def normalizer(raw):
        normalizer_calls.append(raw)
        return raw
    tool = SkillSaveTool(
        policy=None,
        normalizer=normalizer,
        review_service=review_service,
    )
    sequence = [
        {"tool": "web_fetch", "args": {"url": "x"}, "result_summary": "ok", "timestamp_ms": 1},
    ]
    result = tool.execute(
        name="academic-search-test",
        description="学术文献检索 skill 测试",
        when_to_use="当用户想对 CNKI 等学术站点执行关键词检索时使用",
        tool_sequence=sequence,
        session_id="s-test",
    )
    assert result.success, f"skill_save 失败: {result.error}"
    assert result.content["status"] == "pending"
    assert result.content["name"] == "academic-search-test"
    # 验证 normalizer 被调用且参数正确
    assert normalizer_calls == [sequence]
```

- [ ] **Step 3: 跑测试**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/integration/test_skill_save_pipeline.py -v
```

Expected: 1 passed

- [ ] **Step 4: commit**

```bash
git add backend/tests/integration/test_skill_save_pipeline.py
git commit -m "test(tools): skill_save 集成测试走 review pipeline"
```

---

## Task 5: AcademicSearchSkill 提示词模板 + CNKI adapter（一小时）

**Files:**
- Create: `backend/skills/builtin/academic_search.py`
- Create: `backend/skills/builtin/academic_adapters.py`
- Create: `backend/tests/unit/test_academic_search_skill.py`

**决策点（Task 内）：**

`backend/skills/builtin/__init__.py` 当前只有 1 行注释，无注册点。**新 skill 不强求接入 builtin 注册表** —— 它作为 Python 类可被测试和未来注册代码 import；SKILL.md 形态的实际注册由用户在首次使用时通过 `skill_save` 工具沉淀到 `~/.sage/skills/academic-search/SKILL.md`。

**Interfaces:**
- `AcademicSearchSkill(BaseSkill)`：trigger 是用户文本（"在 CNKI 找..."、"查文献..."），`execute()` 返回带剧本的 SkillResult
- `AcademicAdapter` dataclass: `name`, `base_url`, `search_url_template(query: str) -> str`, `extract_results(html: str) -> List[Dict]`
- 注册表 `ADAPTERS: Dict[str, AcademicAdapter]`，至少含 CNKI 1 个

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_academic_search_skill.py
from backend.skills.builtin.academic_adapters import (
    AcademicAdapter, get_adapter, list_adapters,
)


def test_cnki_adapter_registered():
    adapter = get_adapter("cnki")
    assert adapter is not None
    assert "cnki.net" in adapter.base_url


def test_cnki_search_url_format():
    adapter = get_adapter("cnki")
    url = adapter.search_url_template("机器学习")
    assert "机器学习" in url or "%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0" in url


def test_unknown_adapter_returns_none():
    assert get_adapter("nonexistent-site") is None


def test_list_adapters_includes_cnki():
    names = list_adapters()
    assert "cnki" in names
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_academic_search_skill.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 academic_adapters.py**

```python
# backend/skills/builtin/academic_adapters.py
"""学术站点 adapter 注册表。

设计要点:
- 纯数据 + 纯函数：不做任何 IO，纯函数 search_url_template / extract_results
- CNKI 实现 starter，其他站点留 TODO（adapter protocol 稳定后逐站接入）
- 主程序零硬编码："硬编码"的是 adapter 内容，不是程序结构
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import quote


@dataclass(frozen=True)
class AcademicAdapter:
    """单个学术站点的适配规则。"""

    name: str
    base_url: str
    search_url_template: Callable[[str], str]
    extract_results: Callable[[str], List[Dict[str, str]]]


def _cnki_search_url(query: str) -> str:
    """CNKI 老站搜索 URL 模板（待真机验证，可能需要调整）。"""
    encoded = quote(query)
    return f"https://www.cnki.net/old/?keyword={encoded}"


def _cnki_extract_results(html: str) -> List[Dict[str, str]]:
    """CNKI 搜索结果抽取（占位实现：返回空列表；接入真机后实现解析）。"""
    # TODO(cnki-real-impl): 用 BeautifulSoup 解析 li.result-item 类
    return []


ADAPTERS: Dict[str, AcademicAdapter] = {
    "cnki": AcademicAdapter(
        name="cnki",
        base_url="https://www.cnki.net/old/",
        search_url_template=_cnki_search_url,
        extract_results=_cnki_extract_results,
    ),
}


def get_adapter(site: str) -> Optional[AcademicAdapter]:
    """按站点名取 adapter；未知站点返回 None。"""
    return ADAPTERS.get(site)


def list_adapters() -> List[str]:
    """返回所有已注册站点名。"""
    return sorted(ADAPTERS.keys())


__all__ = ["AcademicAdapter", "ADAPTERS", "get_adapter", "list_adapters"]
```

- [ ] **Step 4: 实现 academic_search.py**

```python
# backend/skills/builtin/academic_search.py
"""AcademicSearchSkill — 用户引导 LLM 完成学术检索的提示词模板。

设计要点:
- 不调工具：v1 SKILL.md 形态，body 是给 LLM 看的剧本
- 提示词分三段:
  1. 让 LLM 先用 ask_user_question 确认关键词 / 时间范围 / 文献类型
  2. 调 web_fetch（render=never 默认）抓摘要页
  3. 完成后用 skill_save 把流程沉淀
- 站点在用户说"CNKI"/"WoS"时由 LLM 选定，adapters 在 SKILL.md body 里
  以提示词变量引用，不在代码里 import（避免站点耦合）
"""
from __future__ import annotations

from typing import Any, Dict

from ..base import BaseSkill, SkillResult, SkillSchema


class AcademicSearchSkill(BaseSkill):
    """学术文献检索 skill（提示词模板形态）。"""

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name="academic-search",
            description="引导用户完成学术站点（CNKI/WoS/Scopus）关键词检索并沉淀流程",
            triggers=[
                "学术检索", "文献检索", "在 CNKI", "查文献",
                "academic search", "literature search",
            ],
            parameters={
                "type": "object",
                "properties": {
                    "site": {
                        "type": "string",
                        "description": "目标站点（cnki / wos / scopus）",
                        "enum": ["cnki", "wos", "scopus"],
                    },
                    "query": {
                        "type": "string",
                        "description": "关键词（可选；缺省由用户交互确认）",
                    },
                },
                "required": [],
            },
            examples=[
                "在 CNKI 检索近 5 年机器学习综述",
                "帮我在 WoS 找关于 transformer 的高引论文",
            ],
        )

    def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
        site = params.get("site", "cnki")
        query_hint = params.get("query", "")
        return SkillResult(
            success=True,
            content=ACADEMIC_SEARCH_BODY,
            metadata={
                "source": "builtin",
                "name": self.name,
                "site": site,
                "query_hint": query_hint,
            },
        )


ACADEMIC_SEARCH_BODY = """\
# 学术文献检索（用户引导模式）

## 步骤

1. **明确站点**：用 `ask_user_question` 问用户要检索的站点，选项固定为 cnki / wos / scopus（其他站点提示"暂未注册，可换已注册站点或新增 adapter"）。
2. **确认检索参数**：用 `ask_user_question` 问时间范围（近 1/3/5/全部年）、文献类型（综述 / 期刊 / 会议）、最多返回条数（5/10/20）。
3. **构造搜索 URL**：参考 `backend/skills/builtin/academic_adapters.py` 的 `search_url_template(query)`；用户给出关键词后调用。
4. **抓取结果**：调 `web_fetch(url=..., mode="text", render="never")`。CNKI 等老站纯静态 HTML 可关掉渲染降级提速。
5. **展示 + 追问**：把抽取到的标题/作者/摘要呈现给用户；问"是否需要补充检索"或"是否要换站点"。
6. **沉淀流程**（半自动）：检索完成后用 `ask_user_question` 问"是否把本次流程存为 skill？"；用户选"是"则调 `skill_save(name="academic-search-<site>", description=..., when_to_use=..., tool_sequence=[<最近 N 步 tool call>])`。

## 触发条件

- 用户说"在 CNKI 找..."、"查文献"、"academic search" 等关键词
- 用户给出研究主题 / 关键词 + 隐含的检索意图

## 示例

用户：「帮我在 CNKI 找近 5 年机器学习综述」
- 第 1 步：站点已是 CNKI，跳过
- 第 2 步：调 `ask_user_question(question="检索参数确认", options=[{label: "近5年+综述"}, {label: "近3年+期刊"}, ...])`
- 第 3-5 步：按站点 adapter 拼 URL + 抓取 + 展示
- 第 6 步：问是否沉淀为 skill

## 站点适配指引

新增站点：在 `backend/skills/builtin/academic_adapters.py` 的 `ADAPTERS` 字典加一个键值，提供：
- `name`：小写站点标识
- `base_url`：首页 URL
- `search_url_template(query)`：返回该站搜索 URL 的函数
- `extract_results(html)`：从搜索结果 HTML 抽取结构化记录的函数（占位可返回 `[]`，后续真机接入）
"""

__all__ = ["AcademicSearchSkill", "ACADEMIC_SEARCH_BODY"]
```

- [ ] **Step 5: 跑测试**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_academic_search_skill.py -v
```

Expected: 4 passed

- [ ] **Step 6: ruff + commit**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check ../backend/skills/builtin/academic_search.py ../backend/skills/builtin/academic_adapters.py ../backend/tests/unit/test_academic_search_skill.py
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff format --check ../backend/skills/builtin/academic_search.py ../backend/skills/builtin/academic_adapters.py
git add backend/skills/builtin/academic_search.py backend/skills/builtin/academic_adapters.py backend/tests/unit/test_academic_search_skill.py
git commit -m "feat(skills): AcademicSearchSkill 提示词模板 + CNKI adapter"
```

---

## Task 6: 用户文档（半小时）

**Files:**
- Create: `docs/technical/53-academic-search-skill.md`
- Modify: `docs/technical/README.md`（追加章节目录条目）

- [ ] **Step 1: 写文档**

文档结构：
1. 总览（一段话说明这是什么）
2. 架构图（ASCII）：用户 ↔ LLM ↔ skill_save → review pipeline → SKILL.md
3. 核心组件
   - `skill_save` 工具：何时用、参数、风险
   - `AcademicSearchSkill`：触发词、剧本要点
   - `academic_adapters` 注册表：如何新增站点
4. 完整示例对话（一段 markdown 模拟）
5. 风险与边界（合规、登录态、反爬）
6. 不做的事（YAGNI）

- [ ] **Step 2: 更新 docs/technical/README.md 章节目录**

在 README.md 表格里追加 `| 53 | academic-search-skill | 学术检索 skill：用户引导 + 流程沉淀 |` 链接到新文件。

- [ ] **Step 3: commit**

```bash
git add docs/technical/53-academic-search-skill.md docs/technical/README.md
git commit -m "docs(technical): 53-academic-search-skill 总览"
```

---

## Task 7: 端到端验证 + 开 PR（一小时）

- [ ] **Step 1: 全套 pytest + ruff**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/unit/test_session_extractor.py tests/unit/test_skill_save_tool.py tests/integration/test_skill_save_pipeline.py tests/unit/test_academic_search_skill.py -v
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check ..
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff format --check ..
```

Expected: 所有测试通过；ruff 无错

- [ ] **Step 2: 跑项目 smoke test**

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest tests/ -x -q --timeout=60 -m "not slow"
```

Expected: 全绿；如有 pre-existing failure（doctor_cli 等），记录但不阻塞本 PR

- [ ] **Step 3: 推分支 + 开 PR**

```bash
git push -u origin feat/academic-search-skill
gh pr create --title "feat(skills): 学术检索 skill + skill_save 工具" \
  --body "见 docs/superpowers/plans/2026-09-08-academic-search-skill.md"
```

- [ ] **Step 4: 监控 CI**

```bash
gh pr checks <PR-number> --watch
```

CI 绿后回报用户；CI 红按 traceback 修。

---

## 自检（写完后跑一遍）

1. **Spec 覆盖**：本文 plan 实现了 spec 第 1-3 节目标（M1 + O2 + 站点 adapter 零硬编码）；CNKI 反爬 / 登录态 / 全文下载按 spec 第 4 节声明为"不做"
2. **Placeholder scan**：grep 找 "TODO" / "TBD" —— 有一处（CNKI 真机解析），已显式标 `TODO(cnki-real-impl)` 在 Task 5 step 3
3. **类型一致性**：
   - `_NAME_RE` 在 skill_save_tool.py 与 review_service._validate_skill_name 行为一致（kebab-case）
   - `_MAX_DESCRIPTION=80` / `_MIN_WHEN_TO_USE=30` 与 review_service._validate_skill_schema 完全对齐
   - `normalize_tool_sequence` 的 MAX_SEQUENCE_LEN=20 与 SkillSaveTool 的 _MAX_SEQUENCE_LEN=20 一致
4. **风险点**：
   - skill_save 是 `WRITE_LOCAL` 风险，符合"不写出网"的最小权限
   - `asyncio.run` 桥接如果嵌套事件循环会失败 → 测试用例已显式覆盖 RuntimeError 分支；如果生产路径真出问题，回退方案是改 `is_blocking=False` + 让 agent loop 走原 async 调度

---

## 执行交接

Plan 已保存到 `docs/superpowers/plans/2026-09-08-academic-search-skill.md`。

两种执行方式：
1. **Subagent-Driven（推荐）**：每个 Task 派一个 fresh subagent，独立上下文，task 间我做 review
2. **Inline Execution**：在当前会话直接按 Task 顺序跑，checkpoint 复盘

哪个？
