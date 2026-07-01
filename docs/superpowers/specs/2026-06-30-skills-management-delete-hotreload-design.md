# Skills 管理: 删除 + 热重载设计

> **状态**: Design (待用户审核)
> **日期**: 2026-06-30
> **作者**: Claude (brainstorming)
> **目标分支**: main
> **影响模块**: `backend/skills/skill_md/` + `src/pages/Skills.tsx` + `electron/commands.ts`

## 背景与目标

### 背景

Sage 项目的技能加载机制在 PR #84-#89 已经达到 **agentskills.io 规范** 合规，但**只读侧完善，写侧还缺**：

- ✅ `list_skills` / `toggle_skill` / `execute_skill` / `list_slash_commands`（PR #85, #89）
- ✅ PR #90 加了前端 "刷新" 按钮
- ❌ **完全无删除** 任何 SKILL.md 技能（用户手动编辑 SAGE_SKILLS_DIR 也无 UI 反馈）
- ❌ **完全无热重载**（必须点 Refresh 按钮才看得到 SKILL.md 文件变更）

用户当前在 `/skills` 页面可以 **看 + toggle** 用户技能，但 **删不了、改了没自动同步**。一旦他们在 SAGE_SKILLS_DIR 下重命名/删除/新增 SKILL.md 目录，UI 只在手动点刷新后才会反映。

### 目标

1. 用户在 Skills 页面**删一个 SKILL.md 技能**（物理 unlink 该 skill_name/ 目录）
2. SAGE_SKILLS_DIR 下 SKILL.md 文件**改动后 10s 内**自动反映到 UI
3. **不动 builtin 技能**（仅 SKILL.md 用户技能）
4. **0 新依赖**（不引入 watchdog / chokidar / websockets）

### 非目标

- ❌ 不做 Create / Edit SKILL.md（用户已确认不在本轮）
- ❌ 不做 Folder Picker（用户已确认不在本轮）
- ❌ 不实现秒级实时（10s polling 是 "够自动"，避免 WebSocket/依赖成本）

## 用户已确认的设计决策

| 决策点 | 选择 |
|---|---|
| 管理对象 | **仅 SKILL.md 用户技能**（不动 builtin） |
| "删除" 语义 | **物理 unlink** 整个 `<base_dir>/<skill_name>/` 目录 |
| 删除粒度 | `shutil.rmtree(base_dir / skill_name)`（同目录下的 assets/ 也一起去） |
| 范围（除删外） | **Hot-reload 自动刷新列表**（无 Create/Edit/Picker） |
| 架构 | **方案 A：后端 add `delete_skill` + 前端 10s polling toggle** |

## 设计

### 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│  React Renderer (Skills.tsx)                                         │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐      │
│  │  Refresh 按钮 │  │ Delete 按钮    │  │ 自动刷新 (10s) toggle│     │
│  └──────┬───────┘  └───────┬────────┘  └─────────┬──────────┘      │
│         │ click           │ click              │ tick              │
└─────────┼─────────────────┼────────────────────┼────────────────────┘
          │                 │                    │
          ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Electron main                                                       │
│  COMMAND_ROUTES: delete_skill → POST /api/v1/skills/{name}/delete   │
│                  list_skills  → GET  /api/v1/skills                  │
│  + new IPC: skills-skill-deleted (emit to renderer?) → not needed in A│
└─────────────────────────────────────────────────────────────────────┘
          │ HTTP                                       ▲
          ▼                                            │ skillsApi.list()
┌─────────────────────────────────────────────────────────────────────┐  polling
│  FastAPI Backend (port 8765)                                         │
│  legacy_routes.py:                                                   │
│    POST /api/v1/skills/{name}/delete  → SkillMdDeleter.delete(name) │
│    GET  /api/v1/skills                → list_skills_extended()       │
│                                                                      │
│  NEW: backend/skills/skill_md/delete.py                              │
│    SkillMdDeleter.delete(name) →                                     │
│      1. resolve base_dir from SAGE_SKILLS_DIR/cwd/~/.sage/skills     │
│      2. safety: name 不允许 builtin                                  │
│      3. shutil.rmtree(base_dir / name) if exists                     │
│      4. registry.unregister(name)                                   │
│      5. return {deleted: true, name}                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 组件 / 文件改动

| 文件 | 改动 | 行数估计 |
|---|---|---|
| `backend/skills/skill_md/delete.py` | **新建**：`SkillMdDeleter.delete(name) -> DeleteResult` | ~80 |
| `backend/skills/skill_md/__init__.py` | +1 行（导出 `SkillMdDeleter`） | +1 |
| `backend/api/legacy_routes.py` | +1 endpoint `POST /api/v1/skills/{name}/delete` | ~30 |
| `backend/tests/integration/test_skill_delete.py` | **新建**：success / builtin-block / missing / wrong-name / filesystem-error | ~150 |
| `electron/commands.ts` | +1 entry `delete_skill: { method: 'POST', path: (a) => `/api/v1/skills/${a.name}/delete` }` | +4 |
| `src/shared/api/skillsApi.ts` | +1 method `delete(name): Promise<DeleteSkillResult>` | +10 |
| `src/shared/api/types.ts` | +1 type `DeleteSkillResult { deleted: boolean; name: string }` | +5 |
| `src/pages/Skills.tsx` | + delete 按钮 + auto-refresh toggle + setInterval | +60 |
| `src/widgets/skills/SkillList.tsx` + `SkillCard.tsx` | 接受 `onDelete` 回调 + 红色 delete 按钮（hover 显示） | +40 |
| `src/pages/__tests__/Skills.test.tsx` | +4 测试：delete 调用、auto-refresh 启用时 setInterval、refresh 收到结果、auto-refresh 关闭清理 | +120 |

**总计**: ~500 行净增（其中 ~270 是新测试，符合 80% coverage 目标）

### 数据流

#### 流 1：用户删除 SKILL.md 技能

```
[User clicks Delete icon on SkillCard]
  ↓
[SkillCard.onDelete(name)]
  ↓
window.confirm("确定删除 'web-search'？此操作不可撤销。")
  ↓ (user confirms)
[Skills.handleDelete(name)]
  ↓ optimistic UI: 立即从 list 里 filter 掉
[skillsApi.delete(name)]  → IPC delete_skill(name)
  ↓
[FastAPI POST /api/v1/skills/{name}/delete]
  ↓
[SkillMdDeleter.delete(name)]
  ├─ name == builtin → 400 "无法删除内置技能"
  ├─ base_dir 不存在 → 404 "技能不存在"
  ├─ shutil.rmtree 失败 → 500 + 保留原状
  └─ registry.unregister(name) → 200 {deleted: true}
  ↓
[响应回到 renderer]
  ├─ 200 → 移除 toast 成功 + list 已跳过该项（optimistic）
  ├─ 400/500 → 恢复原 list + toast 错误
```

#### 流 2：用户切换 "自动刷新" 启用

```
[User toggles "自动刷新 (10s)" ON in Skills page]
  ↓
[useState autoRefresh = true]
  ↓
[useEffect 监听 autoRefresh]
  ├─ ON → setInterval(() => loadSkills(), 10000)
  ├─ OFF → clearInterval, refetch 一次作为最终态
  ↓
[setInterval fires 每 10s]
  ↓
[loadSkills() 复用 PR #90 的 refresh 路径]
  ├─ loading = true → 按钮 disabled + 旋转
  ├─ success → setSkills(data), 列表自动更新（如有新增 SKILL.md）
  └─ error → toast "自动刷新失败"，但 toggle 不关
```

#### 流 3：SAGE_SKILLS_DIR 内手工改 SKILL.md

```
[User 在终端 vim ~/.sage/skills/web-search/SKILL.md]
  ↓
[最多 10s 后，自动刷新触发（流 2）]
  ↓
[list_skills_extended() 重新从磁盘读 + 重新 parse]
  ├─ 文件名（name）没变 → 列表里有该 skill，**内容已更新**
  ├─ 删了目录 → 该 skill 从 list 里消失
  └─ 新增目录 → 新 skill 出现在 list
```

注意：10s 内用户需等待。**用户在 toggle 关闭时还能点 Refresh 按钮立即刷新**（PR #90 已实现）。

### 错误处理

| 错误场景 | 后端响应 | 前端 UI |
|---|---|---|
| 试图删 builtin | `400 {error: "builtin skill cannot be deleted"}` | toast 错误 + 不动 list |
| 试图删不存在的 skill | `404 {error: "skill not found in registry"}` | toast 错误 + 自动刷新拉一次以同步 |
| `shutil.rmtree` 失败（权限） | `500 {error: "filesystem error: ..."}` | toast 错误 + 整页 reload button |
| 自动刷新 IPC 失败 | (网络失败) | toast "自动刷新失败"，**不**关闭 toggle |
| 用户在列表窗点 Delete 后取消 confirm | — | 啥都不做（标准浏览器 confirm） |
| `SAGE_SKILLS_DIR` 被设到非法路径 | `400 {error: "skills dir not accessible"}` | toast 错误 |

### 安全 / 路径遍历防御

- **name 校验**：必须 `^[a-z0-9-]{1,64}$`（已在 PR #84 加），不匹配 → `400`
- **builtin 白名单**：`delete(name)` 之前查 `registry.exists(name) and builtin` → 拒绝
- **base_dir 在 `SAGE_SKILLS_DIR` 之下**：用 `Path.resolve(SAGE_SKILLS_DIR) in parents of target` 验证
- **删除审计**：`logger.warning("Deleted SKILL.md skill: %s (base_dir=%s)", name, base_dir)` 给运维/审计排查

### 测试计划 (TDD)

**新建 `backend/tests/integration/test_skill_delete.py`**:

1. `test_delete_skill_md_succeeds` — 创建临时 SAGE_SKILLS_DIR + 合法 SKILL.md，调 delete，成功，目录不存在
2. `test_delete_builtin_blocked` — 试图 delete `coder`（builtin），返回 400，目录不变
3. `test_delete_missing_skill_404` — 不存在的 name，404
4. `test_delete_invalid_name_400` — name 含 `../`，400
5. `test_delete_outside_skill_dir_400` — base_dir 被 `..` 跑出 SAGE_SKILLS_DIR，400
6. `test_delete_triggers_registry_unregister` — delete 后 list_skills_extended 不含该项

**扩展 `src/pages/__tests__/Skills.test.tsx`**:

7. `clicks delete button → confirm → calls skillsApi.delete` — happy path
8. `cancels confirm → does not call delete` — confirm cancel
9. `delete fails → keeps original list + shows error` — error rollback
10. `auto refresh toggle on → fires loadSkills every 10s` — setInterval（用 vi.useFakeTimers）
11. `auto refresh toggle off → stops setInterval` — cleanup

**E2E**（非阻塞，可后续做）：

- 启动应用 + SAGE_SKILLS_DIR=/tmp/skills → /skills 页面 → 看到 skillA
- 终端 `rm -rf /tmp/skills/skillA`
- 等 10s → list 自动移除 skillA

### 文件清单（项目内 README 文档更新）

- `docs/technical/24-skills-system.md`：加 §"管理：删除 + 热重载" 一节
- `docs/user-manual/04-skills-page.md`（如有）：加 "删除技能" + "自动刷新" 用户操作说明

### 部署影响

| 改动类型 | 影响 |
|---|---|
| 后端 API 新增 | 1 个 POST endpoint，向后兼容（旧客户端不调不会有影响） |
| IPC route 新增 | 1 个，向后兼容 |
| 前端 API 新增 | 1 个 method，向后兼容 |
| 前端 UI 改动 | 新增按钮 + toggle，不影响现有功能 |
| 数据库 schema | **无** |
| 环境变量 | **无** |
| 依赖 | **无新增** |

### 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 用户误删（无 undo） | 中 | 高 | confirm dialog 文字强调"不可撤销"；MVP 不做 undo（YAGNI） |
| 自动刷新把 sage 自身内存吃爆 | 低 | 中 | 10s 间隔 + 只是 list() 一次（轻量），后端无副作用 |
| `shutil.rmtree` 删错目录 | **低** | **高** | name 校验 + builtin 拦截 + base_dir 必须在 SAGE_SKILLS_DIR 之下 |
| 10s polling 在低配机器上卡 | 低 | 中 | toggle 默认 OFF，让用户主动启用 |

## 交付里程碑

为避免单 PR 过大，**建议拆 2 个 PR**：

| PR | 范围 | 估时 |
|---|---|---|
| **PR-A: Skills 删除** | 后端 `SkillMdDeleter` + 1 IPC + 前端 delete 按钮 + 测试 | ~1.5 天 |
| **PR-B: 自动刷新 toggle** | 前端 useState + useEffect + setInterval + 测试 | ~0.5 天 |

PR-A 先合，**不**引入 toggle 后端依赖，可独立 review。
PR-B 接续 PR-A 的 setSkills 路径，**不**改后端。

## 关联

- PR #84 (agentskills.io spec conformance) — name 校验已加，删除用它
- PR #85 (Skill IPC routes) — delete_skill IPC 同样模式
- PR #90 (Skills page refresh button) — 自动刷新 toggle 复用 loadSkills 路径
- `docs/technical/24-skills-system.md` — 必更新章节
- `docs/user-manual/04-skills-page.md` — 加用户操作
