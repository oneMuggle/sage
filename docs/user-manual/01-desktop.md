# 01. 桌面端安装与启动（Desktop Installation & Startup）

**最后更新**：2026-06-06
**适用版本**：Sage v0.1（桌面端）

## 1.1 系统要求

| 系统 | 最低 | 推荐 | 备注 |
|------|------|------|------|
| Windows 11 | ✅ | ✅ | 默认 WebView2 已装 |
| Windows 10 | ✅ | ✅ | 1809+ 含 WebView2 |
| **Windows 7** | ⚠️ 需 embedBootstrapper | ⚠️ x64 only | **x86 兼容性已知问题**（issue #11381） |
| macOS 12+ | ✅ | ✅ | Monterey 起 |
| Ubuntu 22.04+ | ✅ | ✅ | GTK + WebKitGTK 4.1 |

## 1.2 安装 Windows

### 1.2.1 正常安装

1. 下载 `sage_0.1.0_x64-setup.exe`
2. 双击运行
3. 按提示完成安装
4. WebView2 自动检测（Win10 1809+ / Win11 预装）

### 1.2.2 Windows 7 安装

Win7 系统不预装 WebView2 runtime，需要 embedBootstrapper 模式：

1. 下载 `sage_0.1.0_x64-setup.exe`（构建时已含 WebView2 bootstrapper，约 +1.8MB）
2. 双击运行
3. 安装器自动检测并安装 WebView2
4. 安装完成后启动 Sage

**已知问题**（issue #11381）：
- Windows 7 **x86 (32-bit)** 上可能因 `tao` 库异常而崩溃
- 推荐 Win7 用户使用 **x64 (64-bit)** 版本
- x86 兼容性需要 rust 1.77.2 + 特定依赖降级（社区 workaround）

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
