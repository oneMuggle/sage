# release/win7 — Sage 长期 Windows 7 维护分支

> 本分支冻结 Tauri 1.6 + Python 3.8，专门维护 **Windows 7 SP1 x64** 兼容性。
> 起点 commit：`7d3c5c0`（main 上 Tauri 2 升级之前）。

## 适用范围

| 项 | 状态 |
|---|---|
| 支持的 Windows 版本 | **Windows 7 SP1 x64**（Win7 x86 已知不兼容，见 docs/user-manual/01-desktop.md） |
| Tauri 版本 | 1.6.x（冻结，**不再升级**） |
| Python 版本 | **3.8.x**（最后支持 Win7 的版本） |
| WebView2 Runtime | v109（最后支持 Win7 的版本，离线捆绑） |
| 桌面端 Node | v20 LTS |
| 后端 Node | 不适用（仅 Tauri shell 用） |

## 与 main 的关系

- **main** 持续迭代，Tauri 2.x / Python 3.11+ / Win10+/macOS/Linux。
- **本分支** 只接受：安全修复、Win7 相关 bug、CVE 紧急修复。
- **不接受**：新功能、依赖大版本升级、性能重构、a11y 改进。
- 同步方式：单 commit cherry-pick，commit message 加 `(cherry picked from main commit XXX)`。

## 升级/安全策略

- Tauri 1.6 已 EOL（2024 年 10 月），**未来安全 CVE 不会得到官方修复**。
- 建议商业承诺期：1-2 年。逾期应迁移用户到 Web 客户端（浏览器访问 FastAPI 后端）。
- Python 3.8 已 EOL（2024 年 10 月），同上。
- WebView2 v109 不再获得微软安全更新（微软官方支持止于 2023 年 2 月）。

## 长期路线图（1-2 年后 Web 化迁移）

**为什么是 1-2 年**：本分支技术栈（Tauri 1.6 + Python 3.8 + WebView2 v109）已 EOL，建议商业承诺期不超过 24 个月。逾期后：

1. **Phase A — 准备（0-3 个月）**：
   - 把 Sage 后端（FastAPI）+ 前端（React + Vite）作为**纯 Web 应用**部署
   - 静态前端 `npm run build` → 上传到任意静态托管（S3 / Vercel / Netlify / 自建 Nginx）
   - FastAPI 后端 + ChromaDB + SQLite 部署在服务器
   - 域名 + HTTPS

2. **Phase B — Win7 用户迁移（3-6 个月）**：
   - **Win7 兼容浏览器**（Win7 用户用浏览器访问）：
     - Chrome **109**（2023-03 发布，**最后支持 Win7**）
     - Firefox **ESR 102**（最后支持 Win7 的 ESR）
     - Edge 109（同 Chrome 109 内核）
   - 给 Win7 用户发邮件/通知：「请升级到 Chrome 109 或 Firefox ESR 102，访问 https://sage.example.com 即可使用」
   - 提供"如何检查浏览器版本"指南

3. **Phase C — 桌面端 EOL（6-12 个月）**：
   - 在 GitHub Release 标注"Win7 桌面端最后一次发布是 vX.Y.Z"
   - BRANCH_NOTES.md 加 "DEPRECATED" 横幅
   - 桌面端停止维护，但二进制仍可下载（"as-is"）

4. **Phase D — 分支归档（12-18 个月）**：
   - `release/win7` 分支 read-only
   - 主仓 release 流程完全 Web 化
   - 至此 Win7 用户全部迁移到 Web 客户端

**为什么选 Web 化而不是其他桌面框架**：
- .NET Framework 4.8 + WPF：需重写后端（Python→C#），3-6 个月工作量
- PyQt5：UI 改写 + Qt5 EOL，2-4 个月工作量
- Electron ≤ 22：已 EOL，包大小翻倍，违反"轻量"目标
- **Web 化**：后端 + 前端都不动，**1-2 周工作量**

**Web 化对 Win7 用户的实际体验**：
- 浏览器双击 .html 启动 → 首次需要输入 URL 或收藏
- 之后与桌面应用**几乎无差别**（功能 100% 相同，无 WebView2 依赖）
- 唯一区别：少了"双击 .exe"这一步骤

## 本分支的特殊性

1. **CI 用 GH-hosted `windows-latest` (Server 2022) 做 cross-build**（**interim 模式**——Win7 self-hosted runner 当前不可用）：
   - `ci-win7.yml` 和 `release-win7.yml` 都用 `runs-on: windows-latest`
   - cross-build 编译产物配置为 Win7 兼容（tauri=1.6 + windows7-compat + WebView2 v109 fallback）
   - **不**做 `sage.exe` 启动冒烟（WebView2 v109 fallback 行为只在真 Win7 上触发，Server 2022 上无法验证）
   - **Win7 启动验证 = 人工步骤**：维护者下载 artifact 拷贝到 Win7 物理机双击运行
   - 未来：拿到 Win7 物理机/VM 后，把 `runs-on` 改回 `[self-hosted, windows-7]` + 恢复 smoke test
2. **WebView2 完全离线安装**：`tauri.conf.json` 设 `webviewInstallMode: "offlineInstaller"`。Tauri 1.6 在 `tauri build` 时从微软官方下载 `MicrosoftEdgeWebView2RuntimeInstallerX64.exe`（~127MB，官方签名）并 embed 到 MSI/NSIS。**Win7 上自动 fallback 到 v109**（最后兼容版本，微软官方机制）。用户完全离线可用，无需任何手动步骤。
3. **`tauri = { features = ["windows7-compat"] }`**：使用旧版 WebView2 SDK (webview2-com) 而非新版 (webview2)。
4. **Python 3.8 兼容**：15 个文件加 `from __future__ import annotations`，避免 PEP 604/585 在 3.8 上解析失败。
5. **前端 shim** `src/lib/tauriInvoke.ts` 指向 `@tauri-apps/api/tauri`（1.6 路径），main 上指向 `core`（2.x 路径）。

## 风险声明

⚠️ **本分支基于已 EOL 的技术栈**——Tauri 1.6 + Python 3.8 + WebView2 v109 + Rust 1.77.2。
新发现的 CVE 大概率**不会得到修复**。用户应：
- 在隔离网络/虚拟机中使用
- 定期备份数据
- 不要用于处理敏感信息

## 发布

本分支通过 GitHub Actions `release-win7.yml`（独立 workflow，不在 `release.yml` 内）产出预编译安装包：
- `sage_<version>_x64-setup.exe`（Tauri 1.6 NSIS 安装包，~140MB，含 WebView2 v109 离线安装器）
- `sage_<version>_x64.msi`（Tauri 1.6 MSI 安装包，~140MB，含 WebView2 v109 离线安装器）

触发方式：
- 自动：push tag `v*.*.*-win7`（如 `v0.1.0-win7`）
- 手动：Actions UI → "Release Build (Windows 7)" → Run workflow

注意：tag `v*.*.*-win7` 不会触发 main 的 `release.yml`（已加 if 守卫 `!endsWith(github.ref, '-win7')`）。

**完全离线内网部署**：用户双击 `.msi` 或 `.exe`，Tauri 自带的 v109 离线安装器自动部署 WebView2，无需任何网络连接。

## CI 强门禁

本分支通过 `.github/workflows/ci-win7.yml`（独立 workflow）做 3 段强门禁：

| Job | 内容 | 强门禁 |
|---|---|---|
| `backend-py38` | Python 3.8 + coverage ≥ 80% | ✅ |
| `frontend` | Node 20 LTS + build + lint + test | ✅ |
| `tauri-win7-build` | GH-hosted `windows-latest` (Server 2022) cross-build + Tauri 1.6 + 跳过 sage.exe 冒烟（**Win7 实机验证为 manual step**）| ✅ |

`all-green` 任务：3 个 job 全过才算通过。

注意：main 的 `ci.yml` 不会在本分支触发（它只在 `[main, develop]` 分支跑）；本分支的 `ci-win7.yml` 也不会在 main 跑。

**Interim 模式下的 Win7 验证流程**：

1. CI 跑通 `ci-win7.yml`（backend-py38 + frontend + cross-build 都 success）
2. 维护者下载 artifact `sage-win7-installer`（含 .msi + .exe）
3. 拷贝到 **Windows 7 SP1 x64 物理机或 VM**（关键步骤）
4. 双击 `.msi` 或 `.exe`，验证：
   - WebView2 v109 自动 fallback 安装
   - sage 主窗口出现
   - 基本聊天功能可用
5. 在 release/win7 分支的 issue/PR 中报告验证结果

未来拿到 Win7 物理机/VM 后，把 `runs-on: windows-latest` 改回 `runs-on: [self-hosted, windows-7]` 即可恢复完整自动化。

---

**最近一次同步**：见 `git log --oneline main..release/win7`。
