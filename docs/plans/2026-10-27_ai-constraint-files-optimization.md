# Sage 约束文件体系调研与优化方案

> 创建日期：2026-10-27
> 状态：G1 已落地（main #2593 / win7 #2599），G2/G3/G4 待推进
> 优先级：HIGH
> 范围：Sage 作为 AI 应用产品，为最终用户提供"配置 LLM 行为"的约束文件机制

---

## 一、结论先行

**Sage 已经具备一套完整且成熟的约束文件体系**，与 Claude Code / Cursor 高度对标，核心能力（全局层、项目层、目录层向上发现、结构化约束、上下文预算、可视化）全部已实现。

真正的差距**不是功能缺失**，而是**三处体验断点**：

| # | 差距 | 现状 | 主流做法 |
|---|------|------|---------|
| **G1** | **全局层无 UI 入口** | `~/.sage/SAGE.md` 后端已实现，但设置界面无任何入口，用户必须知道路径、手动建文件 | Cursor 有 User Rules 面板；Copilot 有 `customInstructions` 设置项 |
| **G2** | **无规则目录（`rules/`）支持** | 只支持单文件 `SAGE.md`/`CLAUDE.md`/`AGENTS.md` | Cursor 支持 `.cursor/rules/*.mdc` 按主题分文件 + Auto/Manual 附加类型 |
| **G3** | **约束规则无法"文件化"共享** | `project_constraints` 存 SQLite，团队无法通过 git 共享；`ConstraintManager` 只支持 Markdown **导出**（单向），不支持导入 | Claude Code / Cursor / Copilot 全部是"文件即真相"，天然可 git 共享 |

---

## 二、现状盘点：五层上下文注入管线

代码依据 `backend/chat/project_context.py` + `backend/memory/{user,project}_profile.py` + `backend/chat/project_context.py:481` `build_constraints_block`。

```
┌─ L0  base_system ───────────────────────────────────────────┐
│  头部 system prompt（应用安全规则，最高优先级）              │
├─ L1  用户全局 ────────────────────────────────────────────────┤
│  ~/.sage/SAGE.md                        ← 后端已实现          │
│  UserProfileStore 快照（1400 字符上限）   ← 已实现            │
├─ L2  目录树约定（向上发现，外层→内层）────────────────────────┤
│  <root>/SAGE.md > CLAUDE.md > AGENTS.md   ← 已实现           │
│  逐级向上直到文件系统根，祖先在前；单文件 8KB / 总量 16KB     │
├─ L3  项目结构化 ──────────────────────────────────────────────┤
│  项目元数据块（description + instructions）  ← 已实现          │
│  project_constraints 表（按 priority DESC）  ← 已实现          │
│    └ 内置 4 套预设：python_default / security_basic /         │
│      academic_writing / document_format                      │
│  ProjectProfileStore 快照（1000 字符上限）  ← 已实现          │
├─ L4  会话 / 动态 ─────────────────────────────────────────────┤
│  Session Rules（会话级权限覆盖）              ← 已实现         │
│  记忆召回 / 技能清单 / 资料 / 附件 / 环境     ← 已实现         │
└───────────────────────────────────────────────────────────────┘
```

### 关键实现细节（值得肯定的部分）

| 机制 | 实现位置 | 说明 |
|------|---------|------|
| 符号链接越界防护 | `project_context.py:172-179` | 拒绝 `SAGE.md → ~/.ssh/id_rsa`，解析后真实路径须仍在扫描目录内 |
| 内容哈希去重 | `project_context.py:120-123` | 同内容文件只注入一次 |
| 字符预算截断 | `PER_FILE_CHAR_CAP=8_000` / `TOTAL_CHAR_CAP=16_000`（模块级硬编码，无 UI/环境变量入口） | 每文件 + 总量双重保护 |
| 冻结快照（prefix cache） | `user_profile.py:248` / `project_profile.py:241` | 写入不刷新快照，保 prefix cache 命中率 |
| 上下文预算分配 | `backend/chat/context_budget.py` | 统一预算管理 |
| 上下文可视化 | `src/widgets/chat/ContextMeter.tsx` | 展示各来源 token 占比 |
| 路径匹配约束 | `project_context.py:434` `extract_active_files_from_text` | 从用户消息提取文件路径，动态匹配 `trigger_pattern` |
| Hooks 信任门控 | `.sage/hooks.json` 需显式授权 | 项目级 hooks 不自动执行 |

---

## 三、与主流 AI 应用对比

| 能力 | Claude Code | Cursor | GitHub Copilot | **Sage** |
|------|-------------|--------|----------------|----------|
| 全局指令文件 | `~/.claude/CLAUDE.md` | User Rules（设置面板） | VS Code `customInstructions` | ✅ `~/.sage/SAGE.md`（**无 UI**） |
| 全局指令 UI | ❌ 纯文件 | ✅ 面板 | ✅ 设置项 | ❌ **缺口 G1** |
| 项目指令文件 | `.claude/CLAUDE.md` | `.cursorrules` | `.github/copilot-instructions.md` | ✅ `SAGE.md`/`CLAUDE.md`/`AGENTS.md` |
| 目录级规则 | `.claude/rules/*.md` | `.cursor/rules/*.mdc` | ❌ | ✅ 向上发现（等价） |
| 规则目录（分文件） | ✅ | ✅ | ❌ | ❌ **缺口 G2** |
| 规则附加类型 | ❌ | ✅ Always/Auto/Manual | ❌ | ⚠️ 部分（`trigger_pattern`） |
| 规则结构化存储 | ❌ 纯 Markdown | ❌ | ❌ | ✅ **Sage 独有优势** |
| 规则 UI 管理 | ❌ | ✅ | ❌ | ✅ **Sage 独有优势** |
| 路径触发规则 | ❌ | ✅ globs | ❌ | ✅ **Sage 独有优势** |
| git 团队共享 | ✅ | ✅ | ✅ | ⚠️ 仅 L2 文件层，结构化约束不行 **缺口 G3** |
| 上下文预算可视化 | ❌ | ⚠️ | ❌ | ✅ **Sage 独有优势** |
| 预设规则包 | ❌ | ❌ | ❌ | ✅ 4 套 + 领域包 **Sage 独有** |

**结论**：Sage 在**结构化程度、UI 友好度、路径触发、预算可视化**四个维度上**优于**主流工具；差距集中在 **UI 入口完整度** 和 **文件/结构化双向同步**。

---

## 四、优化方案

### 设计原则

1. **不推翻现有架构** —— 五层管线是资产，补缺口而非重写
2. **文件与结构化共存** —— 明确各自定位，双向同步
3. **UI 优先** —— 补齐 G1，让 90% 用户不必碰文件系统
4. **零破坏** —— 新增能力不改变现有注入顺序与截断行为

---

### G1：全局规则 UI 入口（补齐 `~/.sage/SAGE.md` 的可达性）

> ✅ **已落地**（2026-10-27，main PR #2593 / win7 PR #2599）。实现与下列方案一致：
> 后端 `backend/api/global_rules_routes.py`（GET/PUT/DELETE `/api/v1/settings/global-rules` + `/templates`），
> 前端 `src/pages/settings/GlobalRulesTab.tsx`。文档见 `docs/technical/102-global-rules.md`、`docs/user-manual/23-global-rules.md`。

**现状**：后端 `_user_level_entries()` 已读取 `~/.sage/SAGE.md`，但设置页无入口，用户根本不知道它存在。

**方案**：在设置页新增"全局规则"Tab。

```
设置
├── 通用
├── 模型
├── 技能          ← 已有，缺省路径 ~/.sage/skills
├── 全局规则      ← 新增
└── ...
```

**交互设计**：

| 元素 | 行为 |
|------|------|
| 主编辑区 | Markdown textarea，实时预览注入后的 system prompt 片段 |
| 保存 | 写入 `~/.sage/SAGE.md`（原子写：临时文件 + rename） |
| 状态指示 | 显示文件路径、大小、最后修改时间、是否被裁剪（超 8KB 提示） |
| 一键模板 | 提供"中文输出规范""代码风格""安全规范"三个起步模板 |
| 作用域说明 | 文案明示："此处规则对**所有项目**生效；项目专属规则请写在项目根 `SAGE.md`" |

**后端接口**（新增）：

```
GET    /api/v1/settings/global-rules           → { content, path, size, mtime, truncated }
PUT    /api/v1/settings/global-rules           → 写回 ~/.sage/SAGE.md
DELETE /api/v1/settings/global-rules           → 删除
GET    /api/v1/settings/global-rules/templates → 起步模板列表
```

**安全约束**（必须）：
- 路径必须是 `~/.sage/SAGE.md`，不接受客户端传参（防路径穿越）
- 写入前过 `backend.memory.safety.get_scanner().scan_write()`，命中威胁模式拒绝
- 原子写（tmp + `os.replace`），避免半写坏文件
- 文件层不走 profile 冻结快照缓存，语义独立

---

### G2：规则目录支持（`.sage/rules/*.md`）

**现状**：`_CANDIDATES` 只有三个固定文件名。想按主题拆 10 个规则文件，只能全部堆进一个 `SAGE.md`。

**方案**：扩展 `discover_project_context`，支持规则目录。

```
<project>/
├── SAGE.md                    # 核心约定（单文件，仍优先）
└── .sage/
    ├── rules/                 # 新增：按主题分文件
    │   ├── code-style.md      # → category = code-style
    │   ├── testing.md
    │   ├── security.md
    │   └── frontend.md
    └── hooks.json
```

**规则发现顺序**（追加在现有三候选之后，优先级最低）：

1. `~/.sage/SAGE.md`（全局）
2. 逐级向上 `SAGE.md` > `CLAUDE.md` > `AGENTS.md`（目录树）
3. 逐级向上 `.sage/rules/*.md`（新增）
4. `project_constraints` 表（结构化，priority DESC）

**每个 `rules/*.md` 的语义**：

| 约定 | 说明 |
|------|------|
| 文件名 = category | `code-style.md` → category `code-style`，与 `project_constraints.category` 对齐，**可与结构化规则互相覆盖** |
| 文件内 `##` 标题 = 分组 | 直接作为 prompt 文本段 |
| 顶层 frontmatter 可选 | 支持 `trigger` / `priority` / `enabled` 字段（YAML frontmatter，与 Obsidian/Cursor 生态一致） |
| 计入同一套 8KB/16KB 预算 | 不绕过现有截断保护 |

**frontmatter 规格**（可选段）：

```markdown
---
trigger: "**/*.py, **/*.ts"   # 可选：路径触发
priority: high               # 可选：high/medium/low
enabled: true                # 可选：开关
---

# 代码风格

- 函数长度不超过 50 行
- 文件长度不超过 800 行
```

**向后兼容**：不写 frontmatter 的纯 Markdown 文件直接全文注入，零配置。

---

### G3：约束规则双向同步（文件 ↔ 结构化）

**现状**：`ConstraintManager` 有 Markdown 导出（单向复制到剪贴板），但：
- 无法从 `.sage/rules/*.md` 导入到 `project_constraints` 表
- 数据库规则无法批量回写成项目文件供团队共享

**方案**：加一个"文件 ↔ 数据库"同步面板，三种模式。

| 模式 | 行为 | 使用场景 |
|------|------|---------|
| **仅文件** | 只读 `.sage/rules/`，不写库 | 团队用 git 管理规则，成员本地不落库 |
| **仅数据库** | 只用 UI + `project_constraints` | 单机个人使用（现状） |
| **双向同步** | 导入时写入库；库变更时回写文件 | 混合场景，**需明确冲突策略** |

**冲突策略**（双向同步必须定义，否则会打架）：

```
同名同 category 的规则：
  - 内容一致 → 跳过（幂等）
  - 内容不同 → 提示用户选择，**默认以文件为准**（文件是团队契约）
  - 库有文件无 → 标记"仅库存在"，可选择回写文件
  - 文件有库无 → 标记"仅文件存在"，可选择导入库
```

**回写文件的安全约束**：
- 回写前弹确认，展示 diff（新增/修改/删除三段）
- 写前备份原文件到 `~/.sage/backups/rules-<timestamp>.md`
- 永不删除用户手写的、库中不存在的规则（只标记，不自动清）
- 回写后提示"建议提交到 git"

---

### G4：上下文预算可配置（补充能力，非对标差距）

**现状**：`PER_FILE_CHAR_CAP = 8_000` / `TOTAL_CHAR_CAP = 16_000` 是 `backend/chat/project_context.py:31-32` 的模块级常量。`discover_project_context(workspace_root)` 不接收预算参数，模块不读 settings / 环境变量，设置页也无对应项——用户只能改代码。

> 注：`docs/mcp-sage-project-management-organization-plan-20261010.md` 多处写"总量 24KB"，与代码实际的 16KB 不符，以代码为准。

**方案**：把两个值提升为设置项，走既有 `SettingsRepository` 白名单链路。

| 设置键 | 标签 | 默认 | 范围 | 生效 |
|--------|------|------|------|------|
| `context_file_chars` | 单个指令文件上限 | 8000 | 2000–16000 | `next-request` |
| `context_total_chars` | 指令文件总预算 | 16000 | 4000–32000 | `next-request` |

**实现要点**：

1. `discover_project_context(workspace_root, per_file_cap=None, total_cap=None)` —— 新增可选参数，`None` 时回落模块常量。现有两个调用方（`legacy_routes.py:1040` / `project_workspace_inspector.py:72`）行为不变，由调用侧按需传入设置值。
2. 服务端二次校验：`per_file_cap <= total_cap`，越界或非法值回落默认并记 warning，**不抛异常**（延续"发现永不抛"的既有契约）。
3. 前端设置页新增两项，放在"高级"分组，附说明文案"增大预算会稀释缓存命中率"。
4. 严格联动：`per_file_cap > total_cap` 时前端即时禁用保存。

**必须接受的副作用**：

- 预算 → 注入文本长度 → system prompt 前缀。改值必然 **使 prefix cache 失效**，下一轮首 token 延迟上升。因此只做"保存后下一轮生效"，不做实时拖动；上限收紧到 32KB，避免用户用缓存命中率换规则容量。
- 不做按项目覆盖（`project_constraints` 里再存一份预算）——双层配置会显著增加解释成本，且当前无真实诉求。

---

### 建议的补齐顺序

| 阶段 | 内容 | 理由 |
|------|------|------|
| **P0** ✅ | G1 全局规则 UI | 成本最低、用户感知最强；后端已就绪，只差 UI + 2 个接口 **（已完成，main #2593 / win7 #2599）** |
| **P1** | G2 规则目录 + G4 可配置预算 | G2 会显著增加规则总量，"预算不够用"的诉求到那时才真实出现，两者同一批做避免先做无用功；G4 复用现有 settings 链路，成本低 |
| **P2** | G3 双向同步 | 涉及冲突策略与回写安全，工程量最大；P1 落地后再评估 |

---

## 五、风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 新增注入源打乱现有 prompt 前缀，损伤 prefix cache | **HIGH** | 规则目录注入**追加在现有三候选之后**，不改动既有顺序；变更后需 A/B 对比首 token 延迟 |
| `~/.sage/SAGE.md` 写入引入路径穿越 / 任意文件覆盖 | **HIGH** | 路径服务端硬编码；不接受客户端路径参数；原子写；复用 `safety.get_scanner()` |
| 双向同步导致规则被误删 | **MEDIUM** | 默认"文件为准"；回写前备份；不自动删除仅文件存在的规则 |
| 规则目录文件过多撑爆 16KB 预算 | **MEDIUM** | 复用现有 `PER_FILE_CHAR_CAP` / `TOTAL_CHAR_CAP`；预算耗尽时按"外层优先"截断并记录 warning |
| G4 预算调大导致 prompt 膨胀、缓存命中率下降 | **MEDIUM** | 总量硬上限 32KB；单文件 ≤ 总量强校验；设置页明示"改值会使缓存失效"；只做下一轮生效 |
| 符号链接越界 | **MEDIUM** | 复用 `project_context.py:172` 已有防护，规则目录同样适用 |
| 文档滞后导致用户不知道新能力 | **LOW** | 同步更新 `docs/user-manual/`，并在设置页内联说明 |

---

## 六、待确认决策点

- [ ] 是否按 P0 → P1（G2+G4）→ P2 顺序推进？
- [ ] G1 的全局规则是否需要**多文件**（`~/.sage/rules/`）还是先做单文件 `SAGE.md`？
- [ ] G3 双向同步的默认冲突策略确认："文件优先"是否符合预期？
- [ ] 是否需要"按项目类型自动生成 `.sage/rules/` 骨架"（类似现有项目脚手架生成 `SAGE.md`）？
- [ ] G4 的默认值（8KB/16KB）与上限（16KB/32KB）是否合适？是否需要暴露在"高级"以外的位置？

---

## 参考

- [Cursor Rules](https://cursor.com/docs/rules) —— 规则目录 + Always/Auto/Manual 类型
- [Claude Code CLAUDE.md 指南](https://www.heyuan110.com/posts/ai/2026-02-28-claude-code-claudemd-guide/) —— 三层继承
- [GitHub Copilot Custom Instructions](https://docs.github.com/copilot/customizing-copilot/adding-repository-custom-instructions-for-github-copilot) —— 仓库级 + 用户级
- [Aider 配置](https://aider.chat/docs/config/aider_conf.html) —— YAML + CONVENTIONS.md
- [awesome-cursorrules](https://github.com/PatrickJS/awesome-cursorrules) —— 生产级规则样例

## 相关内部文档

- `backend/chat/project_context.py` —— 指令文件发现与渲染
- `backend/chat/context_sources.py` —— 注入来源明细与 token 估算
- `backend/chat/context_budget.py` —— 上下文预算
- `backend/memory/user_profile.py` / `project_profile.py` —— 冻结快照画像
- `docs/mcp-sage-project-management-organization-plan-20261010.md` —— 五层管线原始设计
- `src/features/project-type/ConstraintManager.tsx` —— 约束规则 UI
- `src/widgets/memory/UserProfileCard.tsx` —— 用户画像 UI
