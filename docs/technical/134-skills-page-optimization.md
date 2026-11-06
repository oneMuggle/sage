# 技能页面优化 M1–M4

> 分支：`feat/skills-page-optimization`（切自 main `639ab4050`）
> 设计依据：`docs/plans/2026-11-06_skills-page-optimization.md`
> 编号说明：main 上 §133 由专家系统占用，本专题取 §134。

本次把技能页从「开发者管理面板」改造为主流 AI 应用式的技能库：分组浏览、紧凑列表、详情抽屉、来源徽章、可导出、可定位到磁盘，并修复默认运行模式下待审草稿恒为空的链路缺陷。

---

## 1. 里程碑总览

| 里程碑                         | 交付                                                                                                                                                                                                                   |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1 草稿链路修复 + 汉化 + 空态  | legacy `run_loop` `complex_turn` 入队 parity；`Pending Drafts` → 待审草稿；空态解释三种生成方式 + 「从最近会话生成」「扫描冷技能」CTA                                                                                |
| M2 技能页信息架构重构          | 三组可折叠（内置 / 推荐模板 / 我的）+ 紧凑列表默认 / 卡片切换；`SkillRow` / `SkillOriginBadge` / `SkillDetailDrawer`；页头统计 chips + 来源筛选 + 状态筛选；来源 `origin` 字段贯穿前后端                                |
| M3 存储可见性                  | `GET /skills/storage`、`GET /skills/{name}/location`（realpath 白名单 + 根内软链放行）；Electron `skills:open-directory` / `skills:show-in-folder`；设置页目录文案补注升级安全提示                                   |
| M4 导出                        | `GET /skills/{name}/export` 与 `GET /skills/export?scope=mine`（仅允许 SKILL.md 与白名单资源目录）；Electron `skills:export` + 保存对话框 + 在文件夹中显示                                                             |
| 提前完成 M5 部分               | `importer` 写盘时注入 `metadata.provenance=user-imported`，使来源枚举能区分「导入 / 生成 / 本地」                                                                                                                    |

---

## 2. 待审草稿恒为空的根因诊断

默认 `API_MODE=legacy`（`backend/main.py:1170`）。桌面端 Electron 启动后端时未覆盖该变量。`complex_turn` 入队逻辑此前仅存在于 hex `ChatService`（`backend/application/services/chat_service.py:442-490`）。在默认配置下 `review_events` / `skill_drafts` 两张表恒为空。

其余入口：`/learn` 手动触发、低成功率信号、手动「扫描冷技能」都可用，但用户通常不会主动走这些路径。

**修复**：在 legacy `SageAgent.run_loop` 的 DONE 分支按与 hex 相同阈值入队：

```
tool_calls_used ≥ 2
  且 _tools_used_names − {skill, skill_save, learn} ≠ ∅
  且 session_id 非空
→ enqueue trigger_type=complex_turn
  context.tool_call_count / threshold=4 / needs_screening = tool_calls_used < 4
```

`_tools_used_names` 在 `run_loop` 起始置空，于并行批次（`tool_calls_used += len(group_tcs)`）与串行单元素组（`tool_calls_used += 1`）两处收集工具名。异常一律 best-effort 静默降级，不阻塞 DONE 路径。

---

## 3. 来源枚举（origin）

### 3.1 后端

`InprocSkillAdapter.list_skills_extended` 新增 `origin` 字段（与既有 `source: builtin | skillmd` 并存，向后兼容）：

| origin      | 判定                                                                 |
| ----------- | -------------------------------------------------------------------- |
| `builtin`   | 非 `SkillMdSkill`（代码实现）                                        |
| `shipped`   | `doc.base_dir` 位于 `backend/skills/skill_md/shipped/` 下            |
| `generated` | `doc.metadata.provenance == "agent-created"`（草稿审批写入时已注入） |
| `imported`  | `doc.metadata.provenance == "user-imported"`（本次新增，见 §6）      |
| `user`      | 其余（历史技能 / 手工放置 / 兜底）                                   |

`_classify_origin` 在 `list_skills_extended` 内循环外一次性解析 shipped 目录的 realpath，避免每条技能重复 stat。`shipped` 判定使用 `pathlib` resolve + `parents` 包含性检查（py38 无 `is_relative_to`）。

### 3.2 前端

`src/shared/api/types/domainEntityTypes.ts` 的 `Skill` 接口新增 `origin?: 'builtin' | 'shipped' | 'generated' | 'imported' | 'user'`。`SkillList` 内 `resolveOrigin` 对旧后端/fixture 缺省值按 `source` 兜底。

`SkillOriginBadge` 使用 `skills_page.origin_*` i18n 键渲染中文（内置 / 模板 / AI 生成 / 已导入 / 本地），颜色随语义（muted / accent / primary / success / warning）。

---

## 4. 技能页信息架构

### 4.1 页面结构

```
技能页
├─ 工具条：刷新 / 重扫 / 导入文件 / 导入目录 / 打开目录 / 导出我的技能
├─ 统计 chips：技能总数 · 已启用 · 我的技能 · 使用次数
├─ 搜索框 + 来源筛选（全部/内置/模板/我的） + 状态筛选（全部/启用/停用/已归档）
├─ 视图切换：紧凑列表（默认） / 卡片视图
├─ 分组列表（<details open>）：
│   ├─ 内置技能（N）
│   ├─ 推荐模板（N）
│   └─ 我的技能（N）—— 行内含名称 · 徽章 · 📌 · 一行描述 · 使用次数 · hover 归档/删除按钮 · 开关
├─ 巡检建议折叠面板（既有）
└─ 右侧详情抽屉（点行触发）：
    描述 · 触发词 · 何时使用 · 正文预览 · 版本 · 管理动作（钉住/归档/历史/复制/删除/启用/在文件夹中显示/导出）
```

### 4.2 关键组件

| 组件                   | 职责                                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| `SkillRow`             | 紧凑行，`onToggle` / `onOpenDetails` / `onDelete` / `onArchive` / `onPin`。右键菜单收高频动作。    |
| `SkillOriginBadge`     | 来源徽章，缺省回落到 `user`。                                                                      |
| `SkillDetailDrawer`    | 右侧抽屉，`<aside>` + `bg-overlay` 模态背景，ESC 关闭，承载全部管理与详情动作。                    |
| `SkillList`            | 分组渲染；`viewMode='grid'` 时回落原有 `SkillCard` 网格。                                           |
| `SkillCard`            | 保持 API 兼容，仍作为 grid 视图单元；`SkillList` 紧凑模式不再使用它，但保留以兼容既有测试与外部导入。|

### 4.3 行内动作的可见性

行内仅在 hover 时显示归档与删除按钮（`opacity-0 group-hover:opacity-100`）。这保证测试里的 `getByRole('button', {name: /归档/})` 仍能匹配（元素存在，只是默认透明），也避免默认态视觉过载。

---

## 5. 存储可见性与导出

### 5.1 存储信息端点

`GET /skills/storage` 返回：

| 字段                  | 类型     | 含义                                                                |
| --------------------- | -------- | ------------------------------------------------------------------- |
| `writable_root`       | string   | 生效的可写技能根（env > preference > `~/.sage/skills`）             |
| `writable_source`     | enum     | `env` / `preference` / `default`                                    |
| `roots`               | array    | 每个 `discover_skill_md_dirs()` 结果的 `{path, writable}`           |
| `shipped_root`        | ?string  | 随包只读模板目录                                                    |
| `installed_app_dir`   | string   | 应用安装目录（`Path(__file__).resolve().parents[2]`）               |
| `writable_in_app_dir` | boolean  | 可写根是否落在安装目录内（前端据此显示升级风险警告）                |

`GET /skills/{name}/location` 返回 `{name, path}`。`path` 是 realpath，越界返回 403（`path_not_allowed`），内置或不存在返回 404（`skill_location_unavailable`）。

**软链放行**：用户常在 `~/.sage/skills` 下放软链管理外部技能目录（本机已有 `storage-analyzer -> /home/fz/project/khazix-skills/storage-analyzer` 先例）。`_is_under_any` 同时接受「realpath 在根内」与「未解析路径在根内」两种情况。

### 5.2 导出端点

`GET /skills/{name}/export` 与 `GET /skills/export?scope=mine` 返回 `application/zip`。

白名单规则：
- 根层只接受 `SKILL.md`
- 子目录只接受 `scripts/` `references/` `assets/` `templates/` 下的文件
- 跳过符号链接（即使位于白名单目录内）
- 跳过非文件条目

`builtin` 技能返回 404 `skill_not_exportable`（代码实现，无磁盘目录）。

zip 文件内 arcname 形如 `<skill-name>/SKILL.md`、`<skill-name>/scripts/run.py`。`Content-Disposition` 使用 `filename*=UTF-8''...` 避免中文技能名乱码。

### 5.3 Electron IPC

| Channel                 | 用途                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| `skills:open-directory` | 取 `/skills/storage` 的 `writable_root` → `shell.openPath`                                    |
| `skills:show-in-folder` | 取 `/skills/{name}/location` 的 `path` → realpath 与允许根再次校验 → `shell.showItemInFolder` |
| `skills:export`         | 后端生成 zip → 主进程弹保存对话框 → 写盘 → `showItemInFolder`                                 |

所有路径只在主进程解析，不直接回传渲染层。`showSkillInFolder` 与 `exportSkill` 均接受 `name` 参数；`exportMySkills` 传 `{}` 触发批量。

---

## 6. 导入 provenance

`backend/skills/skill_md/importer.py` 的 `import_files` 与 `import_directory` 在写盘前调用 `_with_import_provenance(meta, body, original)`：

- 解析出的 `meta["metadata"]` 不存在则创建字典
- `setdefault("provenance", "user-imported")` —— 不覆盖已有值（保留原文档声明）
- 调用 `dump` 重新序列化 frontmatter
- 任何解析 / 编码异常 → 返回原 `content`，不阻断导入

注入失败保留原文，因此现有集成测试（content 严格相等断言）不受影响；只有成功写入的 SKILL.md 才含新字段。

---

## 7. 汉化

新增 `skills_page.*` i18n 命名空间，覆盖页签、空态、来源徽章、分组名、筛选、统计、详情段标题、CTA 与 toast。

`Pending Drafts` → `待审草稿`（zh）/ `Pending Drafts`（en）。Tab trigger 文案通过 `t()` 输出。

`settings.skills.directory.desc` 补注升级安全提示：「用户目录中的技能在应用升级后仍会保留；请勿指向应用安装目录。」

---

## 8. 升级持久化结论

- 默认 `~/.sage/skills` 位于用户家目录，**安装包升级不会删除**。
- 仅在用户把 `skills_dir` 设置指向应用安装目录或 `$CWD/skills` 时存在风险。
- 设置页文案已明确警告；UI 新增「打开技能目录」与「导出我的技能」作为手动备份入口。
- 内置技能（4 个代码实现）与推荐模板（7 个 shipped）随应用升级被替换，这是期望行为；如需自定义模板，把修改后的技能目录导入到用户目录即可覆盖同名 shipped 版本（用户目录优先级高于 shipped）。

---

## 9. 风险评估与缓解

| 风险                              | 缓解                                                                                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| legacy 自动入队草稿噪音           | 2/4 阈值 + LLM 初筛 + 每 run 一次 + session 归因；失败 best-effort 不影响主对话                            |
| LLM 未配置时草稿仍为空            | 空态明确提示「需要默认模型」；`/learn` 失败给出原因                                                       |
| 路径暴露                          | 所有路径只在主进程使用；realpath 包含性校验；IPC 仅信任渲染层                                              |
| 导出 symlink 逃逸                 | 白名单 + 跳过 symlink + `_is_under_any` 边界校验                                                            |
| i18n 键冲突                       | 集中在 `skills_page.*`；en/zh 成对新增                                                                                          |
| 双分支差异                        | 所有新增 Python 代码使用 `typing.List/Optional` + `from __future__ import annotations`；py38 gate 全绿     |
| 页面重构影响既有测试              | 保留 `SkillCard` API 与 `SkillList` 默认行为；新增 `viewMode` 可选；测试只更新断言（紧凑视图不再显示触发词）|

---

## 10. 测试覆盖

| 范围                    | 数量 | 关键用例                                                                                    |
| ----------------------- | ---- | ------------------------------------------------------------------------------------------- |
| 前端 skills widgets     | 190  | SkillCard/SkillRow/SkillList/SkillDetailDrawer/SkillDraftList/Skills 页面                  |
| 后端技能路由            | 71   | import / import-directory / delete / scope / lifecycle / pins / storage & export            |
| 后端 legacy agent       | 5    | complex_turn 入队阈值/技能专注跳过/失败降级/session_id 缺失                                |
| 后端 inproc adapter     | 82   | origin 字段、list_skills_extended 全量                                                      |
| Python 3.8 兼容门       | 0    | AST gate 全绿                                                                               |

---

## 11. 架构基线更新

`architecture-baseline.json` 同步 4 处增长（均为有意新增功能，未突破 800 行上限）：

| 文件                                     | 原行数 | 现行数 |
| ---------------------------------------- | ------ | ------ |
| `backend/adapters/out/skill/inproc.py`   | 1127   | 1178   |
| `backend/core/legacy/agent.py`           | 3654   | 3697   |
| `electron/preload.ts`                    | 954    | 966    |
| `src/shared/types/electron-api.d.ts`     | 908    | 916    |

`backend/api/legacy_skills_routes.py` 通过把 M3/M4 抽离到独立的 `backend/api/skill_storage_export_routes.py` 回到 647 行，未触发「新文件超过 800 行」的硬上限。
