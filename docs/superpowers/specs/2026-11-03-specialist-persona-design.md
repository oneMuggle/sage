# 专家/数字员工（Specialist Persona）详细设计

> 状态：**设计稿，待实施**
> 日期：2026-11-03
> 分支：feat/specialist-persona
> 前置文档：`docs/plans/2026-11-02_specialist-personas.md`

---

## 1. 设计决策（已确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| **定位** | 只做生产力「专家/数字员工」 | 专注工作场景，不做 Character.AI/SillyTavern 兼容 |
| **记忆默认** | 角色私有 + 共享显式提升 | 强化隐私，默认 `write_scope=specialist` |
| **知识绑定** | 允许专家私有知识目录 | 存储于 `~/.sage/specialists/<id>/knowledge/`，支持专家独有参考资料 |
| **分发** | 本地文件导入导出（暂不做团队共享） | zip 包格式，不含网络分发 |
| **多专家协作** | 首期单专家会话 | 不做 council/debate，多专家仍走现有编排 |

---

## 2. 数据模型设计

### 2.1 `agents` 表扩展

在现有 `agents` 表上增加字段（不新建平行表）：

```sql
-- 新增字段（migration 版本号 +1）
ALTER TABLE agents ADD COLUMN skills TEXT DEFAULT '[]';           -- JSON: 技能允许集
ALTER TABLE agents ADD COLUMN knowledge_bindings TEXT DEFAULT '[]'; -- JSON: 知识绑定
ALTER TABLE agents ADD COLUMN memory_policy TEXT DEFAULT '{}';      -- JSON: 记忆策略
ALTER TABLE agents ADD COLUMN persona_ui TEXT DEFAULT '{}';         -- JSON: 头像/tagline/开场白/示例/推荐
ALTER TABLE agents ADD COLUMN permission_mode TEXT DEFAULT 'workspace_write';
ALTER TABLE agents ADD COLUMN version INTEGER DEFAULT 1;
ALTER TABLE agents ADD COLUMN source TEXT DEFAULT 'user';           -- 'builtin' | 'user' | 'imported'
```

**字段说明**：

| 字段 | 类型 | 示例 | 说明 |
|------|------|------|------|
| `skills` | JSON array | `["writing", "research", "plugin__zotero__*"]` | 技能允许集，支持通配 |
| `knowledge_bindings` | JSON array | `[{"type":"wiki_project","id":"proj_123"}, {"type":"specialist_dir","path":"~/.sage/specialists/sp_1/knowledge"}]` | 知识绑定列表 |
| `memory_policy` | JSON object | `{"read_scopes":["specialist","project","user"],"write_scope":"specialist","auto_extract":true}` | 记忆读写策略 |
| `persona_ui` | JSON object | `{"avatar":"📝","tagline":"写作助手","greeting":"你好，我是写作专家","suggested_prompts":["帮我润色这段"]}` | 卡片 UI 元素 |
| `permission_mode` | TEXT | `'read_only' \| 'workspace_write' \| 'prompt' \| 'full_access'` | 权限模式 |
| `version` | INTEGER | `1` | 专家版本号（每次修改人设/知识绑定 +1） |
| `source` | TEXT | `'user'` | 来源：内置/用户创建/导入 |

### 2.2 专家私有知识目录

存储路径：`~/.sage/specialists/<agent_id>/knowledge/`

```
~/.sage/specialists/
├── sp_writing/
│   ├── knowledge/
│   │   ├── style-guide.pdf
│   │   ├── examples.docx
│   │   └── references.bib
│   └── metadata.json    # {"name":"写作专家","version":3,...}
└── sp_research/
    └── knowledge/
        └── papers/
```

**索引策略**：
- 复用现有 LanceDB 向量索引
- 在向量表增加 `agent_id` 列（nullable）
- 查询时按 `agent_id` 过滤：`WHERE agent_id = ? OR agent_id IS NULL`（专家私有 ∪ 全局共享）
- 新增专家知识目录时，异步触发索引构建（复用 `rag-service`）

### 2.3 记忆表扩展

```sql
-- memories_episodic / memories_semantic / 向量表增加 agent_id
ALTER TABLE memories_episodic ADD COLUMN agent_id TEXT;
ALTER TABLE memories_semantic ADD COLUMN agent_id TEXT;
ALTER TABLE memory_vectors ADD COLUMN agent_id TEXT;

-- 索引
CREATE INDEX idx_memories_agent ON memories_episodic(agent_id);
CREATE INDEX idx_memories_semantic_agent ON memories_semantic(agent_id);
```

**可见性规则**：
- 当前专家私有：`WHERE agent_id = ?`
- 共享层（用户/项目）：`WHERE agent_id IS NULL`
- 完整查询：`WHERE agent_id = ? OR agent_id IS NULL`

**迁移**：历史数据 `agent_id IS NULL` → 视为共享层（用户/项目级），无需回填。

---

## 3. 提示词分层设计

### 3.1 统一 Composer

引入 `compose_system_prompt(specialist, scenario)`，固定优先级：

```text
[1] 系统安全规则（不可覆盖）
    ↓
[2] 基座能力声明（按工具白名单条件注入）
    ↓
[3] 专家人设/职责/风格/护栏/输出模板（受保护层，不可裁剪）
    ↓
[4] 场景块（Plan Mode / 编排 / slash 指令）
    ↓
[5] 知识上下文（检索结果，按预算裁剪）
    ↓
[6] 记忆上下文（召回结果，按预算裁剪）
    ↓
[7] 项目规则（SAGE.md / AGENTS.md / CLAUDE.md）
    ↓
[8] 环境与技能清单
```

**实现**：`backend/chat/specialist_prompt_composer.py`（新文件）

```python
def compose_system_prompt(
    specialist: AgentProfile,
    scenario: dict,
    knowledge_context: Optional[str] = None,
    memory_context: Optional[str] = None,
) -> str:
    """
    组装 system prompt。
    
    优先级：
    1. 系统安全规则（硬编码）
    2. 基座能力（按 specialist.skills 条件渲染）
    3. 专家人设（specialist.system_prompt + persona_ui.guardrails）
    4. 场景块（scenario.get("plan_mode"), scenario.get("orchestration"))
    5. 知识上下文（检索结果，带引用）
    6. 记忆上下文（召回结果）
    7. 项目规则（discover_project_context()）
    8. 环境与技能清单
    """
    parts = []
    
    # [1] 系统安全规则
    parts.append(SYSTEM_SAFETY_RULES)
    
    # [2] 基座能力（按技能白名单条件注入）
    capability_block = render_capability_block(specialist.skills)
    if capability_block:
        parts.append(capability_block)
    
    # [3] 专家人设（受保护层）
    if specialist.system_prompt:
        parts.append(f"## 专家身份\n\n{specialist.system_prompt}")
    if specialist.persona_ui.get("guardrails"):
        parts.append(f"## 行为边界\n\n{specialist.persona_ui['guardrails']}")
    
    # [4] 场景块
    if scenario.get("plan_mode"):
        parts.append(PLAN_MODE_BLOCK)
    if scenario.get("orchestration"):
        parts.append(ORCHESTRATION_BLOCK)
    
    # [5] 知识上下文
    if knowledge_context:
        parts.append(f"## 知识库参考\n\n{knowledge_context}")
    
    # [6] 记忆上下文
    if memory_context:
        parts.append(f"## 相关记忆\n\n{memory_context}")
    
    # [7] 项目规则
    project_context = discover_project_context(scenario.get("project_id"))
    if project_context:
        parts.append(project_context)
    
    # [8] 环境与技能清单
    parts.append(render_skill_inventory(specialist.skills))
    
    return "\n\n".join(parts)
```

**关键修复**：
- `/chat/stream` 必须使用 `compose_system_prompt()`，而不是忽略 `specialist.system_prompt`
- 基座能力块按 `specialist.skills` 条件渲染：没有 Office 工具就不注入 Office 长文

---

## 4. 会话绑定设计

### 4.1 `sessions` 表扩展

```sql
ALTER TABLE sessions ADD COLUMN specialist_id TEXT DEFAULT 'primary';
CREATE INDEX idx_sessions_specialist ON sessions(specialist_id);
```

**默认值**：`primary`（主助手，向后兼容）

### 4.2 API 扩展

**创建会话**：
```typescript
POST /api/v1/sessions
{
  "title": "新会话",
  "specialistId": "sp_writing"  // 新增
}
```

**切换专家**：
```typescript
POST /api/v1/sessions/{id}/switch-specialist
{
  "specialistId": "sp_research",
  "contextStrategy": "new_session"  // "new_session" | "continue_with_context"
}
```

**默认行为**：`contextStrategy = "new_session"`（新建会话），避免上下文污染。

### 4.3 前端体验

**新会话页**：
- 专家卡片网格（头像 + tagline + 推荐任务）
- 点击卡片 → 创建会话并绑定专家

**聊天头部**：
- 显示当前专家徽章（头像 + 名称）
- 点击 → 打开专家选择器（默认"新建会话"，可选"带上下文切换"）

**侧栏**：
- 会话列表按专家分组（可折叠）
- 每个会话显示专家小头像

---

## 5. 技能作用域设计

### 5.1 四个入口统一过滤

专家声明 `skills` 允许集；执行面 fail-closed。四处统一过滤：

```python
# backend/skills/skill_registry.py
class SkillRegistry:
    def list_skills(self, specialist: Optional[AgentProfile] = None) -> list[Skill]:
        """列出可见技能。"""
        all_skills = self._all_skills()
        if specialist and specialist.skills:
            allowed = self._resolve_skill_pattern(specialist.skills)
            return [s for s in all_skills if s.name in allowed]
        return all_skills
    
    def auto_activate(self, specialist: Optional[AgentProfile], ...) -> list[Skill]:
        """自动激活（按专家允许集过滤）。"""
        candidates = self.list_skills(specialist)
        return [s for s in candidates if s.should_auto_activate(...)]
    
    def slash_commands(self, specialist: Optional[AgentProfile] = None) -> list[SlashCommand]:
        """slash 命令索引（按专家允许集过滤）。"""
        skills = self.list_skills(specialist)
        return [SlashCommand.from_skill(s) for s in skills if s.slash_enabled]
    
    def execute(self, specialist: Optional[AgentProfile], skill_name: str, ...):
        """执行技能（fail-closed）。"""
        if specialist and specialist.skills:
            allowed = self._resolve_skill_pattern(specialist.skills)
            if skill_name not in allowed:
                raise PermissionDenied(f"专家 {specialist.name} 无权使用技能 {skill_name}")
        return self._execute_skill(skill_name, ...)
```

**通配解析**：
```python
def _resolve_skill_pattern(self, patterns: list[str]) -> set[str]:
    """解析技能允许集（支持 plugin__<name>__* 通配）。"""
    resolved = set()
    for pattern in patterns:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            resolved.update(s.name for s in self._all_skills() if s.name.startswith(prefix))
        else:
            resolved.add(pattern)
    return resolved
```

### 5.2 专家私有技能目录

存储路径：`~/.sage/specialists/<agent_id>/skills/`

```
~/.sage/specialists/sp_writing/
├── skills/
│   ├── polish-prose/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── polish.py
│   └── citation-format/
│       └── SKILL.md
└── knowledge/
```

**加载逻辑**：
- `SkillRegistry.__init__()` 扫描 `~/.sage/specialists/*/skills/`
- 按 `agent_id` 分组，仅在对应专家会话中可见
- 同名冲突：专家私有 > 全局（但日志 warn）

---

## 6. 知识绑定设计

### 6.1 `KnowledgeBinding` 数据模型

```python
# backend/domain/knowledge.py
class KnowledgeBinding(BaseModel):
    type: Literal["wiki_project", "zotero_collection", "project_material", "workspace_path", "specialist_dir", "file"]
    # 按 type 不同，以下字段可选
    project_id: Optional[str]  # wiki_project
    collection_id: Optional[str]  # zotero_collection
    path: Optional[str]  # workspace_path / specialist_dir / file
    
    class Config:
        extra = "forbid"
```

**类型说明**：

| type | 说明 | 存储位置 |
|------|------|---------|
| `wiki_project` | Wiki 项目 | 现有 LanceDB 索引 |
| `zotero_collection` | Zotero 集合 | 现有 Zotero 向量索引 |
| `project_material` | 项目资料 | 现有 `project_materials` 表 |
| `workspace_path` | 工作区路径 | 现有工作区索引 |
| `specialist_dir` | 专家私有目录 | `~/.sage/specialists/<id>/knowledge/` |
| `file` | 单个文件 | 按需索引 |

### 6.2 检索编排

```python
# backend/services/knowledge_retriever.py
class KnowledgeRetriever:
    async def retrieve(
        self,
        specialist: AgentProfile,
        query: str,
        top_k: int = 5,
    ) -> list[KnowledgeChunk]:
        """
        按专家知识绑定检索。
        
        流程：
        1. 遍历 specialist.knowledge_bindings
        2. 按 type 扇出到对应检索器
        3. RRF 融合（Reciprocal Rank Fusion）
        4. 专家可见性过滤（specialist_dir 仅当前专家可见）
        5. 预算截断（top_k）
        6. 带引用注入
        """
        chunks_by_source = {}
        
        for binding in specialist.knowledge_bindings:
            if binding.type == "wiki_project":
                chunks = await self._retrieve_wiki(binding.project_id, query, top_k)
            elif binding.type == "zotero_collection":
                chunks = await self._retrieve_zotero(binding.collection_id, query, top_k)
            elif binding.type == "specialist_dir":
                chunks = await self._retrieve_specialist_dir(specialist.id, query, top_k)
            # ... 其他 type
            
            chunks_by_source[binding.type] = chunks
        
        # RRF 融合
        fused = reciprocal_rank_fusion(chunks_by_source)
        
        # 预算截断
        return fused[:top_k]
```

**无命中拒答**：
```python
if not chunks:
    return "知识库无相关内容，建议补充参考资料或调整问题。"
```

---

## 7. 记忆作用域设计

### 7.1 读写策略

```python
# backend/domain/memory.py
class MemoryPolicy(BaseModel):
    read_scopes: list[Literal["user", "project", "specialist", "global"]] = ["specialist", "project", "user"]
    write_scope: Literal["specialist", "project", "user"] = "specialist"
    auto_extract: bool = True
    retention_days: Optional[int] = None
    
    class Config:
        extra = "forbid"
```

**默认策略**：
- `read_scopes = ["specialist", "project", "user"]`：专家私有 ∪ 项目 ∪ 用户
- `write_scope = "specialist"`：默认写入专家私有层
- `auto_extract = True`：自动从对话抽取事实

### 7.2 身份贯穿

```python
# backend/agents/tool_execution.py
class ToolExecutionContext:
    agent_id: str  # 当前专家 ID
    session_id: str
    project_id: Optional[str]
    
    def get_memory_manager(self) -> MemoryManager:
        """返回绑定当前专家的记忆管理器。"""
        return MemoryManager(agent_id=self.agent_id, project_id=self.project_id)
```

**子代理继承**：
```python
# backend/orchestration/subagent_runner.py
class SubagentRunner:
    def spawn(self, parent_ctx: ToolExecutionContext, ...) -> ToolExecutionContext:
        """子代理默认继承父代理的 agent_id。"""
        return ToolExecutionContext(
            agent_id=parent_ctx.agent_id,  # 继承
            session_id=parent_ctx.session_id,
            project_id=parent_ctx.project_id,
        )
```

### 7.3 显式提升为共享

前端 UI：
```typescript
// src/components/MemoryPromoteButton.tsx
<Button onClick={() => promoteToShared(memoryId)}>
  提升为共享记忆
</Button>
```

后端 API：
```python
# backend/api/memory_routes.py
@router.post("/memories/{id}/promote")
async def promote_memory(id: str, target_scope: Literal["user", "project"]):
    """将专家私有记忆提升为共享。"""
    memory = await memory_repo.get(id)
    if memory.agent_id is None:
        raise BadRequest("已是共享记忆")
    
    # 清除 agent_id → 变为共享
    await memory_repo.update(id, {"agent_id": None, "scope": target_scope})
```

---

## 8. 专家包格式设计

### 8.1 zip 包结构

```
specialist_writing.zip
├── persona.md          # 人设与配置（Markdown frontmatter）
├── avatar.png          # 头像（可选，≤ 512KB）
├── skills/             # 专家私有技能（可选）
│   └── polish-prose/
│       └── SKILL.md
└── knowledge/          # 专家私有知识（可选，≤ 50MB）
    ├── style-guide.pdf
    └── examples.docx
```

### 8.2 `persona.md` 格式

```markdown
---
name: 写作专家
tagline: 专业写作助手
version: 1
source: user
---

# 身份

你是一位专业写作助手，擅长润色、改写、翻译各类文本。

# 行为边界

- 永远保持原文的核心意思
- 优先使用主动语态
- 避免生僻词汇

# 输出模板

当用户要求润色时，按以下格式输出：

## 润色结果

[润色后的文本]

## 修改说明

- 修改 1：...
- 修改 2：...
```

### 8.3 导入/导出 API

**导出**：
```python
# backend/api/specialist_routes.py
@router.get("/specialists/{id}/export")
async def export_specialist(id: str) -> FileResponse:
    """导出专家包为 zip。"""
    specialist = await specialist_repo.get(id)
    zip_path = await specialist_exporter.export(specialist)
    return FileResponse(zip_path, filename=f"{specialist.name}.zip")
```

**导入**：
```python
@router.post("/specialists/import")
async def import_specialist(file: UploadFile) -> dict:
    """导入专家包。"""
    # 1. 解压 zip
    # 2. 解析 persona.md
    # 3. 验证安全性（无脚本自动执行、无密钥、无注入）
    # 4. 复制 knowledge/ → ~/.sage/specialists/<new_id>/knowledge/
    # 5. 复制 skills/ → ~/.sage/specialists/<new_id>/skills/
    # 6. 写入 agents 表
    # 7. 触发知识索引构建
    return {"id": new_id, "name": specialist.name}
```

**安全校验**：
- 不自动执行 `skills/*/scripts/*.py`
- 扫描 `persona.md` 中的提示词注入模式（如 "ignore previous instructions"）
- 包内不得含密钥（正则扫描 `API_KEY`、`SECRET`、`TOKEN`）

---

## 9. 实施里程碑

### M0：接线修复（1-1.5 周，硬前置）

**目标**：让 `AgentProfile` 真正驱动运行时

**任务**：
- [x] 实现 `compose_system_prompt()` + `/chat/stream` 使用
- [x] stream 链路接通 profile 模型 / temperature / max_tokens
- [x] 会话级专家绑定 + 聊天角色选择器
- [x] 新建 / 删除 / 复制专家 UI；模型改为目录下拉
- [x] 系统提示中的专家列表改读 SQLite，反映启用状态
- [x] `memory_access` 最小执行（读层过滤）
- [x] 修复内置 persona 工具名漂移（`terminal` → `bash`）

**验收**：在聊天中选择「写作专家」，其提示词、工具、模型、记忆读写策略全部生效；切回主助手无残留。

### M1：专家卡与技能库（1.5-2 周）

**目标**：专家画廊 + 技能作用域 fail-closed

**任务**：
- [x] `agents` 表扩展字段 + migration 版本化
- [x] `/specialists` 画廊、创建向导、六段编辑器、预览与试聊
- [x] 技能允许集在四个入口 fail-closed
- [x] 专家私有技能目录（`~/.sage/specialists/<id>/skills/`）
- [x] `.sage` 导入导出 + 专家包 zip 雏形

**验收**：同一全局技能库下，写作专家看不到编码技能；非法技能名无法执行。

### M2：知识绑定（2-3 周）

**目标**：专家可绑定多个知识源，统一检索

**任务**：
- [x] `KnowledgeBinding` 数据模型与 UI
- [x] Wiki / Zotero / 项目资料 / 工作区 / 专家私有目录接入（已接 wiki_project / project_material / specialist_private；zotero_collection 与 workspace_fts 待上游返回集合元数据后接入，见 M2 计划文档）
- [x] 向量表增加 `agent_id` 列 + 索引（**策略调整**：不修改现有三层存储 schema，改为路由层 `knowledge_retriever.py` 扇出 + 独立专家私有向量库 `~/.sage/specialists/<id>/vectors.json`，理由与替代方案见 `docs/plans/2026-11-03_m2-knowledge-binding.md`）
- [x] 统一检索编排 + RRF + 引用输出
- [x] 无命中拒答策略与可观测日志

**验收**：研究专家只引用绑定的 Zotero 集合与 Wiki 空间；引用可点击定位。

### M3：记忆隔离（2-3 周）

**目标**：专家私有记忆 + 共享显式提升

**任务**：
- [x] 记忆表 / 向量表增加 `agent_id` 维度与索引（**落地偏离**：仅 `memories_episodic` / `memories_semantic` 加列 + 索引；sqlite-vec 向量表 payload 无 agent 维度，改为 RRF 融合后按主表行 `is_row_visible` 二次过滤，见 M3 计划文档）
- [x] 读写策略（默认 `write_scope=specialist`）
- [x] 身份贯穿（`ToolExecutionContext.agent_id` → `MemoryManager`）
- [x] 子代理默认继承当前专家
- [x] 记忆浏览器筛选 / 导出 / 级联删除
- [x] 显式"提升为共享"按钮
- [x] 迁移：历史数据 `agent_id IS NULL` → 视为共享层

**验收**：写作专家与编码专家的私有记忆互不可见；共享用户偏好双方可见；删除专家级联清理私有记忆。

### M4：分发与质量（1-2 周，可选）

**目标**：专家包稳定 + 内置模板库

**任务**：
- [ ] 专家包格式稳定（zip: persona.md + avatar + skills + knowledge）
- [ ] 内置模板库（写作 / 研究 / 编码 / 演示 / Office）
- [ ] 版本 diff / 回滚
- [ ] 黄金任务集评测
- [ ] Win7 双侧同步与文档归档

**验收**：用户可从模板库一键创建写作专家；专家包可导出并导入到另一台机器。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 在断链上盖楼 | M0 先行，作为硬前置 |
| 提示词膨胀 | 条件能力块 + 预算裁剪 + 受保护层白名单 |
| 记忆碎片化 | 共享用户/项目层 + 显式提升机制 |
| 知识幻觉 | 引用强制 + 阈值 + 无命中拒答 |
| 角色数量膨胀 | 模板画廊 + 场景标签 + 使用统计 + 归档 |
| 包安全 | 不自动执行 + 注入扫描 + 权限确认 |
| 双分支成本 | 纯 SQLite / 文件实现，避免新重依赖；按 M0–M4 分批同步 |

---

## 11. 验收指标

- 专家任务完成率 / 一次通过率相对 primary 提升（按黄金任务集）
- 工具误用率、无关工具暴露数下降
- 知识回答引用准确率、无命中拒答率
- 角色切换后上下文污染事件为 0（跨角色记忆不可见测试）
- 专家创建到首次可用 ≤ 5 分钟（模板路径）
- 单专家 token / 成本可观测

---

## 12. 参考

- [AI 智能体协作知识体系](http://www.ldpk.cn/news/58813)
- [Coze 智能体创建指南](https://developer.aliyun.com/article/1680193)
- [智能体来了：从 0-1 开启你的 AI 分身](https://developer.aliyun.com/1708097)
- Sage 内部：`docs/technical/22-agents-crud.md`、`24-skills-system.md`、`39-memory-user-profile.md`、`42-chat-multi-agent-orchestration.md`、`58-project-context-aggregation.md`、`121-zotero-llm-integration.md`、`115-project-playbook.md`
