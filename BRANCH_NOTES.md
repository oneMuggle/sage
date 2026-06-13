# release/win7 — Sage 长期 Windows 7 维护分支

> 本分支冻结 **Electron 21.4.4 + Python 3.8**，专门维护 **Windows 7 SP1 x64** 兼容性。
> 起点 commit：`7d3c5c0`（main 上 Tauri 2 升级之前）；Electron 迁移见 PR #13。

## 适用范围

| 项                  | 状态                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------ |
| 支持的 Windows 版本 | **Windows 7 SP1 x64**（Win7 x86 已知不兼容，见 docs/user-manual/01-desktop.md）      |
| 桌面壳              | **Electron 21.4.4**（最后支持 Win7 的 Electron 大版本，Chromium 106 + Node 16.20.2） |
| Python 版本         | **3.8.x**（最后支持 Win7 的版本，钉死在 `backend/requirements-py38.txt`）            |
| WebView             | 无（Electron 自带 Chromium 106，**不依赖系统 WebView2**）                            |
| 桌面端 Node         | v16.20.2（Electron 21 内置）                                                         |

## 与 main 的关系

- **main** 持续迭代，Electron 21.4.4 锁定 + Python 3.11+ 演进 + 桌面壳与 win7 100% 统一。
- **本分支** 只接受：安全修复、Win7 相关 bug、Python 3.8 兼容性微调。
- **不接受**：新功能、Electron 22+、Python 3.9+、性能重构、a11y 改进。
- 同步方式：单 commit cherry-pick，commit message 加 `(cherry picked from main commit XXX)`。

## 升级/安全策略

- Electron 21.4.4 已 EOL（Electron 22+ 砍 Win7/8/8.1，2022 年起），**未来 Electron 21 安全 CVE 不会得到官方修复**。
- 建议商业承诺期：18 个月（详见 `docs/technical/21-win7-lts.md` Phase 1-5）。
- Python 3.8 已 EOL（2024 年 10 月），同 18 个月窗口。
- 18 个月后 Win7 桌面端归档，Win7 用户迁 Web（Chrome 109 / Firefox ESR 102）。

## 长期路线图（18 个月 Web 化迁移）

**为什么是 18 个月**：本分支技术栈（Electron 21.4.4 + Python 3.8）已 EOL，建议商业承诺期不超过 18 个月。逾期后：

1. **Phase 1：共存期（0-6 个月，2026-06 ~ 2026-12）**
   - main + win7 并行开发，cherry-pick 通道打通
2. **Phase 2：减维护期（6-12 个月，2027-01 ~ 2027-06）**
   - Win7 用户 < 10%，减 patch 频率
3. **Phase 3：弃用通知期（12-15 个月，2027-07 ~ 2027-09）**
   - 发"Win7 桌面端 EOL"公告，引导用户迁 Web
4. **Phase 4：归档期（15-18 个月，2027-10 ~ 2027-12）**
   - 分支 read-only，GitHub Release 标 "DEPRECATED"
5. **Phase 5：删除期（2027-12-13+）**
   - `git push origin --delete release/win7`

详见 [`docs/technical/21-win7-lts.md`](../docs/technical/21-win7-lts.md) 完整时间表。

## 本分支的特殊性

1. **CI 用 GH-hosted `windows-latest` (Server 2022) 做 cross-build**（**interim 模式**——Win7 self-hosted runner 当前不可用）：
   - `.github/workflows/ci.yml` 中 `backend-py38` job（仅 win7 触发）+ `desktop-build` (matrix: ubuntu/windows) + `electron-smoke` job
   - `desktop-build` cross-build 编译产物配置为 Win7 兼容（electron@21.4.4 + 7 个 Win7 启动开关）
   - **不**做真 Win7 启动冒烟（Win7 兼容性行为只在真 Win7 上触发，Server 2022 上无法验证）
   - **Win7 启动验证 = 人工步骤**：维护者下载 artifact 拷贝到 Win7 物理机双击运行
   - 未来：拿到 Win7 物理机/VM 后，把 `runs-on` 改回 `[self-hosted, windows-7]` + 恢复 smoke test
2. **Chromium 106 内嵌**：Electron 21.4.4 自带 Chromium 106 + Node 16.20.2，**不依赖系统 WebView2**。Win7 上无需安装任何外部 runtime，**即装即用**。
3. **Win7 启动开关**（`electron/main.ts` 在 `app.whenReady()` 之前设置）：
   - `app.disableHardwareAcceleration()` 禁用 GPU 硬件加速
   - `--no-sandbox` 禁用 chrome-sandbox（Win7 无 SUID helper）
   - `--disable-gpu` 强制 CPU 合成路径
   - `--disable-software-rasterizer` 关闭 Skia 软件光栅
   - 等等（详见 `docs/technical/20-electron.md` § Win7 Launch Flags）
4. **Python 3.8 兼容**：15 个文件加 `from __future__ import annotations`，避免 PEP 604/585 在 3.8 上解析失败。
5. **前端 shim** `src/lib/tauriInvoke.ts`（已 re-export 自 `desktopInvoke.ts`）委托 `window.electronAPI.invoke`——main 与 win7 路径完全一致。

## 风险声明

⚠️ **本分支基于已 EOL 的技术栈**——Electron 21.4.4 + Python 3.8 + Chromium 106 + Node 16.20.2。
新发现的 Electron 21 CVE **不会得到官方修复**（Electron 22+ 已 EOL Win7）。用户应：

- 在隔离网络/虚拟机中使用
- 定期备份数据
- 不要用于处理敏感信息

## 发布

本分支通过 GitHub Actions `release.yml` 触发 electron-builder 产出预编译安装包：

- `sage_<version>_x64-setup.exe`（Electron 21.4.4 NSIS 安装包，~110MB，自带 Chromium 106）
- `sage_<version>_x64.AppImage`（Linux，仅 main 分支产）
- `sage_<version>_x64.dmg`（macOS，仅 main 分支产）

触发方式：

- 自动：push tag `v*.*.*-win7`（如 `v0.1.0-win7`）
- 手动：Actions UI → "Release Build" → Run workflow

注意：tag `v*.*.*-win7` 不会触发 main 的 `release.yml`（已加 if 守卫 `!endsWith(github.ref, '-win7')`）。

**完全离线内网部署**：用户双击 `.exe`，Electron 21 自带的 Chromium 106 + Node 16.20.2 全部内置，**无需任何网络连接**。

## CI 强门禁

本分支通过 `.github/workflows/ci.yml`（与 main 共享，按 `if: github.ref` 分支守卫）做 6 段强门禁：

| Job              | 内容                                                                   | 触发分支     |
| ---------------- | ---------------------------------------------------------------------- | ------------ |
| `backend-py38`   | Python 3.8 + 锁版本依赖 + coverage ≥ 80%                               | release/win7 |
| `frontend`       | Node 20 LTS + build + lint + test                                      | 两个分支     |
| `desktop-build`  | GH-hosted `windows-latest` (Server 2022) cross-build + Electron 21.4.4 | 两个分支     |
| `electron-smoke` | Playwright 启动 Electron + IPC bridge 验证                             | 两个分支     |
| `all-green`      | 上面 4 项全过                                                          | 两个分支     |

`all-green` 任务：4 个 job 全过才算通过。

`backend-py38` 与 main 的 `backend` (py3.11) job **互斥**（用 `if: github.ref` 守卫隔离）。

**Interim 模式下的 Win7 验证流程**：

1. CI 跑通 `ci.yml`（backend-py38 + frontend + desktop-build + electron-smoke 都 success）
2. 维护者下载 artifact `electron-windows-latest`（含 .exe）
3. 拷贝到 **Windows 7 SP1 x64 物理机或 VM**（关键步骤）
4. 双击 `.exe`，验证：
   - Electron 21.4.4 启动（无需 WebView2 离线安装）
   - sage 主窗口出现
   - 基本聊天功能可用
5. 在 release/win7 分支的 issue/PR 中报告验证结果

未来拿到 Win7 物理机/VM 后，把 `runs-on: windows-latest` 改回 `runs-on: [self-hosted, windows-7]` 即可恢复完整自动化。

---

**最近一次同步**：见 `git log --oneline main..release/win7`。
