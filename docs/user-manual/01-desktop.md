# 01. 桌面端安装与启动（Desktop Installation & Startup）

**最后更新**：2026-06-06
**适用版本**：Sage v0.1（桌面端）

## 1.1 系统要求

| 系统 | 最低 | 推荐 | 备注 | 下载来源 |
|------|------|------|------|---------|
| Windows 11 | ✅ | ✅ | 默认 WebView2 已装 | main release |
| Windows 10 | ✅ | ✅ | 1809+ 含 WebView2 | main release |
| **Windows 7 SP1 x64** | ⚠️ LTS only | ⚠️ x64 only | main release 不再支持; KB3033929 必需 | **LTS release** (`v*-lts` tag) |
| macOS 12+ | ⏳ Phase 3 | ⏳ Phase 3 | 暂未发布 | — |
| Ubuntu 22.04+ | ✅ | ✅ | GTK + WebKitGTK 4.1 | main release |
| Linux 通用 (glibc 2.28+) | ✅ | ✅ | AppImage 通用 | main release |

## 1.2 安装 Windows

### 1.2.1 Windows 10 / 11 安装 (main release)

1. 从 main release 页面下载 `Sage-Setup-${version}-win10.exe`
2. 双击运行, 按向导安装 (默认 HKCU, 无需管理员权限)
3. 安装阶段静默装 VC++ 2015-2022 Redistributable (已装会跳过)
4. 桌面出现 Sage 快捷方式, 双击启动

**入口**: https://github.com/oneMuggle/sage/releases/latest

### 1.2.2 Windows 7 SP1 安装 (LTS release)

> ⚠️ **2026-06-23 起**: main release 不再支持 Win7。Win7 用户请下载 LTS release。

1. **前置**: 装 **KB3033929** (SHA-2 代码签名, 2016 年发布) — Win7 SP1 必装, 否则 Sage.exe 启动被拒
2. 从 LTS release 页面下载 `Sage-Setup-${version}-win7.exe`:
   https://github.com/oneMuggle/sage/releases?q=tag%3Av*-lts
3. 双击 `.exe` 运行安装 (NSIS, HKCU, 无需管理员)
4. 安装阶段静默装 VC++ 2015-2022 Redistributable
5. 桌面出现 Sage 快捷方式, 双击启动
6. **x64 only** — Electron 21 不支持 Win7 32-bit

**已知限制**（基于 EOL 技术栈 Electron 21.4.4 + Chromium 106）:

- 不保证 Win7 GPU 驱动兼容, 启动时已禁用硬件加速 (`--disable-gpu`)
- 7 个 Chromium 启动开关在 `electron/main.ts` 行内注释完整记录
- 详见 [`../technical/21-win7-lts.md` §6 风险声明](../technical/21-win7-lts.md)

### 1.2.3 验证安装

启动 Sage 后：
- 任务栏图标显示
- 主窗口打开
- 状态栏显示「就绪」

## 1.3 安装 macOS

1. 下载 `sage_0.1.0_x64.dmg`
2. 双击挂载
3. 拖动 Sage.app 到 Applications
4. 首次打开可能需「系统设置 → 隐私与安全 → 仍要打开」

## 1.4 安装 Linux

### Debian/Ubuntu
```bash
sudo dpkg -i sage_0.1.0_amd64.deb
sudo apt install -f  # 解决依赖
sage
```

### Fedora/RHEL
```bash
sudo dnf install sage-0.1.0.x86_64.rpm
sage
```

### AppImage（通用）
```bash
chmod +x sage_0.1.0_x86_64.AppImage
./sage_0.1.0_x86_64.AppImage
```

## 1.5 启动与配置

### 首次启动

1. 启动 Sage
2. 打开「设置」页面
3. 配置 LLM Provider：
   - **API Base URL**：`https://api.openai.com/v1`（或自部署端点）
   - **API Key**：填入你的 LLM Provider 密钥
   - **Model**：选择模型（如 `gpt-4o`、`claude-3.5-sonnet`）
4. 点击「测试连接」验证
5. 回到「聊天」页面开始对话

### 配置文件位置

| 平台 | 路径 |
|------|------|
| Windows | `%APPDATA%\Sage\settings.json` |
| macOS | `~/Library/Application Support/Sage/settings.json` |
| Linux | `~/.config/Sage/settings.json` |

## 1.6 常见问题

### Q: 启动报「缺少 WebView2」

A: Win7 / 早期 Win10。运行 `MicrosoftEdgeWebview2Setup.exe`（Sage 安装包已含），或从微软官网下载。

### Q: 启动报「端口被占用」

A: Sage 后端使用 8765 端口。如果被占用，关闭占用程序或修改 `backend/main.py` 的 `PYTHON_BACKEND_PORT`。

### Q: macOS 报「无法打开，因为来自身份不明的开发者」

A: 系统设置 → 隐私与安全 → 仍要打开。

### Q: Linux 启动黑屏

A: 检查 WebKitGTK：`sudo apt install libwebkit2gtk-4.1-0`。

### Q: 聊天发送没反应

A: 检查「设置」页面的 LLM Provider 配置 + API Key 是否正确。

## 1.7 卸载

### Windows
设置 → 应用 → Sage → 卸载

### macOS
拖动 Sage.app 到废纸篓

### Linux
```bash
sudo apt remove sage   # Debian
sudo dnf remove sage   # Fedora
```

## 1.8 数据与隐私

- **聊天历史** 存储在本地 SQLite：`%APPDATA%\Sage\sage.db`
- **API Key** 存储在本地 `settings.json`（明文，建议自行加密磁盘）
- **审计日志**：`%APPDATA%\Sage\audit\audit.jsonl`
- **不上传任何数据到第三方**（除 LLM Provider API 调用）
