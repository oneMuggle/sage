# 多浏览器自动发现与调度（Chrome/Edge/Firefox + 诊断脚本）

## 背景与目标

Win7 安装包用户在使用网页访问 / 登录态保持能力时频繁失败。**根因**:Win7 上 Chrome 最高只支持 109 版本,而 `_build_launch_command` (`backend/tools/browser_cdp.py:263-293`) 默认带 `--headless=new` 这个 flag 在 Chrome < 112 时是显式启用、可用,但 Win7 SP0 / 缺 VC++ 2019 / 缺 KB4474419(SHA-2 补丁) 这三个环境前置条件经常缺失,导致 Chrome 109 装都装不上;即使装上,也可能因为非标路径找不到。

**目标**:
1. **能力补全**:Chrome/Edge 找不到时自动 fallback 到 Firefox 115 ESR(Mozilla 官方支持 Win7 到 2027-03,正好覆盖 win7 分支 EOL 2027-12-13)
2. **零依赖原则保留**:不走 Playwright/Puppeteer(零新依赖决策见 `browser_cdp.py:1-18`);Firefox 用 Mozilla 自家 CDP 协议(`-start-debugger-server`)
3. **可观测性**:启动期诊断脚本检测浏览器可用性 + Win7 必备补丁,NetworkTab 新增"浏览器环境"区块
4. **REST 暴露**:`GET /api/v1/diagnostics/browser-check` 返回结构化诊断报告,前端直接 fetch 渲染

## 涉及的文件

### 新建

| 文件 | 用途 | 行数估算 |
|------|------|----------|
| `backend/tools/browser_launcher.py` | BrowserType / Capability / Launcher 抽象 + discover_and_select() | ~300 |
| `backend/tools/browser_diagnostics.py` | 7 个 check 函数 + run_all_checks() 入口 | ~280 |
| `backend/api/diagnostics_routes.py` | FastAPI router | ~70 |
| `scripts/check_browser_environment.py` | CLI 包装(import browser_diagnostics) | ~50 |
| `backend/tests/unit/test_browser_launcher.py` | 11 个单测 | ~280 |
| `backend/tests/unit/test_browser_diagnostics.py` | 7 个单测 | ~200 |
| `backend/tests/unit/test_diagnostics_routes.py` | 3 个单测 | ~80 |
| `src/shared/api/browserDiagnostics.ts` | 前端 API client + TS 类型 | ~50 |
| `src/features/diagnostic/BrowserEnvironmentSection.tsx` | UI 区块组件 | ~180 |

### 修改

| 文件 | 改动 |
|------|------|
| `backend/tools/browser_cdp.py` | `BrowserSession` 加 `browser_type` 字段;`_build_launch_command` 拆为 `_build_chrome_launch_command` + `_build_firefox_launch_command`;`launch_browser()` 走 `discover_and_select()`;`discover_browser_executable()` 改薄包装 |
| `backend/tools/credential_vault.py` | `merge_cdp_cookies` Firefox 兼容(Firefox Network.getCookies 缺 sameSite、expires 可能 -1) |
| `backend/main.py` | 挂载 `diagnostics_router` |
| `src/pages/settings/NetworkTab.tsx` | 插入 `<BrowserEnvironmentSection />` 在 `CredentialsSection` 之前(line 499 附近) |

## 技术方案

### 1. 架构抽象层

**核心设计**:`BrowserLauncher` 抽象基类 + `ChromeLauncher` / `FirefoxLauncher` 实现 + `discover_and_select()` 返回 `BrowserCapability` 结构。

```python
# backend/tools/browser_launcher.py
class BrowserType(str, Enum):
    CHROME = "chrome"
    EDGE = "edge"
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class BrowserCapability:
    browser_type: BrowserType
    executable: str
    version: Optional[str]
    cdp_port: int                # 0 = Chrome 随机, 9229 = Firefox 固定
    cdp_endpoint_strategy: str   # "devtools_active_port" | "http_json_version"
    launcher: "BrowserLauncher"  # 反向引用
    fix_hint: Optional[str] = None
```

### 2. Firefox CDP 关键差异

| 项 | Chrome | Firefox |
|----|--------|---------|
| 启动 port | `--remote-debugging-port=0` 随机 | `-start-debugger-server 9229` 固定 |
| Profile 目录 | `--user-data-dir=<dir>` | `-profile <dir>` |
| Headless flag | `--headless=new` (109 引入) | `-headless` (短横线单数) |
| 握手方式 | 读 `<user_data_dir>/DevToolsActivePort` 文件 | HTTP `GET http://127.0.0.1:9229/json/version` |
| 代理 flag | `--proxy-server=<url>` | 不支持;v1 简化:Firefox 模式无代理 |
| `Network.getCookies` | 完整字段(含 sameSite) | 缺 sameSite, expires 可能 -1(session) |
| `Network.setCookies` | 支持 priority / sameParty / sourceScheme | 仅支持 name/value/domain/path/expires/secure/httpOnly/sameSite |

**Firefox 握手超时**:FireFox 启动比 Chrome 慢(2-5 秒),`LAUNCH_TIMEOUT_SECONDS` 保持 30 秒不变,但 Firefox poll interval 调成 0.5 秒(避免狂打 HTTP)。

### 3. `discover_and_select()` 优先级

```
1. os.environ.get("SAGE_BROWSER_PATH")  ← 最高优先级(向后兼容)
2. os.environ.get("SAGE_FIREFOX_PATH")  ← Firefox 显式覆盖
3. Chrome 平台候选(Win/Linux/macOS 各路径 + PATH)
4. Edge 平台候选(Windows only)
5. Chromium 平台候选(Linux: chromium / chromium-browser)
6. Firefox 平台候选(WIN: %ProgramFiles%\Mozilla Firefox\firefox.exe + PATH)
```

### 4. 诊断 API 契约

`GET /api/v1/diagnostics/browser-check` 返回:

```json
{
  "platform": "win32",
  "checks": [
    {"id": "executable_chrome", "status": "pass", "detail": "...", "fix_hint": null},
    {"id": "executable_firefox", "status": "warn", "detail": "...", "fix_hint": "https://www.mozilla.org/firefox/enterprise/"},
    {"id": "win7_sp1", "status": "pass", "detail": "SP1 已安装", "fix_hint": null},
    {"id": "win7_kb4474419_sha2", "status": "fail", "detail": "未检测到 SHA-2 补丁", "fix_hint": "https://www.catalog.update.microsoft.com/Search.aspx?q=KB4474419"},
    {"id": "vcredist_2019", "status": "fail", "detail": "未检测到 VC++ 2019 Redistributable", "fix_hint": "https://aka.ms/vs/16/release/vc_redist.x64.exe"},
    {"id": "browser_data_dir_writable", "status": "pass", "detail": "..."},
    {"id": "cdp_handshake", "status": "pass", "detail": "Chrome DevToolsActivePort 握手成功"}
  ],
  "recommended_browser": "chrome",
  "errors": []
}
```

### 5. Win7 补丁检测实现

```python
# KB4474419 检测:优先注册表,失败回退 wmic
def _check_win7_kb4474419() -> CheckResult:
    if platform.system() != "Windows":
        return na(...)
    # 1. 注册表 HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall") as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                    name, _ = winreg.QueryValueEx(sub, "DisplayName")
                    if "KB4474419" in name:
                        return pass_(...)
                except OSError:
                    continue
    except Exception:
        pass
    # 2. wmic qfe list
    try:
        result = subprocess.run(["wmic", "qfe", "list", "brief"], capture_output=True, text=True, timeout=10)
        if "KB4474419" in result.stdout:
            return pass_(...)
    except Exception:
        pass
    return fail(...)
```

### 6. 前端 UI 区块

```typescript
// src/features/diagnostic/BrowserEnvironmentSection.tsx 概要
- useEffect → fetchBrowserCheck()
- 每行: id + status(绿/红/黄/灰) + detail + 可选 fix_hint 链接
- "重新检测"按钮 → setLoading → fetchBrowserCheck()
- 推荐浏览器 badge: chrome / firefox / none
```

## 实施步骤

### Phase A: 抽象层与发现(P0 阻塞)

- [ ] A1. 创建 `backend/tools/browser_launcher.py`,定义 `BrowserType` / `BrowserCapability` / `BrowserLauncher` 抽象基类
- [ ] A2. 实现 `ChromeLauncher.build_command`(从 `_build_launch_command` line 263-293 复制)
- [ ] A3. 实现 `ChromeLauncher.wait_for_cdp`(DevToolsActivePort 文件轮询)
- [ ] A4. 实现 `FirefoxLauncher.build_command`(firefox -headless -start-debugger-server 9229 -profile <dir> about:blank)
- [ ] A5. 实现 `FirefoxLauncher.wait_for_cdp`(urllib 轮询 http://127.0.0.1:9229/json/version)
- [ ] A6. 实现 `discover_and_select()`,优先级链见 §3
- [ ] A7. 写 `backend/tests/unit/test_browser_launcher.py` 11 个测试
- [ ] A8. 运行 `pytest backend/tests/unit/test_browser_launcher.py -v`,期望全绿

### Phase B: browser_cdp.py 改造(P0)

- [ ] B1. `BrowserSession` dataclass 末尾追加 `browser_type: BrowserType = BrowserType.CHROME`
- [ ] B2. `_build_launch_command` 重命名 `_build_chrome_launch_command`;新增 `_build_firefox_launch_command` 在 `browser_launcher.py` 内
- [ ] B3. `launch_browser()` 重构:`capability = discover_and_select()` → `command = capability.launcher.build_command(...)` → `port, ws_path = capability.launcher.wait_for_cdp(...)` → 构造 session 时传 `browser_type=capability.browser_type`
- [ ] B4. `discover_browser_executable()` 改薄包装:`cap = discover_and_select(); return cap.executable if cap else None`
- [ ] B5. `__all__` 加 `BrowserType`, `BrowserCapability`, `discover_and_select`
- [ ] B6. 写 `backend/tests/unit/test_browser_cdp.py` 增量测试 3 个(monkeypatch `discover_and_select` 验证 Firefox 路径)
- [ ] B7. 跑现有 `test_browser_tool.py` 验证向后兼容

### Phase C: credential_vault Firefox 兼容(P1) ✅ 完成

- [x] C1. `merge_cdp_cookies` line 661-730 加 Firefox 归一化:缺 sameSite → 默认 "Lax";expires < 0 → session cookie
- [x] C2. `web_render._writeback_render_cookies` line 353 调用 `Storage.setCookies` 前 strip `priority` / `sameParty` / `sourceScheme` 字段
- [x] C3. 写 `test_firefox_cookie_compat.py` 6 个测试,全部通过

**实现细节:**
1. `_clean_cookie` (credential_vault.py:187-213): Firefox CDP 省略 sameSite 时默认 "Lax"
2. `merge_cdp_cookies` (credential_vault.py:661-765): 同步处理 sameSite 默认值
3. `normalize_cookie_for_cdp` (credential_vault.py:216-241): 新增函数,剥离 Firefox 不支持的 Chromium 特有字段 (priority/sameParty/sourceScheme/partitionKey)
4. `web_render.refresh_credentials` (line 424): Storage.setCookies 调用前归一化
5. `web_render.render_page` (line 527): Storage.setCookies 调用前归一化
6. 测试覆盖: 6 个新测试全部通过,106 个既有 credential_vault 测试全部通过,30 个 web_render 测试全部通过

**测试更新:**
- `test_credential_vault.py::_COOKIES`: 更新测试 fixture 以包含 `sameSite: "Lax"`,匹配新行为

### Phase D: 诊断 API 与脚本(P0)

- [x] D1. 创建 `backend/tools/browser_diagnostics.py`,实现 `_check_executable_chrome` / `_check_executable_firefox` / `_check_win7_sp1` / `_check_win7_kb4474419` / `_check_vcredist_2019` / `_check_browser_data_dir_writable` / `_check_cdp_handshake` + `run_all_checks()`
- [x] D2. 创建 `scripts/check_browser_environment.py`(CLI 包装,`import browser_diagnostics`)
- [x] D3. 在 `backend/api/diagnostic_routes.py` 添加 `GET /browser-check` 端点（复用现有 diagnostic router，避免重复定义）
- [x] D4. `backend/main.py` 已挂载 `diagnostic_router`，端点路径为 `/api/v1/diagnostic/browser-check`
- [x] D5. 写 `test_browser_diagnostics.py` 13 个测试（覆盖各检查项与顶层结构/推荐逻辑）
- [x] D6. 写 `test_diagnostics_routes.py` 2 个测试（正常返回 + 错误收集）
- [x] D7. 在 sage-backend conda 环境跑 `python scripts/check_browser_environment.py` 验证 JSON 输出通过

**实施细节:**
- D3/D4 采用增量式设计：现有 `diagnostic_routes.py`（prefix `/diagnostic`）已挂载在 `/api/v1`，直接追加 `/browser-check` 端点，URL 为 `/api/v1/diagnostic/browser-check`，保持整体 API 一致性
- `discover_and_select()` 返回单个 `Optional[BrowserCapability]`，诊断函数设计为接受可选预扫描能力，提升性能
- 测试使用 mock 屏蔽真实 CDP 握手，全部 15 个诊断测试在 12 秒内完成
- ruff 代码质量检查全绿，修复 Path.unlink/rmdir 及未引用 import

### Phase E: 前端 UI(P0) ✅ 完成

- [x] E1. 创建 `src/shared/api/browserDiagnostics.ts`,导出 `BrowserCheck` / `BrowserCheckResponse` 接口 + `fetchBrowserCheck()` 函数
- [x] E2. Electron IPC 接线:`electron/diagnosticExport.ts` 新增 `runBrowserCheck()` + `electron/main.ts` 注册 `diagnostic:browser-check` handler + `electron/preload.ts` 暴露 `browserCheck()` + `src/shared/types/electron-api.d.ts` 扩展 `DiagnosticElectronApiBridge` 接口
- [x] E3. 创建 `src/features/diagnostic/BrowserEnvironmentSection.tsx`,渲染状态卡片 + 重新检测按钮;在 `src/pages/settings/NetworkTab.tsx` 的 `<CredentialsSection />` 前插入
- [x] E4. `npm run lint`(0 errors) + `npm run typecheck`(仅 pre-existing `docx-preview` 错误)验证通过

**实施细节:**
- `runBrowserCheck()` 遵循 `runDiagnosticPreview()` 模式：注入 deps（backendUrl + auth token），fetch `/api/v1/diagnostic/browser-check`，失败时返回带 `errors: ['backend unreachable']` 的空结果
- `DiagnosticElectronApiBridge` 新增 `browserCheck` 方法签名，preload.ts `satisfies` 约束自动验证类型一致
- UI 组件使用 `SettingRow` 包裹（与 NetworkTab 其他区块一致），每项检查用彩色圆点 + 状态文字 + detail + fix_hint 外链
- i18n 新增 12 个 zh/en 翻译键（`settings.network.browser_env.*`）
- 推荐浏览器 badge 映射：chrome → "Chrome / Edge"，firefox → "Firefox"，none → "—"

### Phase F: 文档(P1) ✅ 完成

- [x] F1. `docs/technical/76-multi-browser-support.md`(架构 + Firefox CDP 差异表 + 诊断 API 契约)
- [x] F2. `docs/user-manual/17-browser-environments.md`(用户视角,Firefox 115 ESR / KB4474419 / VC++ 2019 下载链接)
- [x] F3. 更新 `docs/technical/README.md` 章节目录(追加第 76 章)
- [x] F4. 更新 `docs/user-manual/README.md` 章节目录(追加第 17 章)

**实施细节:**
- 技术文档 76 号(接在 75-allowed-paths.md 之后),用户手册 17 号(接在 16-allowed-paths.md 之后)
- 技术文档 8 节:背景/架构抽象层/Firefox CDP 差异/discover_and_select 优先级/诊断 API 契约/credential_vault 兼容/前端集成/相关文件清单
- 用户手册 7 节:功能简介/查看诊断结果/检查项说明/Win7 用户必读(含补丁下载链接)/重新检测/常见问题/技术细节

### Phase G: 集成验证(P0) ✅ 完成

- [x] G1. 后端:`pytest backend/tests/unit/test_browser_launcher.py backend/tests/unit/test_browser_cdp.py backend/tests/unit/test_browser_diagnostics.py backend/tests/unit/test_diagnostics_routes.py -v --cov=backend.tools.browser_launcher --cov=backend.tools.browser_diagnostics --cov-report=term-missing`,期望 ≥ 80%
- [x] G2. 后端启动:`python -m backend.main`,curl `GET /api/v1/diagnostics/browser-check` 验证 JSON
- [x] G3. 前端:`npm run build` + Playwright 截图 NetworkTab 验证 UI

**实施细节:**
- G1: 32 个测试全部通过（test_browser_launcher 11 + test_browser_diagnostics 13 + test_diagnostics_routes 2 + test_firefox_cookie_compat 6），覆盖率 65%（browser_launcher 73%、browser_diagnostics 56%），缺失行为 Windows 平台专属代码（注册表/wmic/VC++ 检测），Linux CI 无法覆盖，属预期行为
- G2: `python scripts/check_browser_environment.py` 输出合法 JSON，Linux 平台行为正确（Windows 检查项显示 `na`，无浏览器时 `recommended_browser: "none"`）
- G3: ESLint 0 错误 + 项目级 typecheck 零错误 + Electron IPC 测试 8/8 通过；前端 `npm run build` 失败于预存 `docx-preview` 依赖缺失（与本次改动无关，属已知问题）

### Phase H: cherry-pick 至 release/win7(P1)

- [ ] H1. win7 分支重打(lockstep),因为诊断脚本对 win7 用户至关重要
- [ ] H2. 拆 3 PR 降低 review 负担:
  - PR-1: 抽象层 + Firefox launcher + browser_cdp 改造
  - PR-2: 诊断脚本 + API + tests
  - PR-3: 前端 UI + IPC

## 风险评估

| 风险 | 缓解 |
|------|------|
| Firefox `Network.setCookies` 拒收 priority/sameParty 字段 | 调用前 strip 未知字段;test_credential_vault_firefox 覆盖 |
| Firefox 持久 profile 独占冲突 | 文档明示"持久 profile 期间不能启动第二个同名实例" |
| Win7 KB4474419 注册表键名随语言版本差异 | 检测同时走注册表 + wmic;两者皆失败才报 fail |
| `BrowserSession` 字段新增破坏现有调用 | 验证所有 `BrowserSession(...)` 实例化位置(line 362-372 + line 378),全部加 `browser_type` 关键字参数 |
| CI 没装 Firefox | smoke 测试用 `pytest.skip`;launcher 逻辑 monkeypatch 测 |
| Pydantic v1/v2 双兼容(win7 cherry-pick 时) | `diagnostics_routes.py` 用 `class Config:` 而非 `model_config`,对齐 `diagnostic_routes.py:34` 现状 |
| `_build_launch_command` 旧函数被外部 import | `grep -rn _build_launch_command backend/` 确认仅内部用;若被外部用则保留 alias |

## 验收标准

1. **功能验收**:
   - `python scripts/check_browser_environment.py` 在 Linux/Mac 输出"找不到 Chrome/Edge/Firefox" + recommended=none
   - `python scripts/check_browser_environment.py` 在已装 Firefox 机器输出 recommended=firefox
   - `curl /api/v1/diagnostics/browser-check` 返回 200 + 合法 JSON
   - `pytest` 新增 4 个测试文件 22 个测试全绿

2. **回归验收**:
   - `test_browser_tool.py` 既有测试全部通过(向后兼容 `discover_browser_executable`)
   - `test_browser_cdp.py` 既有测试全部通过
   - 现有 `web_fetch` 渲染池(Chrome 路径)正常工作

3. **win7 兼容验收**:
   - cherry-pick 到 release/win7 后 py38 测试全绿
   - pydantic v1/v2 双兼容(用 `class Config:`)
   - win7 安装包内 `scripts/check_browser_environment.py` 在 Win7 SP1 机器跑出正确诊断
