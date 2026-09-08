# 学术检索 skill 与 skill_save 工具

> **创建日期**: 2026-09-08
> **分支**: `feat/academic-search-skill`
> **状态**: ✅ 已交付（M1 skill_save + O2 AcademicSearchSkill + CNKI adapter）

---

## 1. 总览

本专题交付两件配套能力:

- **`skill_save` 工具**(M1)——让 LLM 在用户授权下,把一次成功的多步工具调用序列
  + 用户给定的描述,沉淀为草稿 skill(进入 `skill_drafts` 表等人工 review)。
- **`AcademicSearchSkill`**(O2)——一个示例 builtin skill,把"在文献站点检索 →
  抓结果页 → 让用户挑排序偏好 → 整理摘要"这一流程**骨架**化,实际页面解析
  仍交给 LLM,站点差异通过 `academic_adapters` 的 URL 模板适配。

两者配合实现了"先有基础能力 + skill 复用机制,再有一个具体示例"的闭环:CNKI
只是其中一个 adapter,后续要加 PubMed / Google Scholar / arXiv 等只需注册新
adapter,不必改 skill 本体。

---

## 2. 架构图

```
┌────────┐  触发词(找文献/检索论文/...)   ┌─────────┐
│  用户  │ ──────────────────────────► │   LLM   │
└────────┘                              └────┬────┘
       ▲                                     │
       │  ① 调用 AcademicSearchSkill.execute │
       │  ② (可选) ask_user_question 排序     │
       │  ③ 返回结构化 prompt,LLM 解析页面     │
       │                                     ▼
       │                          ┌──────────────────────┐
       │                          │  AcademicSearchSkill │
       │                          │  (builtin skill)     │
       │                          └────┬─────────────┬───┘
       │                               │             │
       │              get_site_adapter │             │ 调 web_fetch
       │                               ▼             ▼
       │                  ┌─────────────────────┐  ┌──────────┐
       │                  │ academic_adapters   │  │ web_fetch │
       │                  │  (CNKI / PubMed /..) │  │  工具     │
       │                  └─────────────────────┘  └──────────┘
       │
       │  "把这个流程存为 skill"
       │
       │                          ┌──────────────────┐
       └────── 返回 SkillDraft ───│   skill_save      │
                                  │  (BaseTool)       │
                                  └────┬─────────────┘
                                       │ 走 sync→async bridge
                                       ▼
                            ┌─────────────────────┐
                            │  ReviewService      │
                            │  (LLM 二次校验)     │
                            └────┬────────────────┘
                                 │ SkillDraft
                                 ▼
                        ┌─────────────────────┐
                        │  SkillDraftStore    │
                        │  (SQLite 落盘)      │
                        │  status='pending'   │
                        └────┬────────────────┘
                             │ 人工审核
                             ▼
                        status='approved'
                             │
                             ▼
                        SKILL.md 装载
                        (复用为下次 skill)
```

---

## 3. 核心组件

### 3.1 `skill_save` 工具(M1)

**位置**: `backend/tools/skill_save_tool.py`

**何时用**: 用户明确说"把这个流程存为 skill / 记住这个流程 / 保存为模板"等。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | str | ✓ | skill 名(3-40 字符,kebab-case,正则 `[a-z](?:[a-z0-9]|-[a-z0-9]){2,39}`) |
| `description` | str | ✓ | ≤80 字符,描述 skill 做什么 |
| `when_to_use` | str | ✓ | ≥30 字符,描述触发条件 |
| `tool_sequence` | list | ✓ | 最近一次成功的工具调用序列(自动 normalizer 过滤) |
| `session_id` | str | ✗ | 当前会话 ID,用于追溯 |

**执行流程**:

1. **校验**: name 走 `SkillSaveTool._validate_skill_name`,content 必须含
   `## 步骤` / `## 触发条件` / `## 示例`,tool_sequence 元素必须是
   `{"tool": str, "args": dict}` 形态。
2. **走 sync→async bridge**(`_run_async`):从 LLM 异步生成草稿 → 在同步上下文
   中拿结果(三种分支:无 loop / 在 loop / 跨线程)。
3. **ReviewService 校验**: `generate_draft(trigger_type="user_explicit_save",
   context={...})` 内部再次调用 LLM 做 schema + 内容校验,产出 `SkillDraft`。
4. **持久化**: `SkillDraftStore.insert(draft)` → SQLite `skill_drafts` 表,
   `status="pending"`,`reviewed_at` / `reviewed_by_user_id` 为 NULL。
5. **返回**: `ToolResult(success=True, content={"draft_id", "name", "status"})`。

**风险**:

- ⚠️ 用户填的 `name` / `description` / `when_to_use` 必须是**用户原话或经用户
  同意**,不要让 LLM 自由发挥去编造触发条件。
- ⚠️ `tool_sequence` 会被 normalizer 过滤,只保留 `{"tool", "args"}` 形态;不要
  把包含敏感参数的调用(如 API token)塞进去。

### 3.2 `AcademicSearchSkill`(O2)

**位置**: `backend/skills/builtin/academic_search.py`

**触发词**: `["找文献", "检索论文", "学术搜索", "literature search",
"find papers", "academic search"]`

**剧本要点**(YAGNI,只做骨架):

1. 接收 `{query, site?, limit?}` 参数;校验 query 非空。
2. `get_site_adapter(site).build_search_url(query, limit)` → 构造检索结果页 URL。
3. 从 `context["tools"]` 取 `web_fetch`,抓检索页 HTML/Markdown。
4. (可选)从 `context["tools"]` 取 `ask_user_question`,让用户挑排序方式
   (按相关度 / 按时间 / 按引用数)。
5. 把以上信息 + 抓取到的页面片段(截断到 4000 字符)组装成结构化 prompt,
   让 LLM 完成**真正的语义提取**(标题/作者/期刊/年份/摘要)。
6. 返回 `SkillResult(success=True, content=<prompt>, metadata={query, site,
   limit, sort_pref, search_url, asked_user})`。

**不做的事**(YAGNI):

- ❌ 不内嵌 CNKI / PubMed / Google Scholar 的 HTML 解析——站点差异通过
  adapter URL 模板处理,页面解析交给 LLM。
- ❌ 不管理登录态——adapter 只构造 URL,登录后的结果不在 skill 范围内。
- ❌ 不引入新工具——复用 `web_fetch` / `ask_user_question` / `memory_save`。

### 3.3 `academic_adapters` 注册表

**位置**: `backend/skills/builtin/academic_adapters.py`

**Protocol**:

```python
@runtime_checkable
class AcademicSiteAdapter(Protocol):
    name: str
    def build_search_url(self, query: str, **kwargs: Any) -> str: ...
```

**当前注册**:

- `cnki` → `CNKIAdapter()`,URL 模板 `https://www.cnki.net/old/kns/brief/
  default_result.aspx`,query string 传 `Txt=...`、`t=<limit>`。

**新增站点**(3 步):

```python
# 1. 实现 adapter
class PubMedAdapter:
    name = "pubmed"
    def build_search_url(self, query: str, **kwargs: Any) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/?term={quote(query)}"

# 2. 注册
from backend.skills.builtin.academic_adapters import register_site_adapter
register_site_adapter(PubMedAdapter())

# 3. 使用
AcademicSearchSkill(site="pubmed")  # 或 params={"site": "pubmed"}
```

注册表是简单的 `dict[str, AcademicSiteAdapter]`,**没有 plugin 系统**(真有 N
个站点再升级)。

---

## 4. 完整示例对话

> **用户**: 帮我找 5 篇大语言模型综述
>
> **LLM**: (检测到触发词"找文献",调用 `AcademicSearchSkill.execute(
> params={"query": "大语言模型综述", "limit": 5},
> context={"tools": {"web_fetch": ..., "ask_user_question": ...}})`)
>
> **Skill**:
> 1. `get_site_adapter("cnki").build_search_url("大语言模型综述", limit=5)`
>    → `https://www.cnki.net/old/kns/brief/default_result.aspx?QueryID=0&
>    Txt=...&t=5`
> 2. `web_fetch.execute(url=...)` → 拿到结果页 HTML
> 3. `ask_user_question.execute(question="已从 cnki 检索到「大语言模型综述」的
>    结果,如何排序?", options=["按相关度", "按时间", "按引用数"])`
>    → 用户答"按相关度"
> 4. 组装 prompt 返回 SkillResult
>
> **LLM**: 解析结果页后,输出 5 篇文献的 Markdown 列表(标题 / 作者 / 期刊 /
> 年份 / 摘要)。
>
> **用户**: 这个流程挺好的,以后我每次想找文献都能用。帮我把这个流程存为 skill
> 吧,叫 `academic-search-cnki`。
>
> **LLM**: (检测到"存为 skill"触发词,先确认 when_to_use,然后调用
> `skill_save.execute(name="academic-search-cnki", description="在 CNKI 上检索
> 学术文献并整理摘要", when_to_use="当用户需要检索 CNKI 上的学术论文并按主题
> 整理摘要时使用", tool_sequence=[{"tool": "web_fetch", ...}, {"tool":
> "ask_user_question", ...}], session_id="sess-...")`)
>
> **Skill**: 走 review pipeline → SQLite 落盘 → 返回
> `draft_id="draft-abc123"`。
>
> **LLM**: ✅ 草稿已保存到 review 队列,`draft_id=draft-abc123`,等待人工审核。
> 审核通过后下次就能直接复用这个 skill。

---

## 5. 风险与边界

### 5.1 合规

- ⚠️ **学术检索场景**:CNKI 检索结果页本身受版权保护,本 skill **不抓全文**,
  只抓检索结果列表(标题/作者/期刊/摘要)。LLM 解析时也不应全文复制。
- ⚠️ `skill_save` 落盘的内容里**不应**包含用户敏感数据(API token、cookie、
  密码等);`tool_sequence` 的 normalizer 不会自动剔除这些字段。

### 5.2 登录态 / 反爬

- ❌ 当前 **不管理登录态**。如果站点需要登录(如 Web of Science),adapter
  构造的 URL 只能拿到公开检索页,登录后才能看到的全文不在 skill 范围内。
- ⚠️ `web_fetch` 走的是后端 HTTP 请求,如果站点有反爬(JS 渲染、Cookie 校验、
  验证码)可能拿不到结果。NetworkPolicy 三档门禁见
  [`46-intranet-web-access.md`](./46-intranet-web-access.md)。

### 5.3 Skill 沉淀副作用

- ⚠️ `skill_save` 调用后,草稿**必须经人工 review**(目前是异步队列 + SQLite
  pending 状态,前端 review UI 后续接入)。
- ⚠️ skill 名必须全局唯一;如果用户起的名字和已有 skill 冲突,review 阶段
  会拒收。

---

## 6. 不做的事(YAGNI)

| 想法 | 不做的理由 |
| --- | --- |
| 内嵌 CNKI HTML 解析(BeautifulSoup 解析结果页) | 站点改版即失效;交给 LLM 解析更稳 |
| 实现 N 个站点的 adapter(PubMed / Scholar / arXiv) | YAGNI;扩展点已留好,按需加 |
| 自动 `ToolExecutionContext.tool_calls` 字段 | 当前 tool 调用上下文是隐式的;显式字段属于下一次重构 |
| skill 自动审核(LLM self-review 后直接 approved) | 必须人工 review;trust LLM to review itself 是 anti-pattern |
| `academic-search` skill 注册为 builtin 自动加载 | 当前靠触发词匹配,LLM 在 `find papers` 时主动调用;不强行 inject 到系统 prompt |
| Adapter 的 schema 校验(`Pydantic` 模型) | dict 注册足够;真有 N 个站点再升级 |

---

## 7. 测试覆盖

| 范围 | 文件 | 测试数 |
| --- | --- | --- |
| `CNKIAdapter` URL 构造 / `get_site_adapter` 注册 | `backend/tests/unit/test_academic_adapters.py` | 9 |
| `AcademicSearchSkill` schema / happy path / 失败模式 / 自定义 site | `backend/tests/unit/test_academic_search.py` | 8 |
| `skill_save` 端到端 pipeline(真 review + 真 SQLite + fake LLM) | `backend/tests/integration/test_skill_save_pipeline.py` | 1 |
