# 165 Firefox 浏览器兜底（多浏览器支持）

> 对齐 `release/win7` 的 Firefox 兼容层（win7 §103 的 main 侧移植）。
> main 侧的启动器实现位于 `backend/tools/browser_cdp.py`（win7 为独立的
> `backend/tools/browser_launcher.py`）。

## 背景

Sage 的浏览器通道（JS 渲染 / 受控浏览器 / 登录任务）默认驱动 Chromium 系
浏览器（Chrome / Edge / Chromium）。Windows 7 用户常遇到两类无法安装新
Chrome 的情况：

1. Win7 上 Chrome 最高只能装到 109，部分站点按 UA 拒绝旧内核；
2. Win7 SP0 / 缺 VC++ 2019 运行库 / 缺 KB4474419（SHA-2 补丁）时 Chrome
   安装器直接失败。

Firefox 115 ESR 持续支持 Win7 至 2027-03，覆盖 win7 分支的 EOL
（2027-12-13），因此作为第三选择提供 CDP 兜底。

## 发现优先级

`browser_cdp.discover_browser_executable()` 的顺序：

1. `SAGE_BROWSER_PATH` 环境变量（显式文件路径）；
2. `SAGE_FIREFOX_PATH` 环境变量（Firefox 专用别名，排在通用覆盖之后）；
3. 设置页选择（`browser_path`；`(embedded)` 哨兵指向内置浏览器）；
4. 内置浏览器兜底（Electron 注入 `SAGE_EMBEDDED_BROWSER*` 时）；
5. 平台扫描：
   - Windows：Chrome/Edge 常见安装目录 → Firefox 常见安装目录
     （`ProgramFiles` / `ProgramFiles(x86)` 下的 `Mozilla Firefox\firefox.exe`）
     → `PATH`（chrome / msedge / firefox）；
   - Linux/WSL：`PATH` 中的 Chromium 系命令 → `firefox`；
   - macOS：`/Applications` 下的 Chrome / Edge / Chromium → Firefox.app。

Chromium 系永远优先；Firefox 仅在全部 Chromium 来源缺失时兜底。设置页
`GET /api/v1/diagnostic/browser/list` 同步把 Firefox 列入候选（显示名
"Mozilla Firefox"），`isDefault` 仍以发现结果为准。

## 启动差异（Firefox vs Chromium）

| 维度 | Chromium | Firefox |
| --- | --- | --- |
| 调试端口 | `--remote-debugging-port=0`（随机） | `-start-debugger-server 9229`（固定） |
| 用户目录 | `--user-data-dir=<dir>` | `-profile <dir>` + `-no-remote` |
| 无头模式 | `--headless=new`（<109 降级 `--headless`） | `-headless` |
| CDP 握手 | 轮询 `DevToolsActivePort` 文件 | 轮询 `http://127.0.0.1:9229/json/version`，解析 `webSocketDebuggerUrl` 的 path+query |
| 轮询间隔 | 0.2s | 0.5s（Firefox 调试服务就绪更慢） |
| 代理开关 | `--proxy-server=` | **v1 不支持**（需写 profile prefs） |

`_build_launch_command()` 按可执行文件名推断类型（`_infer_browser_type`，
路径含 `firefox` → `BrowserType.FIREFOX`）。Firefox 分支忽略
`browser_proxy_flag()`，`launch_browser()` 对 Firefox 走
`_wait_for_firefox_cdp()` 握手并在会话上记录 `browser_type=firefox`；
握手失败时通过 `_terminate_session()` 清理进程与临时 profile。

## Cookie 兼容

`backend/tools/credential_vault.py:normalize_cookie_for_cdp()` 在向浏览器
注入 cookie 前剥离 Firefox `Storage.setCookies` 不接受的 Chromium 特有字段
（`priority` / `sameParty` / `sourceScheme` / `partitionKey`），并在缺省时
补 `sameSite=Lax`。`web_render` 与 `browser_account_service` 的注入路径均
已经过该归一化；`merge_cdp_cookies()` 将 `expires=-1` 识别为 session cookie。

## 限制

- **固定端口 9229**：同一时刻只能有一个 Firefox 调试实例；并发会话会端口
  冲突（Chromium 的随机端口无此问题）。
- **无代理支持**：Firefox v1 不跟随 Sage 的浏览器代理设置，代理环境下
  该通道可能不通。
- **版本探测**：`chromium_major_version()` 的版本目录扫描对 Firefox 不适用，
  设置页列表的 Firefox 版本可能为空。

## 测试

- `backend/tests/unit/test_browser_discovery.py`：Firefox 环境变量优先级、
  候选目录、启动命令分支；
- `backend/tests/unit/test_browser_firefox.py`：`/json/version` 握手
  （成功 / 重试 / 进程提前退出 / 超时）与 `launch_browser` 接入、失败清理；
- `backend/tests/unit/test_firefox_cookie_compat.py`：cookie 归一化与
  session cookie 合并（与 win7 同名用例对齐）。
