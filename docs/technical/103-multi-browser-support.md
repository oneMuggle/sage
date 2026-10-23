# 多浏览器支持：架构与诊断

> 本文档描述 Sage 多浏览器自动发现、调度、诊断的完整技术方案。
> 实施计划见 `docs/plans/2026-09-17_multi-browser-support.md`。

## 1. 背景与目标

Win7 安装包用户在使用网页访问 / 登录态保持能力时频繁失败。**根因**：Win7 上 Chrome 最高只支持 109 版本，而 Win7 SP0 / 缺 VC++ 2019 / 缺 KB4474419（SHA-2 补丁）这三个环境前置条件经常缺失，导致 Chrome 109 装都装不上。

**目标**：

1. **能力补全**：Chrome/Edge 找不到时自动 fallback 到 Firefox 115 ESR（Mozilla 官方支持 Win7 到 2027-03，覆盖 win7 分支 EOL 2027-12-13）
2. **零依赖原则保留**：不走 Playwright/Puppeteer；Firefox 用 Mozilla 自家 CDP 协议（`-start-debugger-server`）
3. **可观测性**：启动期诊断脚本检测浏览器可用性 + Win7 必备补丁，NetworkTab 新增"浏览器环境"区块
4. **REST 暴露**：`GET /api/v1/diagnostic/browser-check` 返回结构化诊断报告

## 2. 架构抽象层

核心模块：`backend/tools/browser_launcher.py`

### 2.1 核心类型

```python
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

### 2.2 Launcher 抽象基类

```python
class BrowserLauncher(ABC):
    @abstractmethod
    def build_command(self, ...) -> list[str]: ...

    @abstractmethod
    def wait_for_cdp(self, process, timeout) -> tuple[int, str]: ...
```

- `ChromeLauncher`：从原 `_build_launch_command` 抽出；`wait_for_cdp` 读 `<user_data_dir>/DevToolsActivePort` 文件
- `FirefoxLauncher`：`-headless -start-debugger-server 9229 -profile <dir>`；`wait_for_cdp` 用 urllib 轮询 `http://127.0.0.1:9229/json/version`

## 3. Firefox CDP 关键差异

| 项 | Chrome | Firefox |
|----|--------|---------|
| 启动 port | `--remote-debugging-port=0` 随机 | `-start-debugger-server 9229` 固定 |
| Profile 目录 | `--user-data-dir=<dir>` | `-profile <dir>` |
| Headless flag | `--headless=new`（109 引入）| `-headless`（短横线单数）|
| 握手方式 | 读 `DevToolsActivePort` 文件 | HTTP `GET /json/version` |
| 代理 flag | `--proxy-server=<url>` | 不支持；v1 简化：Firefox 模式无代理 |
| `Network.getCookies` | 完整字段（含 sameSite）| 缺 sameSite，expires 可能 -1（session）|
| `Network.setCookies` | 支持 priority / sameParty / sourceScheme | 仅支持 name/value/domain/path/expires/secure/httpOnly/sameSite |

**Firefox 握手超时**：Firefox 启动比 Chrome 慢（2-5 秒），`LAUNCH_TIMEOUT_SECONDS` 保持 30 秒不变，但 Firefox poll interval 调成 0.5 秒（避免狂打 HTTP）。

## 4. `discover_and_select()` 优先级

```
1. os.environ.get("SAGE_BROWSER_PATH")   ← 最高优先级（向后兼容）
2. os.environ.get("SAGE_FIREFOX_PATH")   ← Firefox 显式覆盖
3. Chrome 平台候选（Win/Linux/macOS 各路径 + PATH）
4. Edge 平台候选（Windows only）
5. Chromium 平台候选（Linux: chromium / chromium-browser）
6. Firefox 平台候选（WIN: %ProgramFiles%\Mozilla Firefox\firefox.exe + PATH）
```

每个候选都检查 `Path.is_file()` + `os.access(X_OK)`（Windows 跳过 X_OK）。第一个通过的返回 `BrowserCapability`；全部不通过返回 `None`。

## 5. 诊断 API 契约

### 5.1 端点

`GET /api/v1/diagnostic/browser-check`

### 5.2 响应体

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

### 5.3 检查项 ID 与状态

| ID | 检查内容 | 非 Windows 行为 |
|----|----------|----------------|
| `executable_chrome` | Chrome/Edge/Chromium 是否可执行 | 同 |
| `executable_firefox` | Firefox 是否可执行 | 同 |
| `win7_sp1` | Windows 版本 ≥ 6.1 SP1 | `na` |
| `win7_kb4474419_sha2` | 注册表 + wmic 检测 SHA-2 补丁 | `na` |
| `vcredist_2019` | 注册表检测 VC++ 2019 Redistributable | `na` |
| `browser_data_dir_writable` | `~/.sage/browser-data/` 可写 | 同 |
| `cdp_handshake` | CDP 握手（DevToolsActivePort 或 HTTP /json/version） | 同 |

状态枚举：`pass` / `warn` / `fail` / `na`

### 5.4 推荐浏览器逻辑

```
1. Chrome 可用 → "chrome"
2. Firefox 可用 → "firefox"
3. 都不可用 → "none"
```

## 6. credential_vault Firefox 兼容

Firefox CDP 的 cookie 字段与 Chrome 有差异，`credential_vault.py` 新增 `normalize_cookie_for_cdp()` 函数：

- 剥离 Firefox 不支持的 Chromium 特有字段：`priority` / `sameParty` / `sourceScheme` / `partitionKey`
- `merge_cdp_cookies` 处理 Firefox 省略 sameSite 时默认 "Lax"
- `web_render.refresh_credentials` 和 `render_page` 调用 `Storage.setCookies` 前归一化

## 7. 前端集成

### 7.1 IPC 链路

```
renderer → window.electronAPI.diagnostic.browserCheck()
         → ipcRenderer.invoke('diagnostic:browser-check')
         → main.ts ipcMain.handle → runBrowserCheck()
         → fetch GET /api/v1/diagnostic/browser-check
         → 返回 BrowserCheckResult
```

### 7.2 UI 组件

`src/features/diagnostic/BrowserEnvironmentSection.tsx` 渲染在 Settings > Network Tab：

- 推荐浏览器 badge（chrome → "Chrome / Edge"，firefox → "Firefox"，none → "—"）
- 每项检查：彩色圆点（pass=绿 warn=黄 fail=红 na=灰）+ 状态文字 + detail + fix_hint 外链
- "重新检测"按钮触发 refetch

### 7.3 i18n 键

`settings.network.browser_env.*`（12 个键，zh/en 同步）

## 8. 相关文件清单

| 文件 | 职责 |
|------|------|
| `backend/tools/browser_launcher.py` | BrowserType / Capability / Launcher 抽象 + discover_and_select() |
| `backend/tools/browser_cdp.py` | BrowserSession 加 browser_type 字段；launch_browser() 走 discover_and_select() |
| `backend/tools/browser_diagnostics.py` | 7 个 check 函数 + run_all_checks() 入口 |
| `backend/tools/credential_vault.py` | normalize_cookie_for_cdp() + Firefox cookie 兼容 |
| `backend/api/diagnostic_routes.py` | GET /browser-check 端点 |
| `scripts/check_browser_environment.py` | CLI 包装 |
| `electron/diagnosticExport.ts` | runBrowserCheck() 共享逻辑 |
| `src/shared/api/browserDiagnostics.ts` | 前端 API client |
| `src/features/diagnostic/BrowserEnvironmentSection.tsx` | UI 组件 |
