# 2026-10-21 技能设置：脚本执行开关（T-3）+ 技能目录导入（T-4）

> T-1 / T-2 已于 PR #2187 合并到 main（`202c50e9`）。本计划承接剩余的 T-3 / T-4。

## 背景与目标

T-1 / T-2 让 SKILL.md 脚本**能跑**，但把"能不能跑"完全交给后端权限系统
（`_enforce_permission`）和用户确认通道，前端**没有可见的开关**，用户不知道
技能脚本存在、也关不掉。同时导入端停留在"单文件"模型——用户拿到一个技能
目录（含 `scripts/`、`assets/`）时，**只能逐个 .md 导入，附属资源全部丢失**。

本计划：

- **T-3**：新增「允许执行技能脚本」显式开关（默认关，fail-closed），
  前端可见可控，后端强制生效。
- **T-4**：新增「技能目录」设置项（可自定义 skills 根目录）+ 技能目录导入
  （一次导入 `SKILL.md` + `scripts/` + `references/` + `assets/` + `templates/`）。

## 现状（已核实）

### 后端

| 位置 | 事实 |
|---|---|
| `backend/adapters/out/skill/inproc.py:211` | `execute()` 内 `_is_script_dispatch` → `_enforce_permission` 是唯一闸口 |
| `backend/adapters/out/skill/inproc.py:242` | `_enforce_permission` 走 `PermissionEnforcer.check("skill", args)`；`skill` 归 `ToolCapability.EXECUTE`（`backend/tools/permissions.py:79`） |
| `backend/tools/permissions.py:366-368` | `SETTINGS_KEY_MODE = "permission_mode"` / `SETTINGS_KEY_RULES = "permission_rules"` |
| `backend/data/settings_repo.py:18` | `SettingsRepository.KEYS: FrozenSet[str]` —— **preference key 白名单，不加则后端 400** |
| `backend/api/chat_session_lifecycle.py:256` | 布尔开关读取惯例：`SettingsRepository().get(key)`，缺省开/关靠显式 `"0"` 区分 |
| `backend/skills/skill_md/importer.py:206` | `import_files()` **扁平遍历**上传文件，无目录结构概念 |
| `backend/skills/skill_md/importer.py:275` | 目标路径 `skills_dir / name / "SKILL.md"` —— 只写入口文件，附属资源无处安放 |
| `backend/skills/skill_md/importer.py:304` | `_resolve_skills_dir()` 优先级：显式参数 > `SAGE_SKILLS_DIR` env > `~/.sage/skills` |
| `backend/skills/skill_md/resources.py:34` | `ALLOWED_RESOURCE_DIRS = {"scripts","references","assets","templates"}` —— 加载端**已认识**目录结构 |
| `backend/api/legacy_skills_routes.py:382` | `POST /skills/import`：`files: List[UploadFile]`，字段名 `files` |

### 前端

| 位置 | 事实 |
|---|---|
| `src/pages/settings/components.tsx:58` | `Toggle` 组件（`role="switch"` + `aria-checked`），配套 `SettingRow` |
| `src/entities/setting/settingsRegistry.ts:10` | `booleanSetting(...)` 工厂；`:171` `permission_mode`（`riskLevel: 'high'`）是安全开关先例 |
| `src/shared/api/settingsClient.ts:23` | `PreferenceKey` 联合类型白名单 —— **不加则 TS 编译失败** |
| `src/features/manage-settings/useConfirmedPreference.ts` | 带保存回执的 preference 读写 hook（`loading/idle/saving/saved/error`，失败自动回滚） |
| `src/pages/settings/settingsNavigation.ts:3` | `visibleTabs` 白名单 |
| `src/pages/settings/settingsPresentation.ts:3` | `GROUPS` 左侧分组 |
| `src/pages/settings/settingsSearchIndex.ts:9` | `SettingsTabKey` 联合类型 + `SETTINGS_SEARCH_INDEX` |
| `src/shared/lib/i18n/locales/{zh,en}/chatAndSider.ts` | `settings.tab.*` 文案 |
| `electron/skillsIpc.ts:71-77` | `buildMultipart` 硬约束：只收 `.md`、拒目录、filename 不得含 `/` |
| `electron/skillsIpc.ts:93` | `recentPickedFiles` 模块级变量传路径（IPC 参数不传路径） |
| `src/pages/Skills.tsx:274` | `handleImport()` —— 只支持"导入 SKILL.md"单文件多选 |
| `src/shared/api/skillsApi.ts:132` | `importFiles(_paths?)` —— **参数被忽略**，实际走 IPC bridge |

**关键结论**：后端**加载器**已支持 `scripts/references/assets` 目录结构，
缺口只在**导入端**（Electron multipart 协议 + importer 写盘逻辑）。

## 涉及文件

### T-3 脚本执行开关

**后端**
- `backend/data/settings_repo.py` — `KEYS` 加 `allow_skill_scripts`
- `backend/adapters/out/skill/inproc.py` — `execute()` 脚本分支前加开关检查
- `backend/skills/skill_md/script_policy.py`（新）— 开关读取 + 判定（便于单测）
- `backend/tests/unit/test_skill_script_policy.py`（新）

**前端**
- `src/entities/setting/settingsRegistry.ts` — 加 `allow_skill_scripts` 条目
- `src/shared/api/settingsClient.ts` — `PreferenceKey` 加 key
- `src/pages/settings/SkillsTab.tsx`（新）— 承载 T-3 + T-4a 两项设置
- `src/pages/settings/Settings.tsx` — tabs 数组 + 内容分发
- `src/pages/settings/settingsNavigation.ts` — `visibleTabs` 加 `skills`
- `src/pages/settings/settingsPresentation.ts` — `GROUPS` 加 `skills` 分组
- `src/pages/settings/settingsSearchIndex.ts` — `SettingsTabKey` + 索引条目
- `src/shared/lib/i18n/locales/{zh,en}/chatAndSider.ts` — tab 文案
- `src/pages/settings/__tests__/SkillsTab.test.tsx`（新）

### T-4a 技能目录设置项

**后端**
- `backend/data/settings_repo.py` — `KEYS` 加 `skills_dir`
- `backend/skills/skill_md/importer.py` — `_resolve_skills_dir()` 加 preference 优先级
- `backend/tests/unit/test_skill_md_importer.py` — 补优先级用例

**前端**
- `src/entities/setting/settingsRegistry.ts` — 加 `skills_dir` 条目
- `src/shared/api/settingsClient.ts` — `PreferenceKey` 加 key
- `src/pages/settings/SkillsTab.tsx` — 目录输入框 + 校验

### T-4b 技能目录导入

**Electron**
- `electron/skillsIpc.ts` — 新增 `skills:pick-directory`；`buildDirectoryMultipart`
  （相对路径 filename + 扩展名推断 Content-Type + 目录树遍历 + 大小限额）
- `electron/preload.ts` — bridge 加 `pickSkillDirectory` / `importSkillDirectory`
- `src/shared/types/electron-api.d.ts` — 类型声明

**前端**
- `src/shared/api/skillsApi.ts` — 新增 `importDirectory()`
- `src/pages/Skills.tsx` — 新增「导入技能目录」按钮 + handler

**后端**
- `backend/api/legacy_skills_routes.py` — 新增 `POST /skills/import-directory`
- `backend/skills/skill_md/importer.py` — `import_directory()`：按相对路径分组落盘
- `backend/tests/unit/test_skill_md_importer.py` — 目录导入用例
- `backend/tests/integration/test_skill_import_directory.py`（新）

## 技术方案

### T-3 开关语义

**默认关（fail-closed）**。`allow_skill_scripts` 缺省视为"关"，只有显式 `"1"`
才允许脚本分发。

```
REST /skills/{name}/execute  {"script": "..."}  ─┐
skill 工具 {"script": "..."}                    ─┼→ adapter.execute()
slash /cmd script=scripts/x.py                  ─┘        │
                                                        ▼
                                    _is_script_dispatch(skill, args) == True
                                                        │
                                    ┌───────────────────┴───────────────────┐
                                    ▼                                       ▼
                        allow_skill_scripts == "1"?              _enforce_permission()
                                    │                                       │
                              否 → 拒绝(fail-closed)              (现有 EXECUTE 闸口)
```

两层闸口**串联**：开关是第一道（用户显式授权），权限系统是第二道（模式矩阵）。
开关通过 ≠ 权限通过，任一不过即拒绝。

**为什么独立于 `permission_mode`**：`permission_mode` 是"工具执行模式"
（read_only / workspace_write / prompt / full_access），语义是**约束强度**；
"是否允许执行技能脚本"是**能力开关**，语义是"这个功能开不开"。把两者混在一起
会让 `full_access` 隐式打开脚本执行，违反"显式 opt-in"。

**错误信息**：`"技能脚本执行未启用：请在设置 → 技能 中开启「允许执行技能脚本」"`
（`metadata.permission_denied = True`，与现有拒绝路径一致）。

### T-3 后端读取

新建 `backend/skills/skill_md/script_policy.py`：

```python
SETTINGS_KEY_ALLOW_SKILL_SCRIPTS = "allow_skill_scripts"

def is_script_execution_allowed(repo=None) -> bool:
    """缺省 False（fail-closed）；仅显式 "1" 视为开启。"""
```

放独立模块而非塞进 `inproc.py`：`inproc.py` 已 500+ 行，且 import-linter
约束下 `adapters → skills` 是允许方向；独立模块便于单测（不拉起整个 adapter）。

读取失败（DB 故障）→ 视为**关闭**（fail-closed），记 warning。

### T-4a 技能目录

`_resolve_skills_dir()` 优先级调整为：

```
显式参数 > SAGE_SKILLS_DIR env > preference "skills_dir" > ~/.sage/skills
```

preference 路径需做校验：绝对路径、已存在或可创建、不含 `..`。
非法 → 记 warning 并回退下一级（不抛异常，避免把设置损坏升级成启动失败）。

### T-4b 目录导入协议

**新增独立端点**，不改动现有 `POST /skills/import`（向后兼容，零回归风险）：

```
POST /api/v1/skills/import-directory
Content-Type: multipart/form-data
  files: <相对路径>   ← 每个 part 的 filename 携带相对路径
                        如 "SKILL.md" / "scripts/scan.py" / "assets/tpl.html"
```

**后端 `import_directory(files)`**：

1. 读所有 part 的 `(relative_path, content)`
2. 相对路径校验：非绝对路径、无 `..`、无 `\`、无空段、无符号链接语义
3. 找入口文件：相对路径等于 `SKILL.md`（大小写不敏感）；**没有则整批拒绝**
   （400，错误信息说明"目录中缺少 SKILL.md"）
4. 解析入口 → 得技能名（frontmatter `name`），沿用现有 `parse_file_from_bytes`
5. 落盘目标 `<skills_dir>/<name>/<相对路径>`
   - 路径穿越防御：每个相对路径 resolve 后必须仍在 `<skills_dir>/<name>/` 之下
   - 跳过符号链接（`lstat` 判定）
   - 大小限额沿用现有常量（单文件 1MB / 总 10MB），并加**文件数**上限
6. 附属文件只允许落在 `ALLOWED_RESOURCE_DIRS` 白名单目录内，其余忽略
   （与加载端 `resources.py` 口径一致，避免写入加载器不会读的目录）
7. 返回 `{"imported": [{"name", "path"}], "skipped": [{"name", "reason"}]}`

**Electron `skills:pick-directory`**：

- `dialog.showOpenDialog({ properties: ['openDirectory'] })`
- 遍历目录树（深度上限 + 文件数上限，防误选巨型目录）
- 只收集 `SKILL.md`（根）+ `scripts/` `references/` `assets/` `templates/` 下的文件
- 相对路径用 `/` 分隔（跨平台一致）
- multipart part 的 `filename` 写相对路径；`Content-Type` 按扩展名推断
  （`.py` → `text/x-python`，`.md` → `text/markdown`，其余 → `application/octet-stream`）

**为什么走 multipart 而不是 JSON base64**：与现有导入通道同构，Electron 侧
已有一套手写 multipart 构造（Node 16 兼容，不用 FormData），改动最小。

## 实施步骤

- [x] 步骤 1：写本计划文档
- [x] 步骤 2：后端 T-3 —— `script_policy.py` + `inproc.py` 闸口 + `settings_repo.KEYS`
- [x] 步骤 3：后端 T-3 单测（开关关/开、DB 故障 fail-closed）— 29 tests green
- [x] 步骤 4：前端 T-3 —— registry + `PreferenceKey` + `SkillsTab` + i18n + 搜索索引
- [x] 步骤 5：前端 T-3 测试 + `tsc` + lint — `SkillsTab.test.tsx` 15/15 pass；`tsc --noEmit` 净
- [x] 步骤 6：后端 T-4a —— `skills_dir` preference + `_resolve_skills_dir()` 优先级
- [x] 步骤 7：后端 T-4a 单测 — `test_skills_dir_policy.py` 12/12 pass
- [x] 步骤 8：Electron T-4b —— `skills:pick-directory` + `buildDirectoryMultipart`（`commands.test.ts` 88/88 pass）
- [x] 步骤 9：后端 T-4b —— `POST /skills/import-directory` + `import_directory()`
- [x] 步骤 10：后端 T-4b 单测 + 集成测试 — 35 tests pass（26 unit + 9 integration）
- [x] 步骤 11：前端 T-4b —— `skillsApi.importDirectory()` + `Skills.tsx` 按钮（Skills.test.tsx 8/8 pass）
- [x] 步骤 12：Electron smoke + 前端构建 + 后端全量测试（前端构建 `tsc && vite build` 绿）
- [ ] 步骤 13：code-review + security-review
- [ ] 步骤 14：提交 + 推送 + 开 PR

## 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| T-3 开关默认关 → 合并后 T-1/T-2 功能默认不可用 | **高** | 这是**预期行为**（显式 opt-in）。PR 描述与 UI 文案必须说清"需在设置 → 技能中开启"；默认 `permission_mode=workspace_write` 下脚本本来也需要用户确认 |
| 开关绕过：某条路径不经 `adapter.execute()` | 高 | T-2 已把 slash / skill 工具全部路由到 `adapter.execute()`；新增用例断言三条入口都被拒 |
| T-4b 相对路径路径穿越 | **高** | 后端逐段校验 + resolve 后边界断言 + 符号链接跳过；导入只写白名单目录 |
| T-4b 导入大目录打爆内存/CI | 中 | 文件数上限（100）+ 单文件 1MB + 总 10MB，沿用现有常量 |
| Electron multipart filename 含 `/` 被拒 | 中 | 现有 `buildMultipart` 的 `[\r\n"]` 校验保留；新增独立构造函数，不放宽旧通道 |
| 新增 settings tab 漏改配套文件 | 中 | 契约测试 `settingsRegistry.test.ts` + `settingsContract.test.ts` 守门；搜索索引/导航/分组三处同步改 |
| 破坏现有 `POST /skills/import` | 低 | 目录导入走**新端点**，旧端点代码零改动 |

## 依赖

- 无前置 PR（T-1/T-2 已在 `202c50e9` 合并）
- 后续：T-3/T-4 完成后应 cherry-pick 到 `release/win7`（py38 兼容：无 PEP 604、无 `X | Y` 运行时注解）
