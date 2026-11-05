# 项目管理增强：嵌套 + 模板 + 文件引用

> 状态：**设计已批准，待实施**
> 创建日期：2026-11-05
> 作者：Claude + 用户
> 范围：通用能力（CFD 计算场景作为参考，不写 CFD 特定代码）

---

## 1. 背景与目标

### 1.1 问题

Sage 当前的项目管理是**扁平结构**，无法满足以下场景：

| 场景 | 需求 |
|------|------|
| 大型科研项目（CFD / 学术 / 企业咨询） | 一个顶层项目下包含多个子项目（网格、算例、报告） |
| 大文件管理 | 网格/结果文件 GB 级，通过快捷方式链接到实际存储位置 |
| 项目结构标准化 | 创建项目时按模板生成标准目录骨架 |

### 1.2 目标

实现三项通用能力（不绑定 CFD 概念）：

1. **项目嵌套**（目录遍历 + 上下文继承）
2. **目录模板**（文件系统 JSON + 全局模板库）
3. **文件引用**（symlink 自动识别 + 内部引用，只读）

## 2. 业界调研结论

调研了 9 款应用（Cursor / Windsurf / Claude Code / Copilot WS / Aider / Continue / Notion AI / Obsidian / Mem.ai）。对 Sage 最具启发的三个模式：

| 模式 | 来源 | Sage 中的应用 |
|------|------|--------------|
| 目录遍历式项目定义 | Claude Code | 嵌套识别的基础 |
| rules + workflows + skills 三层配置 | Windsurf | 上下文级联继承 |
| `@` 上下文提供者 | Continue | （v1 不实现，为未来预留） |

**应避免**：Mem.ai 的完全无结构、Aider 的单仓库限制、Cursor 的禁用符号链接。

## 3. 设计决策汇总

| 决策点 | 选择 | 备选 |
|--------|------|------|
| 范围 | 仅通用能力 | 通用 + CFD 专用 |
| 嵌套模型 | 目录遍历 + 上下文继承 | parent_id 显式父子 / 混合 |
| 快捷方式机制 | symlink + 内部引用两者都支持 | 仅 symlink / 仅内部引用 |
| 模板存储 | 文件系统 JSON（全局库 + 项目内） | Sage 数据库 |
| 子项目识别 | 模板声明 + 自动发现并集 | 仅自动发现 / 仅模板声明 |
| 引用授权 | 复用既有四层模型，新增第 3 层 | 另造权限系统 |
| 引用写权限 | v1 默认只读 | v1 支持读写 |

## 4. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        变更范围                              │
├─────────────────────────────────────────────────────────────┤
│  扩展:  projects 表          (parent_id, discovery_source)  │
│  新增:  file_references 表   (内部快捷方式)                 │
│  新增:  project_templates    (模板库，JSON 文件)             │
│  新增:  workspace_scanner    (目录扫描 + 层级推导)           │
│  扩展:  project_context      (上下文级联继承)               │
│  新增:  virtual_fs           (虚拟文件树解析)                │
└─────────────────────────────────────────────────────────────┘
```

## 5. 数据模型

### 5.1 `projects` 表扩展

```sql
ALTER TABLE projects ADD COLUMN parent_id TEXT;         -- 派生缓存，指向父项目 id
ALTER TABLE projects ADD COLUMN discovery_source TEXT;  -- 'manual' | 'template' | 'context_file'
```

`parent_id` 是**派生缓存**（真相源永远是文件系统路径），扫描时重新计算。
`discovery_source` 用于 UI 展示子项目的发现方式。

### 5.2 `file_references` 表新增

```sql
CREATE TABLE file_references (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    alias_name   TEXT NOT NULL,      -- 显示名
    rel_path     TEXT NOT NULL,      -- 项目内虚拟位置
    target_path  TEXT NOT NULL,      -- 真实目标（绝对路径）
    kind         TEXT NOT NULL,      -- 'file' | 'directory' | 'symlink'
    created_at   INTEGER NOT NULL,
    UNIQUE(project_id, rel_path)
);
```

### 5.3 模板（不入数据库）

用 JSON 文件存储，存在两个位置：
- **全局库**：`~/.sage/templates/*.json`
- **项目内**：`<project>/.sage/template.json`

优先级：项目内 > 全局库 > 内置。

## 6. 模板系统

### 6.1 模板定义格式

```json
{
  "name": "CFD 计算项目",
  "description": "流体仿真计算的目录骨架",
  "version": 1,
  "directories": [
    { "path": "文档", "desc": "参数与任务背景", "role": "folder" },
    { "path": "模型", "desc": "待网格化的几何",   "role": "folder" },
    { "path": "网格", "desc": "网格文件",         "role": "project" },
    { "path": "CFD",  "desc": "算例目录",         "role": "project" }
  ],
  "files": [
    { "path": "SAGE.md", "template": "cfd_project", "overwrite": false },
    { "path": ".sage/template.json", "content": "$SELF", "overwrite": false }
  ]
}
```

字段语义：
- `role: "project"` — 目录是子项目，出现在侧边栏树中
- `role: "folder"` — 普通目录
- `overwrite: false` — 目标已存在则跳过
- `template: "cfd_project"` — 引用内置内容模板

### 6.2 三个模板来源

| 来源 | 位置 | 用途 |
|------|------|------|
| ① 内置模板 | 由现有 `ARCHETYPE_BLUEPRINTS` 泛化 | coding / research / business / personal |
| ② 全局库 | `~/.sage/templates/*.json` | 用户自定义，可增删改 |
| ③ 项目内 | `<project>/.sage/template.json` | 项目自描述，git 可追踪 |

### 6.3 两个应用入口

| 场景 | 行为 |
|------|------|
| **新建项目时选模板** | 生成目录结构 + 文件 + `.sage/template.json` + `SAGE.md` |
| **现有项目套用模板** | 只补齐**缺失**的目录/文件（`overwrite: false`），写入 `.sage/template.json` |

### 6.4 与现有代码的关系

```
backend/services/project_archetype_scaffold.py   (现有)
    ARCHETYPE_BLUEPRINTS: dict[str, ArchetypeBlueprint]
    scaffold_project_archetype()
                    ↓ 泛化
backend/services/project_template.py             (新增)
    ProjectTemplate  (dataclass, 校验/序列化)
    load_template() / list_templates() / save_template()
    scaffold_project(template, root, dry_run)
                    ↓
    内置模板由 ARCHETYPE_BLUEPRINTS.to_templates() 生成
```

`ArchetypeBlueprint` 不删除，变成内置模板的**数据来源**。原 `scaffold_project_archetype()` 保留薄封装保持向后兼容。

### 6.5 模板变量

最小集：`{{project_name}}`、`{{date}}`、`{{datetime}}`、`{{user}}`。不引入表达式引擎。

## 7. 目录扫描与子项目发现

### 7.1 扫描器职责

`backend/services/workspace_scanner.py` — 单一职责：把一棵目录树翻译成"项目树"。

```
scan(root_path, template) → ProjectTree
```

### 7.2 识别算法

```
scan(dir, depth, parent_project):
    for entry in listdir(dir):
        if entry is symlink:
            → 记为 file_reference(kind='symlink')，不递归（防环）
            continue
        if not entry.is_dir(): continue
        if should_skip(entry): continue        # .gitignore / .sageignore / 默认排除

        role = template.role_for(entry.name)
        has_ctx = contains_context_file(entry)

        if role == 'project' or has_ctx:
            → 注册为子项目
            → 递归进入
        elif depth < limit:
            → 继续递归寻找更深层子项目
```

### 7.3 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 最大递归深度 | 6 | 可配，覆盖「顶层 → 子项目 → 算例」等层级 |
| 单目录最大条目数 | 5000 | 超限停止递归该目录 |
| 默认排除集 | `.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`, `.sage` | 不扫描 |
| 扫描缓存 TTL | 30s | 避免频繁 I/O |

另支持 `.sageignore`（.gitignore 语法）。

### 7.4 扫描时机

| 时机 | 说明 |
|------|------|
| 注册项目时 | 首次扫描 |
| 打开项目 / 新建会话时 | 增量刷新 |
| 手动刷新按钮 | 强制重扫 |

### 7.5 与数据库的同步

**只增不删**：

```python
for found in scan_results:
    upsert_project(found.path, parent_id=..., discovery_source=...)
# 磁盘上已消失的目录 → 不删除行，树构建阶段按路径存在性过滤
```

理由：避免子项目被误删时丢失会话历史/记忆/规程。树构建时过滤不存在的路径。

### 7.6 树 API

`GET /api/v1/projects/{id}/tree` 返回：

```json
{
  "root": {
    "id": "...", "path": "/data/cfd-research", "name": "cfd-research",
    "children": [
      { "path": "/data/cfd-research/网格",  "role": "project", "source": "template" },
      { "path": "/data/cfd-research/CFD",   "role": "project", "source": "template" }
    ]
  }
}
```

## 8. 上下文级联继承

### 8.1 现状与差距

`backend/chat/project_context.py` 已实现基于 CWD 的**向上搜索**（SAGE.md/CLAUDE.md/AGENTS.md，按内容哈希去重，单文件 8000 字符，总量 16000 字符）。

**差距**：它是基于 CWD 单向上溯的，不是基于项目树级联。子项目会话拿不到「父项目规则 + 子项目规则」的完整级联。

### 8.2 级联链构造

```
会话绑定到 /data/cfd-research/CFD/case-001
                    ↓ 沿路径向上，找到已注册的祖先项目
祖先链: cfd-research → CFD → case-001
                    ↓
收集每一级的上下文文件
```

### 8.3 拼接顺序与语义

**父 → 子**顺序拼接，**越靠后优先级越高**（与 Claude Code 一致）。

每层内容包裹作用域标记：

```markdown
<!-- SAGE-CONTEXT level="root" project="cfd-research" -->
这是 CFD 计算项目。所有算例遵循 OpenFOAM 目录约定。

<!-- SAGE-CONTEXT level="project" project="CFD" -->
CFD 子项目：算例统一放在 CFD/ 下，每个算例一个目录。

<!-- SAGE-CONTEXT level="project" project="case-001" -->
本算例：Ma=0.3, AoA=2°, 使用 k-omega SST 模型。
```

### 8.4 预算控制

| 约束 | 值 | 说明 |
|------|-----|------|
| 单文件上限 | 8000 字符 | 保持现有 |
| 每层保底 | 2000 字符 | 防止某层被完全挤掉 |
| 总预算 | 20000 字符 | 约 5k token |

**截断策略**：超出总预算时，**从最外层开始截断**。根项目的规则通常是宽泛约定，细节应该在子项目里写。若根层被截到只剩保底额度，模型仍能拿到定位信息。

### 8.5 与去重逻辑的关系

现有"按内容哈希去重"保留。父子层内容完全相同时只注入一次。但层级标记不同时仍会各自注入。

### 8.6 会话绑定无变化

`session_workspace_bindings` 表不动——子项目有真实路径，会话绑定子项目路径即可。上下文链是**派生**的，不需要存储。

## 9. 文件引用（快捷方式）

### 9.1 两个概念拆开

| 概念 | 问题 | 归属 |
|------|------|------|
| **虚拟路径** | 项目内 `CFD/case-001/wing.msh` 映射到哪个真实文件？ | 新增路径翻译层 |
| **访问授权** | 允许读 `/data/cases/001/wing.msh` 吗？ | 复用既有 `allowed_paths` 机制 |

### 9.2 虚拟路径翻译层

`backend/services/virtual_fs.py`

```python
def resolve_virtual(project_id: str, raw_path: str) -> tuple[Path, Optional[ReferenceHit]]:
    """把项目内路径翻译成真实路径。

    1. 命中已注册引用（rel_path 前缀匹配）→ 拼接 target_path + 剩余部分
    2. 未命中 → 原样返回（走既有 workspace 逻辑）
    """
```

翻译**发生在权限检查之前**。

### 9.3 授权层扩展（复用既有四层模型）

`BaseTool._enforce_workspace()` 插入**第 3 层**：

```
1. 路径在 workspace_root 内          → 放行   （既有）
2. 命中项目 allowed_paths 白名单      → 放行   （既有）
3. 命中已注册 file_reference          → 放行   （新增）
4. 命中当前调用 approved scope        → 放行   （既有）
5. 其余                              → 拒绝
```

### 9.4 只读授权（v1 保守设计）

`file_references` 引用**默认可读、不可写**：

- 读操作 → 第 3 层放行
- 写操作 → 第 3 层**不放行**（写入会污染外部算例目录）

写穿引用需显式授权（v1.1 再做），v1 不开放。避免改动 `_enforce_workspace` 签名。

### 9.5 symlink 的处理

扫描时遇到 symlink → 记为 `file_reference(kind='symlink')`。

**symlink 不递归**（防环、避免拉进整棵外部目录树），但**可以按需访问**——`CFD/case-001/wing.msh` 经第 3 层放行。

### 9.6 内部引用的创建

UI 创建（Windows 无需管理员权限）：

```
项目 → 文件引用 → 新增
  别名:      case-001
  项目内位置: CFD/case-001
  目标路径:   D:\cfd-cases\001
  类型:       目录
```

### 9.7 API

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/projects/{id}/references` | 列出引用 |
| `POST` | `/projects/{id}/references` | 新建内部引用 |
| `DELETE` | `/projects/{id}/references/{ref_id}` | 删除引用 |
| `POST` | `/projects/{id}/scan` | 强制重扫 |

### 9.8 审计

v1 走结构化日志（应用 logger，带 `project_id` / `ref_id` / `target` / `op` 字段），不新建表。

## 10. 前端改造

| 组件 | 现状 | 改造 |
|------|------|------|
| `Sidebar` 项目列表 | 扁平列表 | → **可折叠树** |
| 项目创建对话框 | 选路径 + 类型 | → 增加**模板选择器** |
| 项目详情面板 | 基础信息 | → 增加**「文件引用」Tab** |
| 文件树 | 物理目录 | → **叠加虚拟条目** |
| 项目列表项 | — | 子项目显示来源徽章 |

**树形视图是唯一的前端大改**。其余都是增量。

## 11. 实施分期

按依赖顺序，每期独立可交付：

| 期次 | 内容 | 依赖 | 交付价值 |
|------|------|------|----------|
| **P1 模板系统** | `project_template.py` + 内置模板泛化 + 项目创建选模板 | — | 能按自定义结构建项目 |
| **P2 目录扫描** | `workspace_scanner.py` + `parent_id` + 树 API | P1 | 侧边栏出现子项目 |
| **P3 前端树形** | 侧边栏树 + 模板选择器 + 来源徽章 | P2 | 层级可见可折叠 |
| **P4 上下文级联** | `project_context.py` 扩展为链式收集 | P2 | 子项目继承父级规则 |
| **P5 文件引用** | `virtual_fs.py` + 授权层第 3 层 + UI | P2 | 快捷方式可用 |

P1–P3 是"项目结构"主线，P4 是"上下文"主线，P5 是"文件"主线。三条线可并行，但建议按序落地。

## 12. 现有资产复用清单

| 现有资产 | 复用方式 |
|----------|----------|
| `ARCHETYPE_BLUEPRINTS` | 泛化为内置模板 |
| `scaffold_project_archetype()` | 改调通用脚手架 |
| `validate_workspace()` | 保持不变 |
| `allowed_paths.py` | 第 2 层授权，**不动** |
| `_enforce_workspace()` | 只加第 3 层 |
| `project_context.py` | 扩展为链式 |
| `session_workspace_bindings` | 不动 |

## 13. 测试策略

| 层级 | 内容 | 重点 |
|------|------|------|
| Backend 单元 | 模板加载/校验、扫描算法、虚拟路径翻译、级联拼接、引用 CRUD | 覆盖所有分支 |
| 安全专项 | 路径逃逸（`..`、兄弟前缀、symlink 链）、读写授权边界、symlink 环 | 必跑 |
| 契约测试 | `/projects/{id}/tree`、`/projects/{id}/references` API | 前后端对齐 |
| 前端测试 | 树形视图折叠/展开、模板选择器、引用管理 CRUD | 关键交互路径 |
| 集成测试 | 注册项目 → 扫描 → 子项目自动识别 → 上下文级联 → 文件读取 | 端到端 |

## 14. 双分支适配

新增模块须 main (Py 3.10 + pydantic v2) 和 release/win7 (Py 3.8 + pydantic v1) 双分支可用：

| 差异点 | 处理方式 |
|-------|----------|
| 类型注解 | 新模块用 `from __future__ import annotations` + `Optional/List` |
| pydantic schema | 用既有 shim（`conlist` 参数名已有兜底） |
| pathlib | 仅用 `Path` 稳定 API |

**新增模块清单**（都需双分支移植）：
- `backend/services/project_template.py`
- `backend/services/workspace_scanner.py`
- `backend/services/virtual_fs.py`
- `backend/office/allowed_paths.py` 第 3 层扩展
- 前端：`ProjectTree.tsx`、`TemplatePicker.tsx`、`ReferenceManager.tsx`

## 15. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| 扫描拖慢大项目打开 | 中 | `DEFAULT_EXCLUDES` + `MAX_ENTRIES_PER_DIR` + 深度限制 6 |
| 虚拟路径翻译误判 | 高 | 前缀匹配必须精确到路径边界（用 `PurePath.relative_to`） |
| 引用目标被删除 | 低 | 返回清晰错误「引用目标不存在，请更新或删除引用」 |
| 上下文级联预算超 20000 字符 | 中 | 从最外层截断 + 每层保底 2000 |
| 模板变量引入代码注入 | 低 | 模板变量白名单，无表达式引擎 |
| 树形视图性能 | 低 | 默认折叠 + 懒加载深层 |

## 16. 不在 v1 范围（YAGNI）

- ❌ 跨项目对比/聚合
- ❌ 模板可视化编辑器
- ❌ 文件写穿引用
- ❌ 文件监听自动扫描
- ❌ 引用审计表
- ❌ 模板版本冲突处理
- ❌ 跨分支同步策略（单独规划）

## 17. 关键文件清单（预计新增/修改）

### 新增

```
backend/services/project_template.py     # 模板系统
backend/services/workspace_scanner.py    # 目录扫描
backend/services/virtual_fs.py           # 虚拟路径翻译
backend/tests/unit/test_project_template.py
backend/tests/unit/test_workspace_scanner.py
backend/tests/unit/test_virtual_fs.py
backend/tests/unit/test_project_context_cascade.py
src/components/projects/ProjectTree.tsx
src/components/projects/TemplatePicker.tsx
src/components/projects/ReferenceManager.tsx
src/components/projects/__tests__/ProjectTree.test.tsx
src/components/projects/__tests__/TemplatePicker.test.tsx
```

### 修改

```
backend/data/database.py                 # projects 表 + file_references 表迁移
backend/data/project_repo.py             # Project dataclass 增加 parent_id / discovery_source
backend/api/project_routes.py            # /projects/{id}/tree + /references
backend/api/project_schemas.py           # ProjectResponse 增加字段
backend/tools/base.py                    # _enforce_workspace 加第 3 层
backend/chat/project_context.py          # 上下文链式收集
backend/services/project_archetype_scaffold.py  # 泛化入口
src/components/Sidebar.tsx               # 树形视图
src/components/projects/ProjectPicker.tsx # 模板选择器
src/components/projects/ProjectDetails.tsx # 引用 Tab
```

---

## 附录 A：与既有 allowed_paths 机制的关系

`allowed_paths` 是**用户配置的路径白名单规则**（类 .gitignore 语法，如 `~/Documents/**`），用于允许访问工作区外的特定目录。粒度粗（glob 规则）。

`file_references` 是**项目级别的快捷方式记录**，粒度精确（一个引用对应一个目标）。

两者互补：
- `allowed_paths` 适合「我想让 AI 读 ~/Documents 下的任何东西」
- `file_references` 适合「这个特定路径 `CFD/case-001` 指向 `/data/cases/001`」

第 3 层授权检查的是引用，不替换第 2 层。

## 附录 B：CFD 场景映射（仅作理解参考）

| 用户需求 | 本设计实现 |
|----------|-----------|
| 「文档/模型/网格/CFD」四层目录 | 自定义模板定义 4 个 directory |
| 大文件（网格/结果）快捷方式 | 文件引用（symlink 或内部引用） |
| 嵌套项目管理（总体 → 子任务） | 目录遍历 + 上下文继承 |
| 算例参数对比 | **不在 v1 范围**（YAGNI） |

## 附录 C：决策记录（ADR）

### ADR-1：为什么嵌套模型选「目录遍历」而非「parent_id 显式父子」

- 用户的 CFD 场景层级已经体现在目录结构里，不需要额外的「虚拟分组」
- 目录遍历更简单，不改数据模型核心，复用现有 SAGE.md 机制
- 与 Claude Code 验证过的模式一致
- `parent_id` 作为派生缓存保留，便于 UI 树查询

### ADR-2：为什么模板不进数据库

- 模板要能 git 管理、能随项目迁移、能被团队共享
- 放进数据库就锁死在本地应用里，违反文件系统优先原则

### ADR-3：为什么引用默认只读

- 外部算例目录被写穿的风险大于收益
- CFD 场景 AI 只需要读取大网格/结果，不需要写入
- 避免改动 `_enforce_workspace` 签名和所有写工具
- v1.1 再考虑显式写授权
