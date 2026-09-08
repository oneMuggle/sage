# Win7 安装包启动失败诊断修复 (2026-09-08)

## 背景与目标

**症状**（用户实测，发布到 Win7 电脑的 Sage 安装包）：

1. 程序似乎不能正常启动（用户反馈"没有正常启动"）
2. 启动日志 NDJSON 中 doctor check 报告 **3 个 CRITICAL + 1 个 WARN + 12 个 INFO**
3. 系统托盘 tray 加载失败（`continuing without tray`）
4. 约 30 秒后第二次启动进程（`pid 9412`），之后日志截断

**实际根因**（已通过 systematic-debugging 验证）：

| # | 真根因 | 影响 | 严重度 |
|---|---|---|---|
| 1 | doctor spawn 时 SAGE_USER_DATA_DIR fallback 用 `process.cwd()` 而非 `app.getPath('userData')`，导致 sqlite_writable / log_dir_size 误判安装目录可写性 | doctor 误报 3 个 CRITICAL（conda_env / sqlite_writable / runtime_env），但**实际 backend 用的是 `%APPDATA%\Sage`，是好的** | 🔴 致命（用户体验崩） |
| 2 | `build/icon.ico` 和 `build/icon.png` 没被打包进 `app.asar`，tray 图标加载路径不存在 | Win7 tray 整个失败（Win7 tray 必须用 .ico，PNG 不支持） | 🔴 致命（win7 桌面增强全废） |
| 3 | `conda_env` check 只认三个 conda 路径，对 packaged 嵌入式 Python 必然 CRITICAL | doctor 噪音；用户以为程序坏了 | 🟡 重要（误报噪音） |
| 4 | `runtime_env` 通过 PATH 扫描找 Python；packaged 嵌入式 Python 不在 PATH → 报"Python ×0" | doctor 噪音 | 🟡 重要（误报噪音） |
| 5 | doctor 输出中文，stdout 没强制 UTF-8，Win7 cmd 默认 GBK → 日志全部乱码 | 诊断困难 | 🟢 次要 |
| 6 | `backend_health` WARN：doctor 在 17.7s 启动期内探测 `/health` 1s timeout，后端尚未 listen | 误报；不影响功能 | 🟢 次要 |

**目标**：

- P0 必修：让 Win7 packaged 模式下 doctor 报告**没有 CRITICAL**（除非真的有问题），且 tray 正常加载
- P1 重要：清掉 doctor 的所有 Win7 误报噪音
- P2 次要：让 doctor 输出在 Win7 上可读（中文不乱码）

## 涉及的文件与模块

### 修复 #1（electron/main.ts）

**文件**：`electron/main.ts`

**行号**：1637-1644（doctor spawn 路径）

**改动**：把 `sageDbPath` / `sageUserDataDir` 的 fallback 从 `join(process.cwd(), 'data')` 改成与 `spawnBackend()`（line 278-285）一致的 `app.isPackaged` 三元逻辑。

### 修复 #2（electron-builder.yml）

**文件**：`electron-builder.yml`

**行号**：10-21（`files` 列表）

**改动**：把 `build/icon.ico` 和 `build/icon.png` 加进 files 列表，让它们被打包进 `app.asar`。

### 修复 #3（backend/cli/checks/conda_env.py）

**文件**：`backend/cli/checks/conda_env.py`

**改动**：增加 packaged 模式检测（`getattr(sys, 'frozen', False)` 或 `sys.executable` 包含 `resources/python`），packaged 模式直接返回 INFO "使用嵌入式 Python（packaged 模式）"。

### 修复 #4（backend/tools/runtime_probe.py）

**文件**：`backend/tools/runtime_probe.py` 或 `backend/cli/checks/runtime_env.py`

**改动**：把 `sys.executable` 加入 Python 候选列表，避免 packaged 模式误报 Python ×0。

### 修复 #5（backend/cli/doctor.py）

**文件**：`backend/cli/doctor.py`

**改动**：`main()` 函数最前面强制 `sys.stdout.reconfigure(encoding='utf-8')` 和 `sys.stderr.reconfigure(encoding='utf-8')`（Py3.7+ 标准 API）。

### 修复 #6（不动）

`backend_health` warn 是 doctor 启动时序问题，与功能无关，不修。

## 技术方案

### 修复 #1 的精确 diff

```diff
       const supervisorPlan = resolveBackendLaunchCommand({
         env: process.env,
         resourcesPath: process.resourcesPath,
         platform: process.platform,
         isPackaged: app.isPackaged,
-        sageDbPath: process.env.SAGE_DB_PATH ?? join(process.cwd(), 'data', 'sage.db'),
-        sageUserDataDir: process.env.SAGE_USER_DATA_DIR ?? join(process.cwd(), 'data'),
+        sageDbPath: process.env.SAGE_DB_PATH ??
+          (app.isPackaged
+            ? join(app.getPath('userData'), 'sage.db')
+            : join(process.cwd(), 'data', 'sage.db')),
+        sageUserDataDir: process.env.SAGE_USER_DATA_DIR ??
+          (app.isPackaged ? app.getPath('userData') : join(process.cwd(), 'data')),
         port: BACKEND_PORT,
       });
```

### 修复 #2 的精确 diff

```diff
 files:
   - dist/**/*
   - dist-electron/**/*
   - electron/**/*
+  - build/icon.ico    # Win7 tray 图标
+  - build/icon.png    # Linux tray 图标
   - package.json
```

### 修复 #3 的关键逻辑

```python
# 在 CondaEnvCheck.run() 里开头加：
if getattr(sys, 'frozen', False) or 'resources/python' in str(Path(sys.executable).resolve()):
    return CheckResult(
        self.name,
        Severity.INFO,
        f"使用嵌入式 Python ({sys.executable})，跳过 conda 环境检查",
    )
```

### 修复 #4 的关键逻辑

`runtime_probe.py` 在生成 candidates 时，把 `sys.executable` 加入 "python" 列表：

```python
candidates["python"] = [sys.executable, *candidates.get("python", [])]
```

### 修复 #5 的精确 diff

```diff
 def main(argv: Optional[list] = None) -> int:
+    # 强制 UTF-8 stdout/stderr (Win7 cmd 默认 GBK 会乱码)
+    for stream in (sys.stdout, sys.stderr):
+        if hasattr(stream, "reconfigure"):
+            stream.reconfigure(encoding="utf-8")
     _import_all_checks()
     ...
```

## 实施步骤

### 阶段一（P0，必修）

- [x] **步骤 1**：建 feature 分支 `fix/win7-doctor-misreport-tray-icon`
- [x] **步骤 2**：写本 plan 文档
- [ ] **步骤 3**：写失败测试（tdd-guide）
  - `electron/__tests__/main.test.ts`：mock `app.isPackaged=true`、`app.getPath('userData')='/mocked/userData'` → 验证 doctor spawn 时 SAGE_USER_DATA_DIR = '/mocked/userData'
  - `electron/__tests__/iconPackaging.test.ts` 或手测：asar list app.asar | grep icon
- [ ] **步骤 4**：实施修复 #1（main.ts doctor spawn path）
- [ ] **步骤 5**：实施修复 #2（electron-builder.yml files）
- [ ] **步骤 6**：跑 `sage-backend` 环境 pytest：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -x -q`
- [ ] **步骤 7**：跑 TypeScript 类型检查：`npm run typecheck` 或 `tsc --noEmit -p tsconfig.electron.json`
- [ ] **步骤 8**：本地手测 `npm run dev` + `npm run electron:dev`，看 doctor 日志（dev 路径应不触发此 bug，因为 `process.cwd()` 实际就是项目根）

### 阶段二（P1，重要）

- [ ] **步骤 9**：实施修复 #3（conda_env check packaged 跳过）
- [ ] **步骤 10**：实施修复 #4（runtime_probe sys.executable）
- [ ] **步骤 11**：加测试覆盖：
  - `backend/cli/checks/__tests__/test_conda_env.py`：模拟 packaged 模式（mock sys.executable）→ 应返回 INFO
  - `backend/cli/checks/__tests__/test_runtime_env.py`：模拟 packaged 模式 → 应至少返回 1 个 python
- [ ] **步骤 12**：跑 Py3.8 测试（在 worktree 里用 `sage-backend-py38` 环境，模拟 win7 兼容性）

### 阶段三（P2，次要）

- [ ] **步骤 13**：实施修复 #5（doctor.py 强制 UTF-8）
- [ ] **步骤 14**：测试输出编码（`PYTHONIOENCODING=utf-8 python -m backend.cli.doctor --json` 应输出 utf-8）

### 阶段四（收尾）

- [ ] **步骤 15**：code-reviewer agent 检阅
- [ ] **步骤 16**：更新 plan 文档（标记所有步骤完成）
- [ ] **步骤 17**：commit + push + 开 PR
- [ ] **步骤 18**：CI 通过后合并
- [ ] **步骤 19**：cherry-pick 到 release/win7 分支（按需，按 CLAUDE.md 强制流程）

## 风险评估与依赖

### 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 修复 #1 改了 doctor spawn 行为，可能影响 dev 模式 doctor 输出 | 低 | dev 模式下 `app.isPackaged=false`，fallback 仍是 `process.cwd()/data`，行为不变 |
| 修复 #2 加了 build 文件进 asar，可能导致打包大小增加 ~600KB | 低 | icon.ico 111KB + icon.png 470KB，可接受 |
| 修复 #3 packaged 检测逻辑在 Linux 上误判 | 低 | `resources/python` 路径只在 Win7/Linux packaged 出现；macOS 已 broken-installer，不会触发 doctor |
| 修复 #4 sys.executable 在 `python -m backend.cli.doctor`（host Python）下可能被加进 PATH 外的列表 | 低 | 不会让 doctor 误报更多，只会让"找不到 Python"的情况变少 |
| 修复 #5 stdout.reconfigure 在 Py3.6 之前不存在 | 无 | project 最低 Py3.8（win7），最低 Py3.10（main） |

### 依赖

- 无新增依赖
- 无需 DB schema 变更
- 不涉及 electron-builder 版本升级
- 不涉及 Electron 21.4.4 变更

### 兼容性

- **dev 模式**：修复 #1 与 dev 模式兼容（fallback 逻辑等价）
- **packaged Win7**：核心目标场景，修复后 doctor 应无 CRITICAL（除非真的有问题）
- **packaged Linux**：tray icon 也会修（虽然 Linux 托盘缺失影响小）
- **packaged macOS**：broken-installer，无影响
- **release/win7 分支**：cherry-pick 时需手动验证 Py3.8 兼容性

### 不做的事

- ❌ 不升级 electron-builder
- ❌ 不修改 Electron 版本
- ❌ 不重写 doctor.py 的整体架构
- ❌ 不修改 SAGE_USER_DATA_DIR 的最终用户语义（仍用 `app.getPath('userData')`）
- ❌ 不动 backend_health check（次要 warn，不影响功能）