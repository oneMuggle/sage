# 设置-网络页：浏览器列表 401、Win7 老浏览器可用性与实例上限自愈

> 实施中请逐项勾选本文件的任务清单；完成后按项目规则并入 `docs/technical/`，删除本计划。

**目标**：修复设置-网络页三个用户可见问题——(1) HTTP 401 提示；(2) 明明安装了 Edge/Chrome 却显示「未发现可用浏览器」；(3) 登录站点报「浏览器实例数已达上限 4」且关闭浏览器后不恢复、用户无 `browser_close` 可用。同时让用户选择的浏览器在真实启动链路生效，并消除 Windows 下版本探测的副作用。

**分支**：`fix/settings-network-browser-list`（基于 `release/win7`，合并后 cherry-pick 到 `main`）

**worktree**：`.worktrees/fix-settings-network-browser-list`（后端 8942 / 前端 1597）

## 背景与根因（已验证）

### 1. HTTP 401（P0）

- `src/shared/api/browserSettingsClient.ts` 用裸 `fetch` 请求 `/api/v1/diagnostic/browser/*`，不带 `Authorization`；注释声称走 `electronAPI.backendRequest` 但实现没有。
- 后端 `LocalAuthMiddleware`（`backend/api/local_auth.py`）对非公开路径一律 401；实测无 token 返回 `{"detail":"本地授权凭据无效或缺失"}`。
- 正确模式已存在于 `webAccessClient.requestJson`：Electron 下走主进程 IPC 中继（注入 `X-Sage-Local-Authorization`、解析真实端口），浏览器 dev 回退 Vite 代理。
- 同页「高级」区域的 `NetworkCredentialsSection.tsx`（凭据/指标/配置，8 处裸 `fetch`）与硬编码 8765 端口同病。

### 2. 「未发现可用浏览器」（P0，与 1 同根）

- `BrowserSettingsSection.tsx`：请求失败后 `browsers` 保持 `[]`，组件把「加载失败」渲染成「未发现可用浏览器」空态。
- 后端列表逻辑（`diagnostic_routes._discover_all_browsers`）是纯路径扫描，**没有版本门槛**——Edge 100 / Chrome 107 在 `Program Files (x86)` / `Program Files` / `LocalAppData` 下会被发现。修好鉴权后即可正常列出。

### 3. 内置浏览器未暴露 + 用户选择不生效（P1）

- Win7（NT 6.1）Electron 注入 `SAGE_EMBEDDED_BROWSER=1`（`electron/main.ts:3449-3457`），后端 `embeddedAvailable=true`，但 `BrowserSettingsSection` 从不渲染「Sage 内置浏览器」选项（i18n 文案已存在却未使用）。
- `launch_browser()` 走 `browser_launcher.discover_and_select()`，该函数不读用户设置 `browser_path`；且 `SAGE_EMBEDDED_BROWSER` 优先级高于磁盘浏览器 → Win7 上即使选择了 Chrome/Edge 也不会生效。

### 4. Windows 版本探测副作用（P1）

- `diagnostic_routes._get_version` 执行 `chrome.exe --version`。Windows 上该命令不输出（项目在 `http_factory._probe_chrome_major` 中已明确处理），可能弹出浏览器窗口并白等 5s 超时。
- `--headless=new` 需要 Chrome 109+（`browser_cdp.py:545-547` 注释自述）；Chrome 107 / Edge 100 需要降级 `--headless`。

### 5. 浏览器实例上限不恢复（P0，用户 2026-11-17 补充）

- `BrowserSessionManager.register`（`browser_cdp.py:210-230`）直接按 `len(self._sessions)` 判上限：
  - **已退出实例（用户关窗/崩溃）仍占名额**——`require()` 才清理死实例，`register()` 不清理 → 关掉浏览器后依旧「已达上限」。
  - **内置浏览器（EMBEDDED）会话被重复计数**：Win7 上所有会话共享 Electron 的同一个 Chromium 进程，按进程数的上限本不应按逻辑会话计数。
  - **渲染池会话占满名额**：`render_pool_size` 可配到 4（设置页高级区域），4 个渲染池实例就把登录窗口的名额占满。
- 错误文案「请先用 browser_close 关闭」面向 agent；设置页用户没有该工具，提示不可操作。

## 涉及文件

| 文件 | 变更 |
|---|---|
| `src/shared/api/webAccessClient.ts` | 导出 `requestJson`（补 `detail` 错误字段） |
| `src/shared/api/browserSettingsClient.ts` | 改走 `requestJson`，删除裸 fetch |
| `src/pages/settings/BrowserSettingsSection.tsx` | 错误态/重试、内置浏览器选项 |
| `src/pages/settings/NetworkCredentialsSection.tsx` | 8 处裸 fetch 迁移到 `requestJson`，删除本地 `webAccessApiUrl` |
| `src/shared/lib/i18n/locales/zh/chatAndSider.ts` | 新增 `load_failed` / `retry` 文案 |
| `src/shared/lib/i18n/locales/en/chatAndSiderBrowserExtension.ts` | 同上（英文） |
| `backend/api/diagnostic_routes.py` | 版本探测复用版本目录扫描；`set_browser_path` 接受 `(embedded)` 哨兵 |
| `backend/tools/browser_cdp.py` | 用户选择哨兵、启动链路优先级、headless 降级、会话上限自愈 |
| `backend/tools/browser_launcher.py` | `chromium_major_version` / `headless_flag` / `discover_and_select(user_path)` |
| 测试 | 见各任务 |

## 全局约束

- **py38 兼容**（release/win7 后端）：使用 `typing.Optional/List/Dict`，禁 PEP 604 `X | Y` 与运行时内置泛型。
- 前端新增 UI 元素必须带 `data-testid`；不引入 `console.log`。
- i18n 中英文案同步新增（`TranslationKey` 由 zh 字典推导）。
- 不改 `backend/requirements*.txt`。
- 提交信息用 conventional commits；每任务独立提交。

---

## Task 0：基线记录

- [x] 前端基线：`npx vitest run src/pages/settings/__tests__/NetworkTab.test.tsx src/shared/api/__tests__/webAccessClient.test.ts`
- [x] 后端基线：`/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_browser_launcher.py backend/tests/unit/test_browser_tool.py backend/tests/unit/test_browser_cdp_external.py backend/tests/api/test_diagnostic_browser_health.py -q`
- [x] 记录通过数（Arena 系列已知 flaky，不纳入本次基线）

## Task 1：前端鉴权桥（browserSettingsClient → requestJson）

**Files**：`src/shared/api/webAccessClient.ts`、`src/shared/api/browserSettingsClient.ts`、`src/shared/api/__tests__/browserSettingsClient.test.ts`（新建）

**Interfaces**：
- Produces：`requestJson<T>(path: string, init?: RequestInit): Promise<T>`（从 webAccessClient 导出；Electron 走 `window.electronAPI.backendRequest`，浏览器 dev 走同源 fetch）

- [x] **Step 1：写失败测试** `src/shared/api/__tests__/browserSettingsClient.test.ts`

```ts
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchBrowserList, setBrowserPath } from '../browserSettingsClient';

function stubElectron(bridge: ReturnType<typeof vi.fn>): void {
  (window as unknown as { electronAPI?: unknown }).electronAPI = { backendRequest: bridge };
}

afterEach(() => {
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
  vi.unstubAllGlobals();
});

describe('browserSettingsClient', () => {
  it('routes list requests through the Electron main relay (auth injection)', async () => {
    const bridge = vi.fn(async () => ({
      browsers: [],
      userConfigured: null,
      embeddedAvailable: true,
    }));
    stubElectron(bridge);
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await fetchBrowserList();

    expect(bridge).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/diagnostic/browser/list',
      body: undefined,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends browser selection as a JSON body through the relay', async () => {
    const bridge = vi.fn(async () => ({ success: true }));
    stubElectron(bridge);

    await setBrowserPath('(embedded)');

    expect(bridge).toHaveBeenCalledWith({
      method: 'PUT',
      path: '/api/v1/diagnostic/browser/path',
      body: { path: '(embedded)' },
    });
  });

  it('propagates relay failures so the UI can render an error state', async () => {
    const bridge = vi.fn(async () => {
      throw new Error('Backend request failed: 401');
    });
    stubElectron(bridge);

    await expect(fetchBrowserList()).rejects.toThrow('401');
  });
});
```

- [x] **Step 2：运行确认失败**：`npx vitest run src/shared/api/__tests__/browserSettingsClient.test.ts`
- [x] **Step 3：实现**
  - `webAccessClient.ts`：`async function requestJson` 前加 `export`；失败分支改为 `throw new Error(payload?.error || payload?.detail || \`HTTP ${response.status}\`)`。
  - `browserSettingsClient.ts` 重写为：

```ts
/**
 * 浏览器选择 API 客户端。
 *
 * 与 webAccessClient 同口径：Electron 走主进程 backendRequest 中继（注入
 * 本地 bearer token；渲染层裸 fetch 会被 LocalAuthMiddleware 401），
 * 浏览器 dev 回退 Vite 代理。
 */
import { requestJson } from './webAccessClient';

export interface DiscoveredBrowser {
  name: string;
  path: string;
  version: string | null;
  isDefault: boolean;
}

export interface BrowserListResponse {
  browsers: DiscoveredBrowser[];
  userConfigured: string | null;
  embeddedAvailable: boolean;
}

export async function fetchBrowserList(): Promise<BrowserListResponse> {
  return requestJson<BrowserListResponse>('/api/v1/diagnostic/browser/list');
}

export async function setBrowserPath(path: string): Promise<{ success: boolean; error?: string }> {
  return requestJson('/api/v1/diagnostic/browser/path', {
    method: 'PUT',
    body: JSON.stringify({ path }),
  });
}
```

- [x] **Step 4：运行确认通过**（同上命令）
- [x] **Step 5：提交** `fix(settings): 浏览器列表客户端改走主进程鉴权中继`

## Task 2：BrowserSettingsSection 错误态 / 空态分离 + 重试

**Files**：`src/pages/settings/BrowserSettingsSection.tsx`、zh/en i18n、`src/pages/settings/__tests__/NetworkTab.test.tsx`

- [x] **Step 1：i18n 新增**
  - `zh/chatAndSider.ts`（`settings.network.browser.none_found` 附近）：
    `'settings.network.browser.load_failed': '浏览器列表加载失败，请重试。'`、`'settings.network.browser.retry': '重试'`
  - `en/chatAndSiderBrowserExtension.ts`：
    `'settings.network.browser.load_failed': 'Failed to load the browser list. Please retry.'`、`'settings.network.browser.retry': 'Retry'`
- [x] **Step 2：写失败测试**（NetworkTab.test.tsx 新增两个 case）：
  1. `fetchBrowserList` reject → 渲染 `browser-load-error`、点击 `browser-retry` 后第二次 resolve → 列出浏览器，且全程不出现 `none_found` 文案。
  2. `fetchBrowserList` resolve `{browsers: [], embeddedAvailable: true}` → 不显示 `none_found`（空态仅在 `!embeddedAvailable` 时出现）。
- [x] **Step 3：实现**
  - `BrowserSettingsSection` 增加 `const [error, setError] = useState<string | null>(null);`
  - `load()`：开头 `setLoading(true); setError(null);`；catch 中 `setError(message)` 并 `toast.error(t('settings.network.browser.load_failed'))`（不再 toast 裸 `HTTP 401`）。
  - 渲染顺序：`error ?` 错误块（`data-testid="browser-load-error"`，展示 `t('...load_failed')` + 详情 + `data-testid="browser-retry"` 按钮）`: browsers.length === 0 && !embeddedAvailable ? 空态 : 列表`。
- [x] **Step 4：运行** `npx vitest run src/pages/settings/__tests__/NetworkTab.test.tsx` 确认通过
- [x] **Step 5：提交** `fix(settings): 浏览器列表区分加载失败与未发现并支持重试`

## Task 3：CredentialsSection 迁移鉴权桥

**Files**：`src/pages/settings/NetworkCredentialsSection.tsx`、`__tests__/NetworkCredentialsSection.p143.test.ts`（确认仍通过）

- [x] **Step 1：实现**（机械替换，行为保持：失败时沿用原 fallback 值）
  - 删除本地 `webAccessApiUrl`（含 8765 硬编码），`import { requestJson } from '../../shared/api/webAccessClient';`
  - `reload()`：`requestJson<{credentials?: CredentialRecord[]}>('/api/v1/web-access/credentials').then(...).catch(() => setCreds([]))`
  - 其余 7 处逐一同法替换（browser health / metrics / config PUT / metrics reset / delete / header POST / cookie POST）。header/cookie 的「响应 ok 判断」改为 `try { await requestJson(...); ... } catch { toast.error(...) }`（保持原语义）。
- [x] **Step 2：运行** `npx vitest run src/pages/settings/__tests__/NetworkCredentialsSection.p143.test.ts` 与 `npx tsc --noEmit`
- [x] **Step 3：提交** `fix(settings): 高级凭据区域改走主进程鉴权中继`

## Task 4：「Sage 内置浏览器」选项（前后端哨兵）

**Interfaces**：
- `EMBEDDED_EXECUTABLE = "(embedded)"`（已存在于 `browser_launcher.py`；作为 `browser_path` 哨兵值）

- [x] **Step 1：后端测试**（`backend/tests/unit/test_browser_cdp_external.py` 或新增用例）
  ```python
  def test_get_user_browser_path_accepts_embedded_sentinel(monkeypatch):
      from backend.tools import browser_cdp
      monkeypatch.setattr(
          "backend.data.settings_repo.SettingsRepository.get",
          lambda self, key: "(embedded)" if key == "browser_path" else None,
      )
      assert browser_cdp._get_user_browser_path() == "(embedded)"

  def test_set_browser_path_accepts_embedded_sentinel(client):
      # 参照 test_diagnostic_browser_health.py 的 async client fixture 用法
      ...
  ```
  第二个用例用 `await client.put("/api/v1/diagnostic/browser/path", json={"path": "(embedded)"})` 断言 `success is True`；不存在的路径仍返回 `success is False`。
- [x] **Step 2：实现后端**
  - `browser_cdp._get_user_browser_path()`：`if stored == EMBEDDED_EXECUTABLE: return EMBEDDED_EXECUTABLE`（先于 `is_file` 检查）。
  - `diagnostic_routes.set_browser_path`：`if path and path != EMBEDDED_EXECUTABLE and not Path(path).is_file(): return {"success": False, ...}`。
- [x] **Step 3：前端**（`BrowserSettingsSection`）
  - 常量 `const EMBEDDED_PATH = '(embedded)';`
  - `embeddedSelected = userConfigured === EMBEDDED_PATH || (!userConfigured && embeddedAvailable)`
  - 列表末尾渲染内置浏览器按钮（`data-testid="embedded-browser-option"`）：标题 `t('settings.network.browser.embedded')`，副文案 `t('settings.network.browser.embedded_hint')`；无用户配置时追显 `(t('settings.network.browser.system_default'))`；点击 `handleSelect(EMBEDDED_PATH)`。
  - `isSelected()` 对 `EMBEDDED_PATH` 返回 `embeddedSelected`。
- [x] **Step 4：测试**
  - 后端两条用例通过；前端 NetworkTab 新增：`embeddedAvailable: true, browsers: []` → 显示内置选项并能选中（`setBrowserPath` 收到 `(embedded)`）。
- [x] **Step 5：提交** `feat(settings): 展示并支持选择 Sage 内置浏览器`

## Task 5：启动链路尊重用户选择

**优先级（产品已确认）**：`SAGE_BROWSER_PATH` / `SAGE_FIREFOX_PATH` 环境变量 > 用户设置 `browser_path` > 内置浏览器（Win7 兜底）> 系统扫描。

- [x] **Step 1：失败测试**（`backend/tests/unit/test_browser_launcher.py`）
  ```python
  def test_discover_and_select_user_path_beats_embedded(monkeypatch, tmp_path):
      fake = tmp_path / "chrome.exe"
      fake.write_text("bin")
      monkeypatch.setenv("SAGE_EMBEDDED_BROWSER", "1")
      monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_PORT", "9411")
      monkeypatch.setenv("SAGE_EMBEDDED_BROWSER_TOKEN", "tok")
      monkeypatch.delenv("SAGE_BROWSER_PATH", raising=False)
      cap = discover_and_select(str(fake))
      assert cap.browser_type == BrowserType.CHROME
      assert cap.executable == str(fake)
      assert discover_and_select("(embedded)").browser_type == BrowserType.EMBEDDED

  def test_discover_and_select_env_path_beats_user_path(monkeypatch, tmp_path):
      env_exe = tmp_path / "env-chrome"; env_exe.write_text("bin")
      user_exe = tmp_path / "user-chrome"; user_exe.write_text("bin")
      monkeypatch.setenv("SAGE_BROWSER_PATH", str(env_exe))
      assert discover_and_select(str(user_exe)).executable == str(env_exe)
  ```
- [x] **Step 2：实现**
  - `browser_launcher.py`：把 `_discover_from_env()` 拆为 `_discover_env_browser_path()`（SAGE_BROWSER_PATH → SAGE_FIREFOX_PATH）与既有 `_discover_embedded()`；新增 `_discover_user_path(user_path)`（`(embedded)` → `_discover_embedded()`；文件存在 → `_create_capability(...)`）；
    `discover_and_select(user_path: Optional[str] = None)` 顺序：env 路径 → 用户选择 → 内置 → Windows → Darwin → PATH。
  - `browser_cdp.py`：
    - `discover_browser_executable()` 简化为 `cap = discover_and_select(_get_user_browser_path()); return cap.executable if cap else None`（保持「环境变量 > 用户 > 内置 > 扫描」）。
    - `launch_browser()` 中 `cap = discover_and_select(_get_user_browser_path())`。
- [x] **Step 3：运行** launcher / cdp 相关测试，确认通过且不破坏既有 env 用例
- [x] **Step 4：提交** `feat(browser): 启动链路按 环境变量>用户选择>内置兜底>系统扫描 选浏览器`

## Task 6：Windows 版本探测 + headless 版本降级

- [x] **Step 1：失败测试**（`test_browser_launcher.py`）
  ```python
  def test_chromium_major_version_reads_version_dirs(tmp_path):
      exe_dir = tmp_path / "Application"; exe_dir.mkdir()
      (exe_dir / "100.0.4896.60").mkdir()
      (exe_dir / "107.0.5304.87").mkdir()
      exe = exe_dir / "msedge"; exe.write_text("")
      assert chromium_major_version(str(exe)) == 107

  def test_headless_flag_falls_back_for_legacy_major(tmp_path):
      exe_dir = tmp_path / "Application"; exe_dir.mkdir()
      (exe_dir / "100.0.4896.60").mkdir()
      exe = exe_dir / "msedge"; exe.write_text("")
      assert headless_flag(str(exe)) == "--headless"

  def test_headless_flag_uses_new_for_recent_or_unknown(tmp_path):
      assert headless_flag(str(tmp_path / "missing")) == "--headless=new"
  ```
- [x] **Step 2：实现**
  - `browser_launcher.py`：`_VERSION_DIR_RE = re.compile(r"(\d+)\.\d+\.\d+\.\d+")`、`NEW_HEADLESS_MIN_MAJOR = 109`；
    `chromium_major_version(executable)`：先扫 exe 同级 `X.Y.Z.W` 目录取最大值；Windows 到此为止（不执行 exe）；POSIX 再回退 `--version`。
    `headless_flag(executable)`：major 已知且 `< 109` → `"--headless"`，否则 `"--headless=new"`。
  - `ChromeLauncher.build_command` 与 `browser_cdp._build_launch_command` 的 headless 分支统一改用 `headless_flag(executable)`。
  - `diagnostic_routes._discover_all_browsers._get_version` 改为调用 `chromium_major_version` 并返回 `str(major)`，删除对 `--version` 的调用与 5s 超时路径。
- [x] **Step 3：运行** `test_browser_launcher.py`、`test_browser_tool.py -k launch_command`、`test_http_factory.py -k LaunchCommand`、`test_diagnostic_browser_health.py` 确认通过
- [x] **Step 4：提交** `fix(browser): Windows 版本目录探测与旧内核无头降级`

## Task 7：浏览器会话上限自愈

**Files**：`backend/tools/browser_cdp.py`（`BrowserSessionManager`）、`backend/tests/unit/test_browser_tool.py`

- [x] **Step 1：失败测试**（test_browser_tool.py，复用 `_fake_session`，扩展 `browser_type` 参数）

```python
def test_manager_prunes_dead_sessions_before_cap():
    manager = BrowserSessionManager()
    for i in range(browser_cdp.MAX_BROWSER_SESSIONS):
        manager.register(_fake_session(f"dead{i}", alive=False))
    fresh = _fake_session("fresh", alive=True)
    manager.register(fresh)  # 死实例不占名额
    assert manager.get("fresh") is fresh

def test_manager_excludes_embedded_from_cap():
    manager = BrowserSessionManager()
    for i in range(browser_cdp.MAX_BROWSER_SESSIONS + 1):
        manager.register(_fake_session(f"emb{i}", browser_type=BrowserType.EMBEDDED))
    manager.register(_fake_session("chrome", browser_type=BrowserType.CHROME))
    assert manager.get("chrome") is not None

def test_manager_evicts_render_pool_before_cap_error():
    manager = BrowserSessionManager()
    for i in range(browser_cdp.MAX_BROWSER_SESSIONS):
        manager.register(_fake_session(f"render-pool-{i}", alive=True))
    manager.register(_fake_session("login-default", alive=True))
    assert manager.get("login-default") is not None
    assert manager.count() <= browser_cdp.MAX_BROWSER_SESSIONS
```

- [x] **Step 2：实现**（`BrowserSessionManager`）
  - `__init__` 增加 `threading.Lock()`。
  - 新增 `_counted_locked()`：计数时排除 `BrowserType.EMBEDDED`（Electron 共享同一 Chromium 进程，见 `_EmbeddedProcess`）与 `EXTENSION_BROWSER_ID`（原有豁免）。
  - `register()` 在锁内按序：弹出同 id 旧实例 → **回收 `is_alive() == False` 的死实例** → 计数超限时**按插入序让位渲染池实例**（id == `RESERVED_BROWSER_ID` 或以 `RESERVED_BROWSER_ID + "-"` 开头，懒重建，下次渲染自动恢复）→ 仍超限则抛错。所有 `_terminate_session` 在锁外统一执行（`try/finally` 保证抛错路径也回收已弹出实例）。
  - 错误文案改为面向用户可操作：`f"浏览器实例数已达上限 {MAX_BROWSER_SESSIONS}：请关闭 Sage 打开的浏览器窗口后重试（对话中可调用 browser_close 关闭实例）"`。
- [x] **Step 3：运行** `pytest backend/tests/unit/test_browser_tool.py -q`（含既有 `test_manager_cap` / `test_manager_require_and_dead_session_eviction`）
- [x] **Step 4：提交** `fix(browser): 会话上限先回收死实例并让位渲染池`

## Task 8：全量验证与 PR

- [x] `npx tsc --noEmit`
- [x] `npx eslint` 改动文件（`npm run lint` 全量可留到 CI）
- [x] `npx vitest run src/pages/settings src/shared/api/__tests__`（479 passed）；全量 `npx vitest run`：1426 文件 / 7445 passed / 6 skipped
- [x] py38 后端目标测试 + `ruff check backend/tools/browser_cdp.py backend/tools/browser_launcher.py backend/api/diagnostic_routes.py`
- [x] `node scripts/architecture-check.mjs`（行数棘轮）
- [ ] 本地手工验证（Electron dev，worktree 端口 8942/1597）：设置-网络列出浏览器、无 401、内置选项可选、高级区域可加载；点击登录不再报上限
- [ ] push + `gh pr create`（目标 `release/win7`，说明根因与验收点）
- [ ] 合并后 cherry-pick 到 `main` 并处理 py310/pydantic2 差异（本次改动后端不涉及 pydantic 模型变更，预期零冲突）

## 风险与依赖

| 风险 | 缓解 |
|---|---|
| 用户删除/未安装浏览器后 `browser_path` 残留无效路径 | `_get_user_browser_path` 已做 `is_file()` 校验，无效自动回落 |
| 让位渲染池实例导致渲染短暂变慢 | 渲染池懒重建，仅在登录需要名额时触发一次重建 |
| embedded 不计入上限导致真实进程数是否失控 | embedded 共享 Electron 单进程，进程数不会因逻辑会话增加 |
| `--headless` 旧模式在 Chrome 107/Edge 100 的行为 | 需 Win7 真机冒烟一次（用户环境）；失败则回退「旧内核明确报错并提示升级」 |
| 双分支差异 | 已避开 pydantic 模型改动；cherry-pick 后跑 main 的 py310 测试 |
