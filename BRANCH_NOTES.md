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

## 本分支的特殊性

1. **CI 在 self-hosted Windows 7 runner 上跑**（label `windows-7`），不在 GH-hosted。
2. **NSIS 安装器内嵌 WebView2 v109 离线包**（~127MB），首次安装时自动静默部署。
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

本分支通过 GitHub Actions `release.yml` 的 `release-win7` job 产出预编译安装包：
- `sage_<version>_x64-setup.exe`（NSIS 安装包，~140MB，含 WebView2）
- `sage_<version>_x64-portable.zip`（便携版，无需安装）

---

**最近一次同步**：见 `git log --oneline main..release/win7`。
