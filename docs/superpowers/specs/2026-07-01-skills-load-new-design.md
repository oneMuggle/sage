# Skills 加载新技能 — Design Spec

- **Date:** 2026-07-01
- **Branch:** `feat/skill-load-button` (基于 `origin/main`)
- **Status:** Draft,待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

Sage 当前通过启动时的 `discover_skill_md_dirs()` 加载 `$SAGE_SKILLS_DIR` / `./skills` / `~/.sage/skills` 三个目录下的 SKILL.md。Backend 是常驻进程,**没有任何运行时的"重新扫描"入口**,用户新增 SKILL.md 后必须重启 backend 才能生效。同时也没有"导入 SKILL.md 文件"的能力,用户必须手动把文件复制到上述目录。

Skills 页面 (`src/pages/Skills.tsx`) 头部只有一个 RefreshCw 图标(刷新 UI 列表,不重新扫盘)和"自动刷新(10s)" toggle,无法满足"我加了一个新技能,让界面立刻看到"这个核心 use case。

### 1.2 目标

为 Skills 页面增加两个能力:
1. **重扫磁盘 (Rescan)** — 调用 `SkillMdHotLoader.scan_and_load()` 在不重启 backend 的情况下增量加载新增的 SKILL.md。
2. **导入 SKILL.md (Import)** — 通过 Electron native dialog 选择 1 个或多个 `.md` 文件,后端解析 frontmatter + 写入目标目录 + hot reload,前端 UI 自动反映。

### 1.3 非目标 (YAGNI)

- 不做"运行时切换 SAGE_SKILLS_DIR"(由未来设置项 PR 单独做)
- 不做"导出 / 分享技能"
- 不做"从 URL / 剪贴板导入"
- 不做"批量导入目录"(`dialog.showOpenDialog({properties: ['openDirectory']})` 留作未来口子)
- 不做 web 模式兼容(项目 Electron-only,e2e 不需要)
- 不做 release/win7 同步(本期只在 main,后续按需 cherry-pick)

## 2. 用户故事

- **US-1**:作为 Sage 用户,我编辑了一个新的 `~/.sage/skills/code-review/SKILL.md`,希望点 Skills 页面某个按钮后,无需重启 backend 就能在列表里看到它。
- **US-2**:作为 Sage 用户,我从 GitHub 复制了一个 `SKILL.md` 文件,希望点导入按钮 → 选择文件 → 立即出现在列表里,无需手动复制到 `~/.sage/skills/`。
- **US-3**:作为 Sage 用户,导入一个与 builtin (coder/search/travel/writer) 同名的 SKILL.md 时,系统应跳过并明确告知,而不是静默丢弃。
- **US-4**:作为 Sage 用户,导入一个磁盘上已存在的同名 SKILL.md 时,系统应跳过并明确告知(本期不支持覆盖,避免误操作)。

## 3. 架构

### 3.1 数据流概览

```
┌──────────────┐                                  ┌──────────────────────────┐
│ Renderer     │  skillsApi.rescan()             │ Backend (FastAPI)        │
│ Skills.tsx   │ ──────────────────────────────► │  POST /skills/rescan     │
│              │                                  │   → SkillMdHotLoader     │
│              │  skillsApi.importFiles(files)   │     .scan_and_load()     │
│              │ ──────────────────────────────► │  POST /skills/import     │
│              │   (multipart)                    │   (multipart, files[])   │
│              │                                  │   → SkillMdImporter      │
│              │                                  │     .import_files()      │
└──────┬───────┘                                  └──────────┬───────────────┘
       │                                                     │
       │ IPC: skills:pick-files                              │
       ▼                                                     │
┌──────────────┐                                             │
│ Electron     │  dialog.showOpenDialog(...)                │
│ main         │ ──────────────────────────────────────────►│
│ (commands.ts)│                                             │
└──────────────┘                                             │
       ▲                                                     │
       │ IPC: skills:rescan / skills:import (HTTP wrapper)   │
       └─────────────────────────────────────────────────────┘
```

### 3.2 组件分层

| 层 | 组件 | 职责 |
|---|---|---|
| Backend | `SkillMdImporter` (新) | 解析 multipart 文件 → frontmatter 校验 → name slug 校验 → builtin 冲突检查 → 写盘 → hot reload |
| Backend | `SkillMdHotLoader` (复用,无改动) | 已有 `scan_and_load()` 增量加载已存在的目录;`hot_reload(name)` 单文件重载 — 本期直接调用,不修改 loader.py |
| Backend | `legacy_routes.py` | 加 2 endpoint:`POST /skills/rescan` 和 `POST /skills/import` |
| Backend | `InprocSkillAdapter` | 暴露 `rescan_skill_mds()` + `import_skill_mds(files)` 给路由层 |
| Electron | `commands.ts` | 加 3 IPC:`skills:pick-files` (返回 File[])、`skills:rescan`、`skills:import` |
| Renderer | `skillsApi.ts` | 加 `rescan()` + `importFiles(files: File[])` |
| Renderer | `Skills.tsx` | 加 2 图标按钮 (Rescan / Import) + handler + toast 反馈 |

### 3.3 落地目录解析

与 `SkillMdDeleter._resolve_skills_dir` 对齐,**新规则**:目录不存在时**自动 `mkdir(parents=True, exist_ok=True)`**,而不是抛 500。这样首次安装的用户点导入就能用。

```python
def _resolve_skills_dir() -> Path:
    """优先级:
    1. SAGE_SKILLS_DIR env (若存在)
    2. ~/.sage/skills (若存在或能创建)
    3. 抛 NoSkillsDirError
    """
    env = os.environ.get("SAGE_SKILLS_DIR", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir() or _ensure_dir(p):
            return p
    user = Path.home() / ".sage" / "skills"
    if _ensure_dir(user):
        return user
    raise NoSkillsDirError("No SAGE_SKILLS_DIR or ~/.sage/skills; cannot import")
```

`_ensure_dir` 内部 `p.mkdir(parents=True, exist_ok=True)`,失败抛 `PermissionError`。

## 4. API 契约

### 4.1 `POST /api/v1/skills/rescan`

**请求:** 无 body,无需参数。

**响应 200:**
```json
{
  "loaded": [
    {"name": "code-review", "source": "skillmd", "path": "/home/user/.sage/skills/code-review/SKILL.md"}
  ],
  "skipped": [],
  "total_loaded": 1
}
```

**幂等:** 重复调用,新文件数为 0,返回 `loaded: []` + `skipped: []`。
`total_loaded` 是本次 rescan 新增并注册的数量(不是注册表总数),与 `loaded.length` 相等 — 此字段保留是为未来按需扩展(例如批量 hot reload 数)。

**`skipped` 字段当前始终为 `[]` 的原因** (plan-mandated 限制): `SkillMdHotLoader.scan_and_load()` 当前只返 `(loaded_count, skipped_count)` 两个 int, 不返 `[{name, reason}]` detail。Backend 端在 `inproc.py::rescan_skill_mds` 已经按 `[]` 兜底, docstring 已记录此限制。要支持 detail 报告, 需扩展 `SkillMdHotLoader.scan_and_load()` API — 未来 follow-up (见 plan §10.9)。

### 4.2 `POST /api/v1/skills/import`

**请求:** `multipart/form-data`,字段 `files` (可重复):
```
files: SKILL.md (binary)
files: another.md (binary)
```

**响应 200:**
```json
{
  "imported": [
    {"name": "code-review", "path": "/home/user/.sage/skills/code-review/SKILL.md"}
  ],
  "skipped": [
    {"name": "coder", "reason": "builtin_conflict"},
    {"name": "existing-skill", "reason": "already_exists"},
    {"name": "bad-name!", "reason": "invalid_name"},
    {"name": "broken", "reason": "parse_error: missing 'description'"}
  ]
}
```

**响应 400:** `{"detail": {"type": "invalid_request", "message": "no files provided"}}`

**响应 500:** `{"detail": {"type": "no_skills_dir", "message": "..."}}` 或 `{"detail": {"type": "write_failed", "message": "..."}}`

### 4.3 IPC 契约

| Channel | 方向 | 参数 | 返回 |
|---|---|---|---|
| `skills:pick-files` | renderer → main | 无 | `string[] \| null` (selected paths,取消返回 null) |
| `skills:rescan` | renderer → main | 无 | `RescanResult` |
| `skills:import` | renderer → main | `string[]` (paths) | `ImportResult` |

`skills:import` 内部 main process 读每个 path 为 File-like 对象,转发到 HTTP endpoint。

## 5. 前端 UI

### 5.1 Skills.tsx 头部(之后)

```tsx
<div className="flex items-center gap-3">
  <Checkbox>自动刷新(10s)</Checkbox>
  <IconButton onClick={loadSkills} title="刷新列表">      {/* 已有 */}
    <RefreshCw />
  </IconButton>
  <IconButton onClick={handleRescan} title="重扫磁盘">    {/* 新 */}
    <RotateCw />  {/* lucide-react,区别于 RefreshCw 的顺时针箭头 */}
  </IconButton>
  <IconButton onClick={handleImport} title="导入 SKILL.md"> {/* 新 */}
    <Upload />
  </IconButton>
</div>
```

**按钮顺序逻辑:** RefreshCw(列表刷新,已有)→ RotateCw(磁盘重扫)→ Upload(导入)。语义从"轻"到"重":UI 级 → 磁盘级 → 用户输入级。

### 5.2 Handler 实现

```typescript
const handleRescan = async () => {
  setRescanLoading(true);
  try {
    const result = await skillsApi.rescan();
    if (result.loaded.length > 0) toast.success(`已加载 ${result.loaded.length} 个技能`);
    if (result.skipped.length > 0) toast.warn(`跳过 ${result.skipped.length} 个`);
    await loadSkills();  // 刷新 UI
  } catch (err) {
    toast.error(`重扫失败: ${(err as Error).message}`);
  } finally {
    setRescanLoading(false);
  }
};

const handleImport = async () => {
  const paths = await window.electronAPI.pickSkillFiles();
  if (!paths || paths.length === 0) return;
  setImportLoading(true);
  try {
    const result = await skillsApi.importFiles(paths);
    if (result.imported.length > 0) toast.success(`已导入 ${result.imported.length} 个技能`);
    if (result.skipped.length > 0) {
      const reasons = result.skipped.map(s => `${s.name}(${s.reason})`).join(', ');
      toast.warn(`跳过 ${result.skipped.length} 个: ${reasons}`);
    }
    await loadSkills();
  } catch (err) {
    toast.error(`导入失败: ${(err as Error).message}`);
  } finally {
    setImportLoading(false);
  }
};
```

## 6. 错误处理矩阵

| HTTP | type | 触发 | UI 行为 |
|---|---|---|---|
| 200 | — | 全部完成 (含 skipped) | toast.success 显 imported 数,toast.warn 显 skipped 数与原因 |
| 400 | `invalid_request` | multipart 没 files | toast.error('请选择至少一个 .md 文件') |
| 500 | `no_skills_dir` | 两个目录都无法创建 | toast.error('无法创建 skills 目录,请检查权限') |
| 500 | `write_failed` | 写文件失败 (PermissionError) | toast.error(`导入失败: ${msg}`) |

**partial success 策略:** 即使部分文件失败,**HTTP 仍返回 200**,在 `skipped` 数组中报告失败的明细。前端按 skipped 数决定 toast 等级(success-only / success+warn / error-only)。这样 "1 个成功 2 个失败" 不会让用户以为全部失败。

## 7. 测试策略

### 7.1 测试矩阵

| 层 | 文件 | 用例数 | 覆盖 |
|---|---|---|---|
| 单元(后端) | `backend/tests/unit/test_skill_md_importer.py` (新) | 12 | Importer 全部分支 |
| 集成(后端) | `backend/tests/integration/test_skill_import.py` (新) | 10 | multipart + FastAPI + 落盘验证 |
| 单元(Electron) | `electron/__tests__/commands.test.ts` (扩展) | 6 | 3 个新 IPC handler |
| 组件(前端) | `src/widgets/skills/__tests__/Skills.test.tsx` (新) | 8 | 按钮渲染 + 点击 + loading + toast |
| E2E | (不新增,沿用 `e2e/sidebar-skills-nav.spec.ts`) | 0 | dialog 不能 E2E |

### 7.2 后端单元测试详情

```
test_import_files_writes_skill_md_to_correct_path
test_import_files_creates_skill_dir_if_missing (~/.sage/skills auto-mkdir)
test_import_files_skips_builtin_name_collision
test_import_files_skips_existing_skill_md
test_import_files_skips_invalid_name (非 slug)
test_import_files_skips_parse_error
test_import_files_aggregates_skipped_in_result
test_import_files_hot_reloads_after_write (registry 出现新 skill)
test_import_files_handles_write_permission_error
test_import_files_resolves_sage_skills_dir_first
test_import_files_falls_back_to_dot_sage_skills
test_import_files_returns_empty_when_no_files
```

### 7.3 后端集成测试详情

```
test_post_skills_import_multipart_round_trip (POST 文件 → GET /skills 看到)
test_post_skills_import_returns_structured_skipped
test_post_skills_rescan_returns_loaded_count
test_post_skills_rescan_is_idempotent (二次调用 loaded=0)
test_post_skills_import_no_files_returns_400
test_post_skills_import_to_sage_skills_dir_uses_env
test_post_skills_import_invalid_md_returns_parse_error_in_skipped
test_post_skills_import_concurrent_safe (并发同名 → 一个进)
test_post_skills_import_then_list_includes_new
test_post_skills_import_with_empty_file_returns_skipped
```

### 7.4 Electron 单测详情

```
test_pick_files_returns_paths_from_dialog
test_pick_files_returns_null_on_cancel
test_rescan_skill_calls_http_endpoint
test_import_skill_posts_multipart_to_backend
test_import_skill_handles_400_response
test_import_skill_handles_500_response
```

### 7.5 前端组件测试详情

```
test_renders_rescan_and_import_buttons
test_rescan_button_click_calls_skills_api_rescan
test_import_button_opens_dialog_via_electron_api
test_import_success_toast_shown
test_import_with_skipped_warns_user
test_import_error_toast_shown
test_rescan_loading_state_disables_button
test_import_loading_state_disables_button
```

### 7.6 安全 / 防御性测试(单列)

| 测试 | 验证什么 |
|---|---|
| name 含 `../` → skip | 路径遍历防御 |
| name 含 `/` → skip | 与 skill_name_re 一起拒绝 |
| name 含空字节 → skip | OS-level injection 防御 |
| 文件 > 1MB → skip | DoS 防御 |
| 并发导入同名 → 只一个成功 | race condition 防御 |
| frontmatter 含 Python 表达式 → 不被 eval | 走 yaml.safe_load 而非 yaml.load |

## 8. 验收标准 (DoD)

- [ ] 所有新增测试通过(36 个新增 case)
- [ ] 现有 1700+ tests 无回归(后端 pytest + 前端 vitest)
- [ ] CI 4/4 通过(Frontend TS / Electron build x2 / Electron smoke)
- [ ] Skills 页手动验证:rescan 能发现新加的 .md,import 能从 dialog 选文件
- [ ] builtin / SKILL.md 同名 skip 行为正确 (toast 提示)
- [ ] `docs/technical/24-skills-system.md` 加 "import / rescan" 章节
- [ ] release/win7 同步作为后续单独 PR(本期只在 main)

## 9. 实施步骤(高层)

1. **后端:** 写 `SkillMdImporter` + 单元测试 → 加 route + 集成测试
2. **Electron:** 加 3 个 IPC handler + 单测
3. **前端:** 扩 `skillsApi` + Skills.tsx 头部 + 组件测试
4. **文档:** 更新 `docs/technical/24-skills-system.md`
5. **CI:** push → 4 CI 跑全 → Code review → merge → 不自动打 tag(功能变更但属于增强,留待后续按需)

## 10. 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| 导入路径含恶意文件(如 huge file) | DoS | size 限制 1MB,在 Importer 早 reject |
| 并发导入同名 → 双写 | race condition | `_resolve_skills_dir` + `mkdir(exist_ok=False)` 之后写前再 `exists()` 检查(单进程内够用;真要分布式再上锁) |
| frontmatter 解析炸 | Importer crash | 全部走 try/except 包,记 WARNING,不影响其他文件 |
| 用户选 .md 但内容不是 SKILL.md | 加载失败 | 不在 importer 层校验(让 loader 自己 skip + warning),用户体验上仍能看到 skipped |
| Electron IPC + 后端 HTTP 双重错误处理 | 错误信息不一致 | 错误透传 `err.message` 到 toast,后端 error detail 与 frontend message 1:1 映射 |
| 自动创建 `~/.sage/skills` 风险 | 用户意外写盘 | 与 `SkillMdDeleter` 行为一致(已经会写),且只创建目录不创建文件,可接受 |

## 11. 不在本文档范围

- `SkillMdDeleter` 行为变更(本期不动)
- builtin 技能管理(已通过 toggle 控制)
- 技能"导出"功能(YAGNI)
- 技能"市场 / 在线仓库"(YAGNI)
- 运行时切换 `SAGE_SKILLS_DIR`(未来 settings 单独 PR)