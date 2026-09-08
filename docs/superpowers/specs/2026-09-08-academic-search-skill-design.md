# Academic Search Skill 设计 — Sub-project

> **日期**:2026-09-08
> **作者**:Claude (with user)
> **状态**:Draft — 待用户 review
> **分支**:`feat/academic-search-skill` (base: main)
> **Worktree**:`.worktrees/feat-academic-search-skill`
> **关联 plan**:`docs/superpowers/plans/2026-09-08-academic-search-skill.md`

## 背景与目标

Sage 已具备完整的 LLM 工具栈（`web_fetch` / `ask_user_question` / `browser_*` / `web_search` / `plan_tool` / `todo_tool` / `subagent_tool` / `memory`），用户想把这套工具用于**学术文献检索场景**（CNKI / Web of Science / Scopus 等），并把"用户引导 LLM 完成检索"的流程**沉淀为可复用 SKILL.md**，方便下次直接复用。

**目标**：
1. 不在主程序硬编码任何特定站点（CNKI / WoS / Scopus）逻辑 —— 主程序零硬编码是底线
2. 提供"流程沉淀"基础能力（`skill_save` 工具），让 LLM 在用户明确表达"把这个流程存下来"时把刚执行的工具序列转成 SkillDraft
3. 给出**学术检索场景的 SKILL.md 模板**（`AcademicSearchSkill`），作为用户首次使用的样板
4. 提供**站点 adapter 注册表**（CNKI 优先），让 SKILL.md 内部的"调哪个 URL / 怎么解析"是数据驱动的

## 范围与非范围

**范围**:
- M1: `skill_save` 工具 —— LLM 显式触发技能沉淀的统一入口
- M2: `session_extractor.normalize_tool_sequence()` —— 校验/标准化 LLM 传入的工具序列（裁剪到 20 上限、过滤缺字段记录）
- O2: `AcademicSearchSkill` builtin class（提示词模板形态） + CNKI adapter
- O3: `docs/technical/53-academic-search-skill.md` 用户文档

**非范围**（YAGNI，刻意不做）:
- 主程序内 CNKI 解析逻辑（站点抽取留给 adapter 实现；本次 PR 占位返回 `[]`）
- 登录态持久化（CNKI 老站登录是浏览器 profile 级工作，超出本次范围）
- 全文下载 / 引用导出（属"扩展检索结果"，不是检索流程本身）
- 反爬应对（合规边界：让用户在他自己的浏览器里走流程，不绕反爬）
- 主程序 ContextVar 加 `tool_calls` 字段（已探明 `ToolExecutionContext` 字段固化、SageAgent 不累积，加字段会动 16+ 测试 fixture —— 方案 B 规避）

## 关键发现（设计过程中）

源码勘察发现 3 个关键事实，决定了最终方案：

| 探查点 | 现状 | 影响 |
|---|---|---|
| `backend/skills/builtin/__init__.py` | 仅 1 行注释，无注册点 | 4 个 builtin skill（coder/search/travel/writer）**没在主程序注册**，grep 0 命中 |
| `SkillMdSkill.execute()` v1 / v2 | v1 只返回 body 不调工具；v2 走 ScriptRunner 沙箱 | 实际可用的 skill 形态只有 SKILL.md（**给 LLM 看的提示词模板**），不是程序模块 |
| `ToolExecutionContext` 字段 | 固化 session_id/stream_id/binding_generation/office_doc_scope，**无 tool_calls**；`SageAgent` 在 agent.py:595-661 直接调 `tool.execute()` 不累积 | `skill_save` 无法从会话历史自动抽取 tool_calls；LLM 必须**显式传 `tool_sequence`** |

**这 3 个事实决定了：**
1. M1 工具入口必须存在 —— builtin skill 不能注册，SKILL.md 不能调工具栈，只能让 LLM 在执行过程中显式触发沉淀
2. `tool_sequence` 是必填参数 —— 由 LLM 在调 skill_save 时把刚执行的步骤塞进来
3. CNKI 解析逻辑不放主程序 —— 放 adapter 注册表，SKILL.md body 用站点名引用

## 设计

### 子项 1: skill_save 工具（M1）

**文件**: `backend/tools/skill_save_tool.py`

**接口**:
```python
class SkillSaveTool(BaseTool):
    risk = RiskClass.WRITE_LOCAL  # 写 SKILL.md 到本地 skills_dir
    is_blocking = True  # 委托 review_service.generate_draft() 是 async
    requires_tool_context = False  # 不依赖 session context

    # ToolSchema 关键字段
    parameters.properties = {
        "name": {"type": "string", "description": "kebab-case, 3-40 字符"},
        "description": {"type": "string", "description": "≤ 80 字符"},
        "when_to_use": {"type": "string", "description": "≥ 30 字符"},
        "tool_sequence": {
            "type": "array",
            "items": {"type": "object"},
            "description": "刚执行的工具调用序列（最多 20 项）",
        },
        "session_id": {"type": "string", "description": "可选；用于日志/溯源"},
    }
    parameters.required = ["name", "description", "when_to_use", "tool_sequence"]
```

**执行流程**:
1. 本地 schema 校验（kebab-case / 长度 / tool_sequence 类型）
2. 委托 `session_extractor.normalize_tool_sequence()` 标准化（裁剪到 20、过滤缺字段）
3. `asyncio.run(review_service.generate_draft(trigger_type="user_explicit_save", context={...}))` 桥接 sync → async
4. 返回 `{draft_id, name, status: "pending", note: "等待用户审批"}`

**为什么走 `asyncio.run`**:
- BaseTool.execute() 是同步签名（被 chat 层同步调用）
- review_service.generate_draft() 是 async（接受 LLM provider.complete()）
- `asyncio.run` 桥接；如果 agent loop 内已有事件循环会抛 `RuntimeError` → 工具捕获返回明确错误（不污染草稿库）

**风险等级 WRITE_LOCAL 的理由**:
- 写本地 `~/.sage/skills/<name>/SKILL.md`（在 skill_loader 的 skills_dir 范围内）
- 不出网、不读敏感文件
- 比 EXEC / EXTERNAL 风险低，符合"最小权限"原则

**失败模式**:
| 失败 | 行为 |
|---|---|
| 本地 schema 校验失败（name/description/when_to_use/tool_sequence） | 早返回 ToolResult(success=False, error=...)；不调 review pipeline |
| tool_sequence 全是缺字段记录 | 正常返回（review pipeline 拿到空 tool_calls 仍能产出草稿） |
| review_service ValueError / KeyError | 返回 `error: "review pipeline 拒绝草稿: ..."` |
| asyncio.run RuntimeError（嵌套事件循环） | 返回明确错误，提示改 is_blocking 或 async 路径 |
| LLM provider 异常 | 返回 `error: "review pipeline 异常: ..."` |

### 子项 2: session_extractor（M2）

**文件**: `backend/skills/session_extractor.py`

**接口**:
```python
MAX_SEQUENCE_LEN = 20
REQUIRED_FIELDS = ("tool", "args")

def normalize_tool_sequence(
    raw_sequence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """校验并裁剪 LLM 传入的工具调用序列。

    - 过滤掉非 dict / 缺 tool / 缺 args / tool 非字符串 / args 非 dict 的记录
    - 裁剪到 MAX_SEQUENCE_LEN（保留最后 N 条，丢弃最旧的）
    - 不修改输入（返回新列表）
    """
```

**为什么是"标准化"而非"提取"**:
- 原 plan 名 `extract_recent_tool_calls(session_id, n, calls)` —— 隐含了"从会话历史抽 N 步"语义
- 方案 B 改为 LLM 显式传入 → 函数职责变为"校验 + 裁剪 LLM 给的数据"
- 名字从 `extract` 改为 `normalize`，更贴合实际职责

**可选字段 `result_summary` / `timestamp_ms` 缺省合法**:
- LLM 可能简化输出，只给 `{tool, args}`
- 这两个字段仅用于 review prompt 的上下文丰富度，不是必需

### 子项 3: AcademicSearchSkill builtin class（O2）

**文件**: `backend/skills/builtin/academic_search.py` + `academic_adapters.py`

**builtin class 的角色**:
- 不注册到主程序（与 4 个既有 builtin skill 现状一致）
- **作为 Python 类存在，方便单元测试和未来复用**
- SKILL.md body 字符串以常量 `ACADEMIC_SEARCH_BODY` 暴露，作为 LLM 看的"剧本"模板

**ACADEMIC_SEARCH_BODY 关键内容**:
```
# 学术文献检索（用户引导模式）

## 步骤
1. 用 ask_user_question 问站点（cnki/wos/scopus）
2. 用 ask_user_question 问时间范围 / 文献类型 / 最多条数
3. 按 academic_adapters.py 的 search_url_template(query) 拼 URL
4. 调 web_fetch(url, mode="text", render="never")
5. 展示结果 + 追问
6. 用 ask_user_question 问"是否沉淀 skill"，是则调 skill_save(...)

## 触发条件
- "在 CNKI 找..." / "查文献" / "academic search"

## 示例
用户：「帮我在 CNKI 找近 5 年机器学习综述」
- ...
```

**adapter 注册表**:
```python
@dataclass(frozen=True)
class AcademicAdapter:
    name: str
    base_url: str
    search_url_template: Callable[[str], str]
    extract_results: Callable[[str], List[Dict[str, str]]]

ADAPTERS: Dict[str, AcademicAdapter] = {
    "cnki": AcademicAdapter(
        name="cnki",
        base_url="https://www.cnki.net/old/",
        search_url_template=_cnki_search_url,
        extract_results=_cnki_extract_results,  # 占位：返回 []
    ),
}
```

**`extract_results` 占位返回 `[]` 的理由**:
- CNKI 真机解析需要登录态 / 反爬考量，留待后续真机接入
- 本次 PR 只建立"adapter 协议稳定"基线，不实际解析 HTML
- TODO(cnki-real-impl) 显式标注在代码里

### 子项 4: 用户文档（O3）

**文件**: `docs/technical/53-academic-search-skill.md`

**结构**:
1. 总览（一段话说明是什么）
2. 架构图（ASCII）：用户 ↔ LLM ↔ skill_save → review pipeline → SKILL.md
3. 核心组件
   - skill_save 工具：何时用、参数、风险
   - AcademicSearchSkill：触发词、剧本要点
   - academic_adapters 注册表：如何新增站点
4. 完整示例对话（一段 markdown 模拟）
5. 风险与边界（合规、登录态、反爬）
6. 不做的事（YAGNI）

**同时更新** `docs/technical/README.md` 章节目录（追加第 53 章链接）。

## 风险与合规边界

| 风险 | 应对 |
|---|---|
| CNKI 反爬 | 不在本 PR 范围；用户在 SKILL.md 剧本里走自己的浏览器 |
| 登录态 | 本 PR 不做；后续可加 `browser_navigate` 触发用户手动登录 |
| 全文下载 / 引用导出 | YAGNI，不做 |
| skill_save 异步桥接 | 已显式处理嵌套 RuntimeError |
| LLM provider 不可用 | `_build_review_config()` 已 fail-closed（`_UnavailableReviewProvider`） |
| 草稿名冲突 / 路径穿越 | `review_service._validate_skill_name` 强制 kebab-case + 拒绝 `..` / `/` / `\` |

## 实施步骤（简版，详细见 plan）

1. **Task 1（本文档）**: 写 spec，请用户 review
2. **Task 2**: session_extractor 单元 + 实现（7 个单元测试）
3. **Task 3**: skill_save 工具单元 + 实现（7 个单元测试 + 导出）
4. **Task 4**: skill_save 集成测试（1 个端到端测试 + FakeLLMProvider）
5. **Task 5**: AcademicSearchSkill + CNKI adapter（4 个单元测试）
6. **Task 6**: 用户文档（53 章 + README 更新）
7. **Task 7**: 端到端验证 + 开 PR

## 测试覆盖目标

- session_extractor: 7 个单元测试（空列表 / 短于上限 / 超过上限 / 缺字段 / 类型错 / 可选字段缺省 / 不修改输入）
- skill_save tool: 7 个单元测试（4 个校验失败 + 1 个类型错 + 1 个 normalizer 注入 + 1 个 success）
- skill_save pipeline: 1 个集成测试（end-to-end with FakeLLMProvider）
- academic_search skill: 4 个单元测试（CNKI 注册 / search URL 格式 / unknown site 返回 None / list_adapters 含 cnki）

合计 **19 个测试**，覆盖三层：纯函数（session_extractor）→ 工具边界（skill_save）→ 流程集成（pipeline）→ builtin 数据（academic_adapters）。

## 不做的事（YAGNI）

- ❌ CNKI 真机 HTML 解析（adapter 占位 `[]`，留待后续真机接入）
- ❌ ToolExecutionContext 加 `tool_calls` 字段（动 16+ 测试 fixture，方案 B 规避）
- ❌ 主程序自动注册 builtin skill（与 4 个既有 builtin skill 现状一致，不在本 PR 改）
- ❌ skill_save 异步路径（BaseTool 是 sync 接口；asyncio.run 已够用）
- ❌ 自动激活 SKILL.md（spec 04 `when_to_use` 已用，但本次不接聊天层自动匹配；留给后续 PR）
- ❌ 多站点 adapter 实际解析（CNKI 1 个占位已足够说明协议）

## 与现有规则 / spec 的关系

- 继承 `backend/skills/` 既有架构（review_service + draft_store + loader + lifecycle）—— 不重写
- 遵循 `backend/tools/base.py` BaseTool 接口（risk / is_blocking / execute 签名）
- SKILL.md 内容约束走 `review_service._validate_skill_schema`（kebab-case / 长度 / 三段必备）
- 命名规范走 `review_service._validate_skill_name`（拒绝 `..` / `/` / `\`）
- 工作流遵循 `.claude/CLAUDE.md` 全局约束（sage-backend conda env / 端口约定 / 不动 release/win7）
