---
name: academic-search
description: 在文献站点(默认 CNKI)检索学术论文并整理成 Markdown 摘要列表。当用户想要找文献、检索论文、查找综述时使用。
license: Apache-2.0
compatibility: Requires Python 3.10+,需要 backend.skills.builtin.academic_adapters 模块
when_to_use: 当用户想查找学术文献、综述、期刊文章,或用"找文献""检索论文""find papers""literature search"等表达时使用
allowed-tools: web_fetch ask_user_question
triggers: []
---

# 学术检索(基础模板)

> **这是基础版 skill**,由 Sage 默认装载。
> 触发词故意留空 —— 完全靠 `when_to_use` 的语义描述让 LLM 自己判断是否激活。
> 避免占用"找文献 / 检索论文"等关键中文短语,留给用户基于此模板自定义。

---

## 触发条件

用户在聊天里表达"想找学术论文 / 综述 / 期刊文章"的需求,例如:

- "帮我找 5 篇大语言模型综述"
- "检索近三年 Transformer 论文"
- "find papers on RAG"
- "literature search about diffusion models"

---

## 步骤

1. **解析查询**
   从用户消息里提取:
   - `query`:研究主题(必填,非空字符串)
   - `limit`:篇数(默认 10,常用 5/10/20)
   - `site`:目标站点(默认 `cnki`,可选 `pubmed`/`scholar` 等;需先有对应 adapter 注册)

2. **构造检索 URL**
   ```python
   from backend.skills.builtin.academic_adapters import get_site_adapter
   adapter = get_site_adapter(site or "cnki")
   url = adapter.build_search_url(query, limit=limit or 10)
   ```

3. **抓取结果页**
   调用 `web_fetch` 工具,参数 `{"url": <上一步的 URL>}`。
   - 成功 → 拿到 HTML / Markdown 文本
   - 失败 → 返回 `{"success": false, "error": "..."}`,告知用户网络问题

4. **(可选)询问排序方式**
   如果用户没有显式指定排序,用 `ask_user_question` 让用户选:
   - 选项:`"按相关度"` / `"按时间"` / `"按引用数"`
   - 默认走"按相关度"

5. **解析并输出**
   LLM 自己解析抓取到的页面片段,按用户偏好输出 Markdown 文献列表:
   ```
   1. **标题** — 作者 — 期刊/会议 — 年份
      摘要: ...
   ```

---

## 不做的事(YAGNI)

- ❌ **不内嵌 HTML 解析**(BeautifulSoup 等):站点改版即失效,LLM 解析更稳
- ❌ **不实现 PubMed / Scholar / arXiv adapter**:扩展点已留好(`register_site_adapter`),按需加
- ❌ **不管理登录态**:adapter 只构造公开检索页 URL
- ❌ **不预设触发词**:用户从此模板派生自定义版本时,可自行加 `triggers: [找综述, ...]`

---

## 怎么变成你自己的版本

### 路径 A:直接编辑这个文件

`~/.sage/skills/academic-search/SKILL.md` 会**优先**覆盖随包分发的版本。
改 `triggers` / `when_to_use` / `步骤` 就行,不用碰代码。

### 路径 B:派生新 skill

把整个目录复制为 `~/.sage/skills/my-cnki-search/SKILL.md`,改 `name`、自己定 `triggers` 和 `when_to_use`,互不冲突。

### 路径 C:跑通一次后沉淀为草稿

让 `skill_save` 工具把"你跑通的那次工具调用序列"沉淀为新 SKILL.md 草稿,经人工 review 后即可装载。

### 路径 D:高级用户写 Python skill

继承 `backend.skills.builtin.academic_search.AcademicSearchSkill` 类,自定义 `triggers` / `execute()`,然后 `registry.register()`。
库代码仍在,只删了 builtin 自动注册。

---

## 示例对话

> **用户**: 帮我找 5 篇大语言模型综述
>
> **LLM**: (读到本 SKILL.md,看 `when_to_use` 命中,按步骤执行)
> 1. 解析 → query="大语言模型综述", limit=5
> 2. URL → `get_site_adapter("cnki").build_search_url("大语言模型综述", limit=5)`
> 3. web_fetch → 拿到结果页
> 4. ask_user_question → 用户选"按相关度"
> 5. 解析输出 → Markdown 列表(5 篇综述)