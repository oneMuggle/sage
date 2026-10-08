# 项目（Projects）功能设计评审与对标优化方案

> 日期: 2026-09-20 · 分支: `main`（工作树 `E:/ProgrammingData/electron/sage`）
> 范围: 侧边栏项目区（`ProjectSection`）、项目注册表/资料/上下文注入后端、
> 与知识库（Wiki）的关系；对标 ChatGPT Projects / Claude Projects /
> Gemini Notebooks(NotebookLM) / Cursor·Claude Code 工作区模型。
> 前置阅读: `docs/technical/61-projects-module.md`（P1–P13 落地记录）、
> `docs/technical/58-project-context-aggregation.md`（M3 资料与注入）、
> `docs/user-manual/16-project-context.md`（用户视角）。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 项目功能是怎么设计的 | **目录优先（folder-first）**：项目 = 用户显式登记的本地工作目录（对标 Cursor Recent Workspaces / Claude Code），会话归属复用 `session_workspace_bindings`，再叠加 description / instructions / materials / allowed_paths 四类项目级元数据，在 chat 主链路注入 system prompt。 |
| 是否像主流 AI 应用一样放在会话区 | **是，但只是“放进去了”**：项目是左侧栏的一个可折叠分组（默认排在 会话 → 定时任务 → 项目 → 团队 第三位，`maxHeight=30vh`），项目行内嵌 会话子列表 + 概览编辑 + 资料管理 + allowed_paths 编辑器。没有项目主页，会话列表本身对项目零感知（扁平、无归属标记、不可“移动到项目”），新建会话（Welcome）不能选项目，Chat 内只有只读徽标。与 ChatGPT/Claude 的“项目是一级容器、有落地页”的模式差距明显。 |
| 有没有项目 Wiki 类功能 | **有两套互不贯通的东西**：(a) 全局知识库页 `/knowledge`（LLM Wiki：ingest / 图谱 / lint / review / 独立 WikiChat），其“wiki 项目”= 含 `wiki/` 子目录的文件夹；(b) 侧边栏项目的“资料（materials）”——纯文本片段直接存 SQLite 注入 prompt。P6/P8 只把两者的**注册表/授权**合并了（recents 成为 projects 表的投影），**知识本体没有合并**：资料不进 wiki 索引、`@wiki:` 检索的是“最近打开的 wiki 项目”而非当前会话的项目、Chat 与 WikiChat 是两个聊天入口。 |
| 最严重的问题 | **资料功能实际上是“死”的（P0）**：`ProjectMaterialRepository.add()` 固定写入 `status='pending_index'`，`mark_ready()` 在生产代码中**没有任何调用方**（仅测试调用），而注入只取 `status='ready'`。用户添加的资料永远显示“待索引/Processing”，也永远不会进入模型上下文。用户手册“等待几秒后自动转已索引”的描述与实现不符。 |
| 优化方向 | 把“项目”从“目录的快捷方式”升级为**一级工作容器**：项目主页 + 会话归属可视化 + 新建会话即选项目 + 目录可选（虚拟项目）+ 资料/文件统一进项目 Wiki 并按需检索 + 项目级记忆隔离 + 项目级设置（模型/技能/MCP/allowed_paths）。分四个阶段推进，第一阶段先修 P0 并补齐信息架构。 |

---

## 1. 现状：项目功能是如何设计的

### 1.1 概念模型

```
用户显式登记的目录  ──►  projects 行（id, path UNIQUE, name=basename）
                              │
        ┌─────────────────────┼──────────────────────────────┐
        ▼                     ▼                              ▼
  description /         project_materials             allowed_paths(JSON)
  instructions          (文本片段, 三态 status)        (额外只读路径规则)
        │                     │
        └────────┬────────────┘
                 ▼
   chat 主链路 system prompt 注入（legacy_routes.py M3/M6 标记块）
                 ▲
                 │  归属判定：session_workspace_bindings 活跃行
                 │  (workspace_path == projects.path)
              sessions
```

关键设计决策（均可在源码注释中找到依据）：

| 决策 | 位置 | 含义 |
| --- | --- | --- |
| 项目 = 目录，`path` UNIQUE | `backend/data/project_repo.py`、`backend/api/project_routes.py` 模块注释 | 明确对标 Cursor Recent Workspaces / Claude Code；没有目录就没有项目 |
| 会话归属**不新增数据**，复用 workspace 绑定 | `docs/technical/61-projects-module.md` §2.2 | 好处：fork 继承、变更面板、检查点、SAGE.md 发现全部自动生效；代价：项目与目录强耦合，一个会话只能属于一个目录，目录消失即 410 |
| 打开项目 = 复用最近会话或新建 | `POST /projects/{id}/open` | 单次 IPC 往返切项目 |
| 元数据/资料**不**自动读目录、资料视为不可信 | `docs/technical/58-project-context-aggregation.md` §1 | 安全立场正确，但也意味着“项目知识”必须靠手工粘贴 |
| 注入预算：单字段/单条 8 KB，累计 16 KB；资料超预算整条排除 | `backend/chat/project_context.py` | 全量注入、无检索；资料上限 64 KB/条 |

### 1.2 数据模型（SQLite，`backend/data/database.py init_db`）

```sql
projects(id PK, path UNIQUE, name, created_at, last_opened_at,
         intent NULL,            -- P8: wiki recents 投影用 (create/open)
         description NULL,       -- ≤ 4 KB
         instructions NULL,      -- ≤ 16 KB
         allowed_paths NULL)     -- JSON 数组, ≤ 50 条 gitignore 风格规则

project_materials(id PK, project_id FK CASCADE, source_message_id NULL,
         content_hash, content(≤64 KB), status('pending_index'|'ready'|'failed'),
         wiki_page_path NULL, error_message NULL, created_at)
UNIQUE(project_id, content_hash)

session_workspace_bindings(session_id, workspace_path, generation, revoked_at ...)
```

实测（本机两份库均为空库：`%APPDATA%/Sage/sage.db` 无 projects 表，
`data/sage.db` 0 项目 0 会话），因此本文所有结论基于源码而非运行数据。

### 1.3 后端 API 面（`backend/api/project_routes.py`）

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| GET | `/api/v1/projects` | 清单（`last_opened_at DESC`，≤50，附 session_count / last_session_id 聚合） |
| POST | `/api/v1/projects` | 登记目录（`validate_workspace`，幂等；可带 allowed_paths） |
| PATCH | `/api/v1/projects/{id}` | description / instructions（`model_fields_set` 局部更新） |
| PUT | `/api/v1/projects/{id}/allowed-paths` | 额外只读路径规则 |
| DELETE | `/api/v1/projects/{id}` | 移除注册行（不动磁盘与会话） |
| POST | `/api/v1/projects/{id}/open` | 复用最近会话或新建并绑定；目录缺失 410 |
| GET | `/api/v1/projects/{id}/sessions` | 项目下未归档会话（≤20） |
| GET/POST | `/api/v1/projects/{id}/materials` | 资料列表 / 粘贴文本添加（413 超限） |
| DELETE | `/api/v1/projects/{id}/materials/{mid}` | 硬删除 |
| POST | `/api/v1/projects/{id}/materials/save-answer` | 把 assistant 消息存为资料（校验 role 与会话归属） |

缺失的端点：项目重命名、项目归档/恢复、把会话移入/移出项目、资料重试索引、
资料编辑、文件上传、项目级设置（模型/技能/MCP）。

### 1.4 上下文注入链路（`backend/api/legacy_routes.py` 2762–2824 行）

```
[system 头 / 安全规则]
  + M3  项目概览 (description + instructions)      ← 仅当会话有活跃 workspace 绑定且该路径已登记为项目
  + M6  SAGE.md / CLAUDE.md / AGENTS.md 向上发现    ← 仅依赖绑定目录，不要求登记为项目
  + L5  环境块 / 技能清单（尾部 dynamic system）
  + M3  项目资料 (status='ready')                   ← 见 §2.1：永远为空
```

要点：

- 归属判定链是 `session_id → binding.workspace_path → projects.path`，因此
  **绑定了目录但未登记为项目**的会话（Office 页 `WorkspaceBindModal` 绑定的）
  只享受 SAGE.md 发现，不享受 description / instructions。
- `~/.sage/SAGE.md` 用户级规则 → 项目级文件 → 项目 instructions，三层都是
  “文件/字段全量注入”，没有检索。

### 1.5 前端：项目放在哪里、长什么样

`src/widgets/layout/Sidebar.tsx`：

```
┌ 240px 侧栏 ──────────────────────────────┐
│ Logo                                     │
│ 对话 · 记忆 · 知识库 · 设置   (一级导航)  │
│ ▸ 更多 (Office/技能/智能体/编排/Arena/帮助)│
│ ▾ 会话  [搜索][+]        maxHeight 50vh  │
│    · 会话A  · 会话B … (扁平, 置顶优先)     │
│ ▾ 定时任务                               │
│ ▾ 项目  [+]              maxHeight 30vh  │  ← ProjectSection
│    ▸ 📁 sage   E:/…/sage        3        │
│      ├ 子会话 1 / 子会话 2 (展开后)        │
│      ├ [项目概览] description ▭ instr ▭   │
│      ├ [额外允许访问] 规则编辑器           │
│      └ [项目资料] 列表 + textarea + 保存回答│
│ ▾ 团队 (占位)                            │
│ 连接状态 · 版本                           │
└──────────────────────────────────────────┘
Chat 头部: [📁 sage] 只读徽标 (ProjectBadge)
```

交互清单：标题行 `+` 选目录 → 登记 → 直接打开；行点击 open；hover `+` 项目内新
建会话、两步移除；chevron 展开懒加载会话子列表；拖文件夹到分组登记；命令面板
“项目”分组 + `add-project`；全局搜索按项目分组（P7）。

### 1.6 与知识库（Wiki）的关系

| 维度 | 侧边栏“项目” | 知识库页“wiki 项目” |
| --- | --- | --- |
| 定义 | 任意已登记目录 | 含 `wiki/` 子目录的文件夹（`WikiProjectPicker` 创建/打开） |
| 存储 | `projects` 表 | P8 起 `recent_projects` 是 `projects` 表的只读投影（intent 列） |
| 授权 | — | `wiki/project_authorization.authorize_registered_project`（P6 起接受 projects 注册表并集） |
| 知识本体 | `project_materials` 文本片段（SQLite） | `wiki/sources/*.md` + 向量索引 + 图谱 |
| 聊天入口 | 主 Chat（system prompt 注入） | `WikiChat`（独立流式对话，RAG） |
| 跨入口引用 | — | 主 Chat 中 `@wiki:query`，但根目录取 `load_recent()[0]`（最近打开的 wiki 项目），与当前会话所属项目无关 |
| 桥接 | `project_materials.wiki_page_path` 字段已预留，`docs/technical/58` §2 提到 ingest，但**无实现** | — |

即：项目与 Wiki 在“注册表”层面统一了，在“知识”层面仍是双轨。

### 1.7 演进时间线（便于理解为什么长成现在这样）

`d66d6af4` 占位分组 → P1 `#727` 注册表 → P2 `#734` 子列表/命令面板 → P3
徽标 → P4 `#743` → P5 `#772` 拖拽 → P6 `#775` wiki 授权桥接 → P7 `#810` 搜索
分组 → M3 `#857` description/instructions/materials → P8/P9/P13 recents 迁移与
知识范围 → P22/`#1120` allowed_paths。每一批都刻意“最小加法、零后端改动优先”，
结果是功能在侧栏里**纵向堆叠**，而信息架构从未重排。

---

## 2. 问题诊断

### 2.1 P0 缺陷：项目资料永远不会被注入

证据链：

1. `backend/data/project_material_repo.py` `add()`：
   `INSERT ... VALUES (?, ?, ?, ?, ?, 'pending_index', NULL, NULL, ?)`；
2. 全仓 `mark_ready(` 的生产调用方为 0（仅 `backend/tests/unit/test_project_material_repo.py`
   与 `backend/tests/integration/test_project_overview_injection.py` 手工调用后再断言注入）；
3. `get_active_materials_for_project()` 只查 `status = 'ready'`；
4. `legacy_routes.py` 2811–2819 只注入上一步结果。

后果：UI 永远显示“待索引”，“保存当前回答”看似成功实则无效；集成测试因为
自己调用了 `mark_ready` 而全绿，掩盖了缺口。文档 `docs/user-manual/16-project-context.md`
“等待几秒后自动转已索引”与实现矛盾。

### 2.2 信息架构：项目被塞进 30vh 的侧栏分组

- 概览编辑（两个 textarea）、allowed_paths 编辑器、资料列表 + 新增 textarea
  全部内嵌在 240px 宽、最高 30vh 的滚动区里，字号 10–11px；这是“设置页”级别
  的内容量，却没有页面级承载。
- 没有项目主页（landing）：ChatGPT / Claude 点开项目看到的是“项目名 + 说明 +
  新对话输入框 + 该项目的对话列表 + 知识/文件面板 + 指令入口”，Sage 点开项目
  直接跳到最近一条会话。
- 项目区默认排在会话与定时任务之后，首屏常常看不见；`sider.project.empty`
  文案是唯一的引导。

### 2.3 会话区与项目区脱节

- `ConversationsSection` 是全量扁平列表（置顶/搜索/归档），`SessionItem` 中没有
  任何 project / workspace 字段，看不出一条会话属于哪个项目。
- Welcome 页 `createSession()` 不接受项目参数，新会话天然“无项目”；要让会话属于
  项目只能从项目行的 `+` 进入。
- Chat 页只有只读 `ProjectBadge`；`ChatInput.tsx` 注释称 “Chat.tsx renders the
  WorkspaceBindModal entry point”，但 `Chat.tsx` 中并无该组件——绑定入口实际
  只在 Office 页。会话无法在 Chat 内“加入项目 / 切换项目 / 移出项目”。
- 一条会话同时出现在“会话”列表和“项目 › 子列表”两处，两处的操作集合不同
  （子列表只有删除，没有置顶/重命名/归档）。

### 2.4 “项目 = 目录”的强耦合

- 写作/研究类用户（README 定位是“Office 写作代理”）常常没有代码目录，却需要
  “某个课题 / 某个客户”的项目容器；现在必须先在磁盘上造一个文件夹。
- 目录移动/删除 → 410，项目下所有会话、instructions、materials 一并失联
  （数据仍在库里，但无法通过 UI 触达）。
- 同一目录只能是一个项目；同一目录下想按课题分多个项目做不到。

### 2.5 知识双轨：资料 ≠ Wiki，Chat ≠ WikiChat

- 资料只能粘贴纯文本（≤64 KB），不能上传 PDF/DOCX/图片，尽管 `backend/wiki/file_parser.py`
  / `vision_ingest.py` 已具备解析能力。
- 资料注入是“全量拼接 + 超预算整条剔除”，没有检索；预算 16 KB 决定了资料库
  实际只能放 2–3 条长文。对比 Claude Projects 在知识接近上下文上限时自动切换
  RAG（容量约 10×）[1](https://prompt-architects.com/blog/390-claude-projects-prompting-with-project-knowledge)。
- `@wiki:` 检索根为“最近打开的 wiki 项目”，用户在项目 A 的会话中 `@wiki:` 可能
  检索到项目 B 的知识库。
- Knowledge 页有自己的 `WikiChat`，和主 Chat 是两套流式实现、两套历史、两套
  上下文策略；用户需要在两个聊天入口之间切换。

### 2.6 记忆不按项目隔离

`backend/memory/` 中没有任何 project / workspace 维度（grep 为 0）。ChatGPT
Projects 提供 default / project-only memory 两档，共享项目强制 project-only
[2](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)；Claude
Projects 也有项目级 memory。Sage 的“记忆优先”哲学下，跨项目串味（客户 A 的
偏好影响客户 B）是可预见的投诉点。

### 2.7 其它缺口（对标清单）

| 能力 | ChatGPT Projects | Claude Projects | Sage 现状 |
| --- | --- | --- | --- |
| 项目落地页 | 有 | 有 | 无 |
| 会话 ↔ 项目移动 | 右键“移动到项目” | 拖拽/菜单 | 无 |
| 项目图标/颜色 | 有 | — | 无 |
| 项目重命名 | 有 | 有 | 无（name = basename） |
| 项目归档/删除含会话 | 有 | 有 | 只能移除注册行 |
| 文件上传 | 5/25/40 个 | 无公开上限，超阈值自动 RAG | 仅粘贴文本 |
| 项目指令优先级高于全局 | 是 | 是 | 是（已实现，优点） |
| 项目级记忆 | 有 | 有 | 无 |
| 项目级模型/工具选择 | 部分 | — | 无（但 Sage 有多端点/技能/MCP，天然适合做） |
| 本地目录感知 / 代码工具 | 无 | 无（Claude Code 另算） | **有**（差异化优势） |
| 共享/协作 | 有 | 有 | 单机产品，不适用 |

---

## 3. 主流产品的设计要点（可借鉴的模式）

1. **项目是一级容器，不是文件夹**：ChatGPT 官方与社区反复强调 Projects “bundles
   chats + files + instructions，且会改变模型的回答方式”，一级深度、无嵌套，
   一个会话同一时间只属于一个项目
   [3](https://medium.com/@adi_leviim/chatgpt-projects-are-not-folders-here-is-what-they-actually-do-2026-a6695580bf1c)。
2. **三段式项目知识**：Claude 把上下文分成 项目指令（standing rules）、项目知识
   （文件/文本，加载或检索）、项目记忆（从对话自动生成）三层，各有独立入口
   [1](https://prompt-architects.com/blog/390-claude-projects-prompting-with-project-knowledge)。
3. **知识规模自适应**：小于阈值全量加载，接近上下文上限自动切换检索模式并给出
   指示器，无需用户配置
   [4](https://gptprompts.ai/how-to-use-claude-to/use-project-knowledge)。
4. **记忆作用域是项目属性**：ChatGPT 在创建项目时选择 default / project-only，
   切换后“项目内信息从项目外记忆中移除”
   [2](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)。
5. **文档中心 vs 对话中心分工**：Gemini Notebooks（对话中心、可设指令）与
   NotebookLM（文档中心、来源即权威）通过同步互补，而不是做成两个平级的聊天
   [5](https://www.mindstudio.ai/blog/gemini-notebooks-vs-claude-projects-chatgpt-memory)。
   对 Sage 的启示：Knowledge 页应是“来源/索引管理”，对话统一回到主 Chat。
6. **目录型项目的长处**：Cursor / Claude Code 的“项目 = 仓库”给了工具链上下文
   （文件、git、LSP、SAGE.md）。Sage 已有这一半，缺的是 ChatGPT/Claude 那一半。

---

## 4. 优化方案

### 4.1 目标定位

> **Sage 项目 = 一级工作容器**：`{ 名称/图标, 可选工作目录, 项目指令, 项目知识
> (Wiki), 项目记忆作用域, 项目内会话, 项目级设置 }`。目录是项目的一个属性，
> 而不是项目的身份。

设计原则沿用 `PHILOSOPHY.md`：可逆（软删除/归档）、透明（注入了什么可查看）、
简单（先用现有 wiki 管线，不新造索引）。

### 4.2 阶段 0（P0 修复，1–2 天）：让资料真正生效

> **状态：已实施（2026-09-20，方案 A）**，详见 §6 实施记录。

两种方案，建议先做 A、再在阶段 2 升级为 B：

- **A. 同步就绪**：`ProjectMaterialRepository.add()` 直接写 `status='ready'`
  （或 `add()` 后立即 `mark_ready()`），把 `pending_index` 保留给未来的异步索引；
  `save-answer` 同路径。补一条集成测试：**不**手工调用 `mark_ready`，走
  `POST /materials` 后断言 system prompt 含 `MATERIALS_HEADER`。
- **B. 接入 wiki ingest**：add 后投递到 `backend/wiki/ingest_queue`，完成回调
  `mark_ready(id, wiki_page_path)` / 失败 `mark_failed()`；前端增加“重试索引”
  按钮（`error_message` 已有字段）。B 依赖 §4.5 的“项目知识根目录”决策。

同步修正 `docs/user-manual/16-project-context.md` 的状态说明。

### 4.3 阶段 1（信息架构，1–2 周）：项目主页与会话归属可视化

1. **项目主页路由** `/projects/:id`（新页 `src/pages/Project.tsx`）：
   头部（图标 + 名称可改 + 目录 chip 可绑定/更换/解绑）；中部新对话输入框
   （复用 `WelcomeInputCard`，提交即 `projects_create_session` + pendingMessage）；
   下方该项目会话列表（复用 `SessionItem`，获得置顶/重命名/归档全套操作）；
   右侧 Tab：指令 / 知识 / 设置。侧栏 `ProjectSection` 退化为“项目列表 +
   `+`”，点击进入主页；把概览、allowed_paths、资料三个面板整体迁到主页。
2. **会话列表项目感知**：`GET /sessions` 响应附 `project_id`（后端 JOIN
   `session_workspace_bindings` + `projects`，零新表）；`SessionItem` 显示项目
   色点/短名；`ConversationsSection` 增加“按项目分组 / 平铺”切换与项目筛选。
3. **移动到项目**：`SessionItem` 右键/更多菜单新增“移动到项目…”“移出项目”，
   后端复用 `bind_session_workspace` / `revoke_session_workspace`（generation
   递增已支持重绑）；移动时 toast 提示“该会话将开始应用项目指令与知识”
   （对标 ChatGPT 的行为变化提示）。
4. **新建会话即选项目**：Welcome 页输入框上方增加项目选择器（默认“无项目”，
   记住上次选择）；Chat 头部 `ProjectBadge` 改为可点击的项目切换器
   （无项目时显示“加入项目”）。
5. **侧栏顺序**：默认 `['project', 'conversations', 'cron', 'team']` 或把
   项目列表提升到一级导航“项目”下（沿用 `useSiderSections` 的持久化，老用户
   的自定义顺序不受影响）。

### 4.4 阶段 2（数据模型解耦，1 周）：目录可选的项目

- `projects.path` 允许 NULL，新增 `title`（可改名，name 继续作 basename 回退）、
  `icon`、`color`、`archived_at`、`memory_scope('default'|'project')`。
- 会话归属改为显式列 `sessions.project_id`（可空，`ON DELETE SET NULL`），
  workspace 绑定退回为“项目的目录属性 → 会话打开时自动绑定”。迁移脚本：按
  `binding.workspace_path == projects.path` 回填 `project_id`；`session_stats()`
  改查该列。这样目录消失只影响文件工具，不再让项目失联（410 改为主页内的
  “目录不存在，重新选择/解绑”提示）。
- 项目删除 = 软删除（`archived_at`）+ 会话保留/一并归档二选一，符合“不可逆
  操作必须可回滚”。

### 4.5 阶段 3（项目知识 = 项目 Wiki，2–3 周）

目标：资料、文件、Wiki 三合一，检索式注入，主 Chat 统一入口。

1. **知识根目录**：有目录的项目默认 `<project>/.sage/wiki/`（可改为
   `<project>/wiki/` 以兼容现有 wiki 项目）；无目录项目用
   `${SAGE_USER_DATA_DIR}/projects/<id>/wiki/`。`authorize_registered_project`
   把这两类根纳入白名单。
2. **资料升级为知识条目**：粘贴文本 / 保存回答 / 上传文件（拖拽到主页“知识”
   Tab，复用 `wiki/file_parser.py`、`vision_ingest.py`）统一走 `wiki/ingest`，
   `project_materials` 保留为“来源登记 + 状态”表，`wiki_page_path` 落地。
3. **注入策略自适应**：知识总量 ≤ 预算（建议把 16 KB 提到模型上下文的一个比例，
   由 `model_catalog/context.py` 给出）时全量注入；超出时改为
   `search_wiki(project_root, 用户消息)` Top-K 检索注入，并在 UI 显示“检索模式”
   指示器（对标 Claude 的自动 RAG）。
4. **`@wiki:` 与知识范围跟随项目**：`entity_refs._wiki_project_root()` 优先取
   当前会话项目的知识根，其次才是 recents[0]；P9/P13 的 `knowledge_project`
   默认值同样跟随当前项目。
5. **WikiChat 收敛**：Knowledge 页保留 ingest / 图谱 / lint / review / 来源管理，
   “对话”视图改为跳转主 Chat 并预选该项目（或以只读方式嵌入主 Chat 组件），
   消除双聊天入口。
6. **透明度**：主 Chat 消息底部显示“本轮注入：项目指令 ✓ · 知识 3 条（检索）·
   SAGE.md ✓”，点击可展开预览（对齐 PHILOSOPHY “用户知道什么被注入”）。

### 4.6 阶段 4（项目级记忆与设置，1–2 周）

- 记忆条目增加 `project_id`（episodic / semantic / user_profile 三层的写入侧带
  上当前会话项目；检索侧按 `memory_scope` 过滤：`project` 只召回本项目 + 用户
  画像，`default` 全量）。记忆页增加项目筛选。
- 项目设置 Tab：默认模型端点、启用的技能子集、MCP 服务器子集、allowed_paths、
  记忆作用域、临时聊天默认值。后端在 chat 主链路读取项目设置覆盖全局（优先级
  与 instructions 一致：项目 > 全局）。
- 导出/导入项目（JSON + wiki 目录），满足“数据不锁定”。

### 4.7 路线图与风险

| 阶段 | 内容 | 预估 | 主要风险 |
| --- | --- | --- | --- |
| 0 | 资料 ready 修复 + 测试 + 文档（**已完成**，§6） | 1–2 天 | 无；纯缺陷修复 |
| 1 | 项目主页、会话归属可视化、移动到项目、Welcome/Chat 选项目 | 1–2 周 | `Chat.tsx`（1160 行）与 win7 分支分歧大，新增独立组件、Chat 只插入一行 |
| 2 | path 可空、`sessions.project_id`、软删除、重命名/图标 | 1 周 | 迁移需幂等（沿用 `init_db` try/except ALTER 惯例）；`session_stats()` / P7 搜索分组 / wiki recents 投影三处消费方要同步 |
| 3 | 知识统一进 wiki + 自适应检索 + `@wiki:` 跟随项目 + WikiChat 收敛 | 2–3 周 | 嵌入/向量依赖（ChromaDB / embedder）缺失时需降级为全量注入；无目录项目的知识根放用户数据目录 |
| 4 | 项目级记忆作用域与项目设置 | 1–2 周 | 记忆表加列 + 检索过滤，注意“切到 project-only 后旧记忆如何处理”需要明确交互 |

阶段 1 与 2 可并行（1 先用现有 binding 判定，2 落地后切换到 `project_id`）。
win7 LTS 分支按“仅 hotfix”原则只回流阶段 0。

### 4.8 验收标准（节选）

- 添加资料后，在同项目新会话首条消息的 system prompt 中能看到 `MATERIALS_HEADER`
  块（集成测试不得手工 `mark_ready`）。
- 从 Welcome 选项目 → 发送 → 会话出现在项目主页列表且 `ProjectBadge` 正确。
- 会话列表任一条目可移动到项目/移出项目，操作后 `session_count` 聚合正确。
- 目录被移走后项目仍可打开主页、查看会话与知识，仅目录 chip 标红。
- 项目知识 > 预算时自动进入检索模式，UI 有指示；`@wiki:` 在项目 A 的会话里
  不会命中项目 B。
- `memory_scope='project'` 的项目内，记忆检索不返回其他项目的情景记忆。

---

## 5. 附录

### 5.1 本次评审涉及的源码

- 后端：`backend/api/project_routes.py`、`backend/data/project_repo.py`、
  `backend/data/project_material_repo.py`、`backend/chat/project_context.py`、
  `backend/api/legacy_routes.py`（2762–2824）、`backend/office/session_workspace.py`、
  `backend/storage/recent_projects.py`、`backend/wiki/project_authorization.py`、
  `backend/chat/entity_refs.py`、`backend/data/database.py`
- 前端：`src/widgets/layout/Sidebar.tsx`、`src/widgets/sidebar/useSiderSections.ts`、
  `src/widgets/sidebar/sections/ProjectSection.tsx`、
  `src/widgets/sidebar/sections/ConversationsSection.tsx`、`src/widgets/session/SessionItem.tsx`、
  `src/widgets/chat/ProjectBadge.tsx`、`src/shared/api/projectApi.ts`、`src/pages/Chat.tsx`、
  `src/pages/Welcome.tsx`、`src/pages/Knowledge.tsx`、`src/entities/wiki/store.ts`、
  `src/features/workspace/WorkspaceBindModal.tsx`、`src/app/providers/SessionWorkspaceProvider.tsx`
- 文档：`docs/technical/61-projects-module.md`、`docs/technical/58-project-context-aggregation.md`、
  `docs/user-manual/16-project-context.md`、`docs/plans/2026-09-13_projects-p2-plan.md` 等

### 5.2 复现 P0 的最小命令

```bash
# 生产代码中 mark_ready 的调用方
grep -rn "mark_ready(" backend --include=*.py | grep -v tests | grep -v orchestration
# 期望: 只剩 backend/data/project_material_repo.py 的定义行
```

### 5.3 外部参考

1. Claude Projects: Prompting with Project Knowledge（2026-09）
   https://prompt-architects.com/blog/390-claude-projects-prompting-with-project-knowledge
2. OpenAI Help: Projects in ChatGPT（memory 设置）
   https://help.openai.com/en/articles/10169521-projects-in-chatgpt
3. ChatGPT Projects Are Not Folders（2026-09）
   https://medium.com/@adi_leviim/chatgpt-projects-are-not-folders-here-is-what-they-actually-do-2026-a6695580bf1c
4. How to Use Claude Project Knowledge（2026-07）
   https://gptprompts.ai/how-to-use-claude-to/use-project-knowledge
5. Gemini Notebooks vs Claude Projects vs ChatGPT（2026-04）
   https://www.mindstudio.ai/blog/gemini-notebooks-vs-claude-projects-chatgpt-memory

---

## 6. 实施记录

### 6.1 阶段 0：资料添加后直接 `ready`（2026-09-20，已完成）

**工作树与分支**（按 `docs/technical/47-git-worktree-workflow.md` 的成对惯例，
`scripts/worktree.sh new` 创建，端口自动分配）：

| 目标分支 | 工作分支 | 工作树 | 基线 |
| --- | --- | --- | --- |
| `main` | `fix/project-materials-ready-main` | `.worktrees/fix-project-materials-ready-main` | `origin/main` @ `0c7c28b9` |
| `release/win7` | `fix/project-materials-ready-win7` | `.worktrees/fix-project-materials-ready-win7` | `origin/release/win7` @ `7e1eebc5` |

对齐策略：改动先在 main 工作树完成并提交，再 `git cherry-pick` 到 win7 工作树。
事前 `git diff --stat origin/main origin/release/win7 -- <改动文件>` 确认：
`project_material_repo.py`、三个测试文件、两份文档、`projectApi.ts` 在两分支
逐字节一致；`database.py` 两分支的差异全部位于记忆表区域，`project_materials`
DDL 块相同，因此 cherry-pick 无冲突。改动不含 py3.9+ 语法（保留
`from __future__ import annotations`、`typing.Optional/List`，无 walrus /
`match` / `X | None`），满足 win7 的 Python 3.8 约束。两分支分别独立发 PR，
不做 win7↔main 的分支合并。

**代码改动**（方案 A，同步就绪；保留异步扩展点）：

- `backend/data/project_material_repo.py`
  - 新增常量 `MATERIAL_STATUS_{PENDING,READY,FAILED}`、`VALID_MATERIAL_STATUSES`、
    `DEFAULT_MATERIAL_STATUS = "ready"`（导出到 `__all__`）
  - `add(..., *, status=DEFAULT_MATERIAL_STATUS)`：校验 status（非法抛
    `ValueError`），INSERT 写入请求的 status 而非硬编码 `'pending_index'`
  - 去重命中 `failed` 行 → 按本次 status 复活并清空 `error_message`
    （"再添加一次"即重试）；`pending_index` 行保持不动
  - 回读逻辑抽为 `_get_or_raise()`；`mark_ready` / `mark_failed` /
    `get_active_materials_for_project` 不变
- `backend/data/database.py`：`project_materials` DDL 之后追加幂等回填
  `UPDATE project_materials SET status='ready' WHERE status='pending_index'`，
  修正升级前已卡在 `pending_index` 的存量资料（注释标明：将来接入异步索引时
  必须移除或按版本门控）
- `src/shared/api/projectApi.ts`：仅注释修正（`addMaterial` 返回 `ready`、
  `wikiPagePath` 当前恒为 null），无行为变化；前端徽章文案（就绪/处理中/失败）
  与 `ProjectSection.test.tsx` 无需改动
- 路由/注入层（`project_routes.py`、`project_context.py`、`legacy_routes.py`）未动

**测试**（主机 Python 3.12.10 + pytest 9.0.3，`41 passed`）：

- `backend/tests/unit/test_project_material_repo.py`（19 个）：新增默认 ready、
  显式 pending、非法 status、failed 复活、pending 不被覆盖 5 个用例；
  GetActive/Status 用例改用 `status="pending_index"` 构造排除项
- `backend/tests/api/test_project_routes_m3.py`（17 个）：add / save-answer
  断言 `status == "ready"`
- `backend/tests/integration/test_project_overview_injection.py`（5 个）：删除
  手动 `mark_ready`；新增 `test_material_added_via_api_is_injected_without_manual_ready`
  （REST 添加 → `/chat/stream` → system prompt 含 `MATERIALS_HEADER` 与资料标记），
  即 §4.8 第一条验收标准

**文档**：`docs/user-manual/16-project-context.md`（状态表改为 就绪/处理中/失败，
补"生效时机"与"旧资料一直处理中"FAQ）、
`docs/technical/58-project-context-aggregation.md`（§3.2 状态语义、§4 表、
新增 §11 P0 修复记录、测试计数）。

**未纳入本阶段**（记入阶段 1 backlog）：

- 前端 `ProjectSection.tsx` 本地长度阈值 `MATERIAL_TEXT_MAX = 1_000_000` 与后端
  `MAX_MATERIAL_CONTENT_CHARS = 64_000` 不一致（超限文本要到后端才被 413 拒绝，
  提示文案本身已写 64KB）；改动需同步 `ProjectSection.test.tsx` 第 604 行的
  `'x'.repeat(1_000_001)`，留待阶段 1 一并处理
- `origin/main` 最新提交（#1338，记忆 scope 轴 P1–P4：作用域 / 项目画像 /
  冲突消解 / 反思评分）已开始落地"项目级记忆"，与 §4.6 阶段 4 重叠，阶段 4
  启动前需先对齐该实现，避免重复建设
