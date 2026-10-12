# AI 增强项目管理子系统实施方案

> **状态**: Draft  
> **创建**: 2026-10-12  
> **分支**: `feat/ai-project-enhancements`  
> **前置分析**: 已完成竞品调研（Cursor Projects / Fenix / Bito / Jooj / CodeWiki / Deepforge / Windsurf）

---

## 1. 背景与目标

### 1.1 现状

Sage 的项目子系统已具备完整的 CRUD 基础：项目注册、类型检测、会话绑定、5层上下文注入、材料管理、约束系统、里程碑追踪、项目 Profile、内置 VCS、Wiki 桥接。

**核心缺口**：所有功能依赖用户手动操作，AI 仅作为被动响应者。竞品（Cursor Projects、Fenix、Bito、Jooj）已将 AI 作为项目管理的"主动参与者"。

### 1.2 目标

1. **AI 主动参与项目管理** — 智能任务分解、进度分析、风险预警
2. **AI 生成项目知识** — 对话知识沉淀、代码→Wiki 自动生成
3. **补全架构预留** — 激活 `pending_index` 语义索引管线

### 1.3 非目标（v1 不做的）

- 实时多人协作/共享项目
- 事件驱动自动化（Slack/PR 订阅）
- 跨项目知识关联
- Coordinator Agent 模式（需云端基础设施）

---

## 2. 功能模块拆分

### Phase 1（P0，优先实施，2-3 Sprint）

| 模块 | 描述 | 复用现有设施 |
|------|------|-------------|
| **M1: 智能任务分解** | LLM 将自然语言需求拆解为 milestone 树 | `project_milestones` 表 + `MilestoneManager` |
| **M2: 对话知识沉淀** | 会话结束时 AI 提取值得保存的知识点 | `project_profile` 表 + `ProjectProfileStore` |
| **M3: 项目进度顾问** | AI 分析项目健康度并给出建议 | `project_diagnose` + `git-status` + `milestone_repo` |

### Phase 2（P1，后续实施，3-4 Sprint）

| 模块 | 描述 | 复用现有设施 |
|------|------|-------------|
| **M4: 语义索引管线** | 材料添加时异步 embedding + 语义检索 | `pending_index` 状态 + `wiki_page_path` 字段 |
| **M5: 代码→Wiki 生成** | 扫描代码库生成结构化文档写入 Wiki | Wiki `pages` 表 + `allowed_paths` 文件访问 |

---

## 3. 涉及的文件与模块

### 3.1 后端新增文件

```
backend/services/
  project_task_decomposer.py     # M1: 任务分解引擎
  project_knowledge_extractor.py # M2: 对话知识提取器
  project_advisor.py             # M3: 项目进度顾问
  project_semantic_indexer.py    # M4: 语义索引服务（Phase 2）
  project_wiki_generator.py      # M5: 代码→Wiki 生成器（Phase 2）

backend/api/
  project_ai_routes.py           # AI 功能 API 路由（统一入口）

backend/tools/
  decompose_tasks_tool.py        # LLM 可调用的任务分解工具
  extract_knowledge_tool.py      # LLM 可调用的知识提取工具
  project_advise_tool.py         # LLM 可调用的项目顾问工具
```

### 3.2 后端修改文件

```
backend/api/project_routes.py    # 挂载新路由
backend/main.py                  # 注册新 router
backend/data/project_milestone_repo.py  # 增加批量创建方法
backend/data/project_profile.py         # 增加语义去重方法
backend/chat/project_context.py         # 集成顾问建议到上下文
```

### 3.3 前端新增文件

```
src/features/project-ai/
  TaskDecomposeDialog.tsx         # M1: 任务分解对话框
  KnowledgeExtractionPanel.tsx    # M2: 知识沉淀面板
  ProjectAdvisorCard.tsx          # M3: 项目顾问卡片
  AiProjectActions.tsx            # AI 操作统一入口组件
```

### 3.4 前端修改文件

```
src/shared/api/projectApi.ts              # 新增 AI 相关 API 调用
src/shared/api/projectApiTypes.ts         # 新增类型定义
src/features/project-type/ProjectArchetypeStudio.tsx  # 增加 AI Tab
src/features/project-type/MilestoneManager.tsx         # 增加"AI 分解"按钮
src/widgets/sidebar/sections/ProjectExpandedPanels.tsx # 增加顾问入口
```

---

## 4. 技术方案

### 4.1 M1: 智能任务分解引擎

#### 数据流

```
用户输入自然语言需求（如"添加用户认证"）
         │
         ▼
POST /api/v1/projects/{id}/ai/decompose-tasks
  body: { requirement: "...", context?: "..." }
         │
         ▼
ProjectTaskDecomposer.decompose(
  project: Project,
  requirement: str,
  existing_milestones: List[ProjectMilestone]
)
         │
         ▼
构建 prompt:
  - system: "你是项目管理助手，根据项目类型和当前阶段分解任务"
  - context:
    - project_type (coding/research/business/personal)
    - project_stage (planning/development/...)
    - project_description
    - existing_milestones (避免重复)
    - active_constraints (编码风格/安全要求等)
  - user: requirement
         │
         ▼
LLM 输出结构化 JSON:
{
  "milestones": [
    {
      "title": "JWT 认证模块",
      "description": "实现 token 签发、验证和刷新",
      "stage": "development",
      "due_date": "2026-10-20",
      "sub_milestones": [
        {
          "title": "设计 token schema",
          "description": "...",
          "estimated_days": 1
        },
        ...
      ]
    },
    ...
  ]
}
         │
         ▼
写入 project_milestones 表（批量创建）
         │
         ▼
返回前端，刷新 MilestoneManager
```

#### 关键设计决策

1. **LLM 调用方式**: 复用现有 `OrchestrationService` 的 LLM 客户端，不新增依赖
2. **子里程碑**: 当前 `project_milestones` 表无 parent_id 字段，需新增 `parent_id`（nullable FK → self）支持层级
3. **幂等性**: 分解前先查询现有里程碑，prompt 中提示避免重复
4. **估算**: `estimated_days` 为新增字段，辅助进度顾问计算

#### 数据库迁移

```sql
-- project_milestones 新增字段
ALTER TABLE project_milestones ADD COLUMN parent_id TEXT REFERENCES project_milestones(id);
ALTER TABLE project_milestones ADD COLUMN estimated_days REAL;
CREATE INDEX idx_milestones_parent ON project_milestones(parent_id);
```

#### API 端点

```
POST /api/v1/projects/{id}/ai/decompose-tasks
  Request:  { requirement: str, context?: str }
  Response: { milestones: Milestone[], tokens_used: int }

POST /api/v1/projects/{id}/ai/decompose-tasks/preview
  Request:  { requirement: str, context?: str }
  Response: { proposed: Milestone[], tokens_used: int }
  （预览模式，不写入数据库，用户确认后再创建）
```

### 4.2 M2: 对话知识沉淀

#### 数据流

```
会话结束 / 用户手动触发
         │
         ▼
ProjectKnowledgeExtractor.extract(
  project: Project,
  messages: List[ChatMessage],
  existing_profile: List[ProjectProfileEntry]
)
         │
         ▼
构建 prompt:
  - system: "从对话中提取值得持久化的项目知识"
  - context:
    - project_type + description
    - existing_profile entries (去重)
    - 最近 N 条对话消息
  - extraction categories:
    - convention: 编码约定、命名规范
    - architecture: 架构决策、设计模式
    - decision: 技术选型、方案取舍
    - goal: 项目目标、里程碑意图
    - note: 其他值得记住的信息
         │
         ▼
LLM 输出:
{
  "entries": [
    {
      "content": "项目使用 JWT + Redis 黑名单方案做 token 失效",
      "category": "decision",
      "importance": 8,
      "source_message_ids": ["msg_abc", "msg_def"]
    },
    ...
  ]
}
         │
         ▼
语义去重（与 existing_profile 比对内容相似度）
         │
         ▼
前端展示提取结果，用户勾选确认后写入
POST /api/v1/projects/{id}/knowledge/confirm
```

#### 关键设计决策

1. **触发时机**: 两个入口——
   - 手动：`KnowledgeExtractionPanel` 中点击"提取知识"
   - 自动（可选）：会话结束时 `PostToolUse` hook 触发，但仅生成建议不自动写入
2. **去重策略**: 使用简单的字符串相似度（Jaccard），Phase 2 可升级为 embedding 余弦相似度
3. **安全扫描**: 复用 `ProjectProfileStore` 现有的 safety scan 逻辑
4. **1000字符限制**: 沿用现有 Profile 的全局限制

#### API 端点

```
POST /api/v1/projects/{id}/ai/extract-knowledge
  Request:  { session_id: str, message_range?: [start, end] }
  Response: { entries: ProposedEntry[], tokens_used: int }

POST /api/v1/projects/{id}/knowledge/confirm
  Request:  { entries: [{ content, category, importance }] }
  Response: { created: int, skipped: int }
```

### 4.3 M3: 项目进度顾问

#### 数据流

```
用户打开项目 / 定时触发
         │
         ▼
ProjectAdvisor.analyze(project_id)
         │
         ▼
收集数据:
  - milestone_repo.count_by_status() → pending/in_progress/completed/blocked
  - git-status → branch, uncommitted_changes, recent_commits
  - session count + last active time
  - project_diagnose → runtime availability
  - constraints count + materials count
         │
         ▼
构建 prompt:
  - system: "你是项目顾问，根据项目数据给出简洁可行的建议"
  - structured data (JSON)
  - 要求输出:
    - health_score: 0-100
    - risks: [{ description, severity, suggestion }]
    - suggestions: [{ action, reason, priority }]
    - summary: str (1-2 句话)
         │
         ▼
LLM 输出:
{
  "health_score": 72,
  "summary": "项目整体进展良好，但认证模块已逾期",
  "risks": [
    {
      "description": "JWT 认证里程碑已逾期 3 天",
      "severity": "high",
      "suggestion": "建议分解为更小的子任务"
    }
  ],
  "suggestions": [
    {
      "action": "为测试模块添加约束模板",
      "reason": "当前无测试相关约束，但项目处于 testing 阶段",
      "priority": "medium"
    }
  ]
}
         │
         ▼
缓存 30 分钟（避免频繁调用 LLM）
         │
         ▼
前端 ProjectAdvisorCard 展示
```

#### 关键设计决策

1. **缓存策略**: 后端内存缓存，key=project_id，TTL=30min。用户可手动刷新
2. **健康评分**: LLM 输出 0-100 分，但计算逻辑透明化（prompt 中给出评分标准）
3. **不自动执行**: 所有建议仅展示，用户手动确认后 AI 才执行（如"分解任务"→调用 M1）
4. **上下文注入**: 顾问结果可注入到下次对话的 system prompt（可选，由用户开关）

#### API 端点

```
GET /api/v1/projects/{id}/ai/advice
  Response: { health_score, summary, risks, suggestions, cached_at }
  Cache: 30min TTL

POST /api/v1/projects/{id}/ai/advice/refresh
  Response: (同上，强制刷新，忽略缓存)
```

### 4.4 M4: 语义索引管线（Phase 2 概要）

#### 架构

```
Material 添加
     │
     ▼
状态: pending_index
     │
     ▼
BackgroundIndexer (asyncio.Task)
  - 读取 material.content
  - 调用 embedding API (本地 / 远程)
  - 存入 project_material_embeddings 表
     │
     ▼
状态: ready (带 embedding)
     │
     ▼
语义检索:
  - 用户提问 → 问题 embedding
  - 余弦相似度 > 阈值 → 召回相关 chunks
  - 替代全量注入（当前 L4 材料层）
```

#### 新增表

```sql
CREATE TABLE project_material_embeddings (
  id TEXT PRIMARY KEY,
  material_id TEXT REFERENCES project_materials(id) ON DELETE CASCADE,
  chunk_index INTEGER,
  content TEXT,           -- 原始 chunk 文本
  embedding BLOB,         -- float32 向量
  token_count INTEGER,
  created_at INTEGER
);
```

### 4.5 M5: 代码→Wiki 生成（Phase 2 概要）

#### 架构

```
用户触发 "生成项目文档"
         │
         ▼
ProjectWikiGenerator.generate(project_id)
         │
     ├── 1. Scan: 遍历 allowed_paths 内的源文件
     ├── 2. Parse: Python ast / JS tree-sitter 提取符号
     ├── 3. Graph: 构建依赖关系图（import/inherit/call）
     ├── 4. Plan: LLM 规划文档结构（overview + per-module）
     ├── 5. Write: 逐模块生成 Markdown + Mermaid
     └── 6. Store: 写入 wiki pages 表
         │
         ▼
用户在 Wiki 页面浏览生成的文档
支持增量更新（文件 hash 变化 → 仅重新生成受影响页面）
```

---

## 5. 实施步骤

### Phase 1（P0）

#### Sprint 1: M1 智能任务分解

- [x] 步骤 1: 数据库迁移 — `project_milestones` 新增 `parent_id` + `estimated_days`
- [x] 步骤 2: `project_milestone_repo.py` 增加 `create_batch()` 和 `get_tree()` 方法
- [x] 步骤 3: 实现 `ProjectTaskDecomposer` 服务（LLM prompt 工程 + 结构化输出解析）
- [x] 步骤 4: 实现 `decompose_tasks_tool.py`（LLM 可调用工具）
- [x] 步骤 5: 新增 API 路由 `POST .../ai/decompose-tasks` 和 `.../preview`
- [x] 步骤 6: 前端 `TaskDecomposeDialog.tsx` — 输入需求 → 预览 → 确认创建
- [x] 步骤 7: 前端 `MilestoneManager.tsx` 增加"AI 分解"按钮
- [x] 步骤 8: 前端 API 调用封装 + 类型定义 + Electron IPC 桥接
- [x] 步骤 9: 单元测试（后端服务 + API 端点）
- [ ] 步骤 10: 集成测试（前端 E2E 流程）

#### Sprint 2: M2 对话知识沉淀

- [x] 步骤 1: 实现 `ProjectKnowledgeExtractor` 服务
- [x] 步骤 2: 实现 `extract_knowledge_tool.py`
- [x] 步骤 3: 新增 API 路由 `POST .../ai/extract-knowledge` + `.../knowledge/confirm`
- [x] 步骤 4: 去重逻辑 — 复用 `ProjectProfileStore.add()` 内置去重 + LLM prompt 传入已有条目
- [x] 步骤 5: 前端 `KnowledgeExtractionPanel.tsx` — 展示提取结果 + 勾选确认
- [x] 步骤 6: 集成到 `ProjectArchetypeStudio` 的 Profile Tab
- [x] 步骤 7: 单元测试 + 集成测试

#### Sprint 3: M3 项目进度顾问

- [x] 步骤 1: 实现 `ProjectAdvisor` 服务（数据收集 + prompt 构建）
- [x] 步骤 2: 实现 `project_advise_tool.py`
- [x] 步骤 3: 新增 API 路由 `GET .../ai/advice` + `POST .../ai/advice/refresh`
- [x] 步骤 4: 后端缓存层（30min TTL）— 集成在 ProjectAdvisor 内
- [x] 步骤 5: 前端 `ProjectAdvisorCard.tsx` — 健康分 + 风险 + 建议
- [x] 步骤 6: 集成到 `ProjectOverviewWidgets`（侧边栏 + 工作室均消费）
- [x] 步骤 7: 顾问建议 → M1 任务分解的联动（点击"分解任务"跳转 M1 对话框）
- [x] 步骤 8: 单元测试 + 集成测试

### Phase 2（P1，概要步骤）

#### Sprint 4-5: M4 语义索引

- [x] 数据库迁移 v7 — `project_materials_vec` sqlite-vec 虚拟表（动态创建）
- [x] Embedding 服务 — 复用现有 `Embedder` Protocol + `create_embedder()` 工厂
- [x] `ProjectMaterialIndexer` — 索引 + 语义检索 + 统计
- [x] 语义检索 API — `GET /ai/materials/search` + `GET /ai/materials/indexing-stats` + `POST /ai/materials/{id}/index`
- [x] 移除 P0 backfill — `init_db()` 不再自动回填 `pending_index → ready`
- [x] 单元测试 — 27 tests covering indexer, search, stats, chunking
- [x] L4 材料层从全量注入改为检索注入 — `build_project_materials_block_semantic()` + 降级回退 + 11 tests
- [x] 前端材料面板集成 — 语义检索 UI (2026-10-12): `SemanticSearchPanel.tsx` + 3 个 IPC 路由 + 3 个 API 封装 + 6 个 Wire/Result 类型 + barrel 导出 + 集成到 `StudioMaterialsTabPanel`

#### Sprint 6-7: M5 代码→Wiki

- [x] 文件扫描器（复用 `allowed_paths`） — `scan_files()` + `EXCLUDED_DIRS` + 语言过滤 + 25 tests
- [x] Python AST 符号提取器 — `extract_symbols()` + 类/方法/装饰器/继承 + 修复 ast.walk 重复提取 bug
- [x] 依赖图构建 — `build_dependency_graph()` + import 解析 + 类继承边
- [x] LLM 文档结构规划 — `_plan_documentation()` + JSON 结构化输出
- [x] 逐模块 Wiki 页面生成 — `_generate_pages()` + 源码上下文注入
- [x] 写入 Wiki 文件 — `_write_wiki_pages()` via `secure_write_file()` (非 SQL 表)
- [x] 增量更新机制 — `content_hash` 比对 + `incremental=True` 标志
- [x] API 端点 — `POST /wiki/generate` + `GET /wiki/scan-files` + `GET /wiki/extract-symbols`
- [x] 修复 `_get_llm_client` 不存在 bug — 改用 `build_llm_client_from_settings()`
- [x] 前端 Wiki 生成 UI — `WikiGenerationPanel.tsx` + 3 个 IPC 路由 + 3 个 API 封装 + 6 个 Wire/Result 类型 + barrel 导出 + 集成到 `ProjectOverviewWidgets` (coding/git 项目)

---

## 6. 风险评估与依赖

### 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 输出格式不稳定 | 任务分解/知识提取结果解析失败 | 结构化输出 + 重试 + fallback 到纯文本展示 |
| LLM 延迟影响用户体验 | 任务分解等待时间长 | preview 模式先展示，用户确认后再写入 |
| 里程碑层级递归深度 | parent_id 循环引用 | 数据库层 CHECK 约束 + API 层校验 |
| Embedding API 成本 | 语义索引大量调用 | 本地模型优先（sentence-transformers），远程 API 作为 fallback |
| 对话隐私 | 知识提取可能暴露敏感信息 | 用户手动确认，不自动写入；安全扫描沿用现有机制 |

### 依赖

- LLM 客户端：复用 `OrchestrationService` 现有配置
- Wiki 子系统：M5 依赖 `backend/wiki/` 模块
- Embedding：Phase 2 需确认 embedding 模型选型

---

## 7. 验收标准

### M1 智能任务分解

- 输入自然语言需求 → 输出结构化里程碑树（支持至少 2 层）
- 预览模式不写入数据库，确认后批量创建
- 支持 coding/research/business/personal 四种类型的术语适配
- 现有里程碑不重复创建

### M2 对话知识沉淀

- 会话对话历史 → 提取 1-10 条知识条目建议
- 用户可逐条确认/拒绝
- 与现有 Profile 条目去重（相似度 > 80% 跳过）
- 提取结果包含 source_message_ids 可追溯

### M3 项目进度顾问

- 输出健康分 0-100 + 风险列表 + 建议列表
- 30 分钟缓存，手动刷新可用
- 建议可联动到 M1（点击"分解任务"打开 M1 对话框）
- 诊断数据来源于现有 git-status / milestone / diagnose 端点
