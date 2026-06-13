# Win7 真机烟测脚本（Phase 5）

> **跨主机架构**：本目录脚本在 **Win7 VM 内部** 运行（管理员 PowerShell）。Host (Linux) 通过 RDP / SSH / SMB 推送脚本和安装包，VM 内执行。

## 1. 烟测矩阵（5 步）

| Step | 脚本 | 验证内容 | 期望耗时 |
|---|---|---|---|
| 1. Deploy | `deploy.ps1` | OS 版本 + KB3033929 + 后端端口 + Ollama 端口 + 安装包存在 | ~30s |
| 2. Install | `install.ps1` | NSIS 静默安装 + Sage.exe 存在 + 注册表项存在 | ~1-2 min |
| 3. Launch | `launch-test.ps1` | Sage.exe 启动 < 10s + 主窗口出现 + 后端 /health + 截图 | ~30s |
| 4. Ollama | `verify-ollama.ps1` | Ollama /api/tags + /api/generate + 后端 /chat 链路 | ~30s |
| 5. Teardown | `teardown.ps1` | NSIS 卸载 + 日志收集 | ~30s |

**PASS 准则**：5 步全部 PASS，且 Launch 步骤截图肉眼确认非白屏、xyflow 节点连线可见。

## 2. 一次性环境前置（用户责任）

在 Win7 VM 里：

1. **KB3033929** 已装（`Get-HotFix -Id KB3033929` 验证）
2. **管理员 PowerShell** 执行（部署 NSIS 卸载器需 admin）
3. **PowerShell ExecutionPolicy** 设为 `RemoteSigned` 或更宽松：
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```
4. **可选：OpenSSH Server**（KB 3033929 后 Win7 支持原生 OpenSSH；用于 host 推送脚本）

## 3. 三种执行模式

### 3.1 手动 RDP 模式（最简单）

1. RDP 进 Win7 VM
2. 桌面双击 PowerShell (Admin)
3. 把脚本从 host 复制粘贴到 VM 桌面（共享剪贴板或 SMB 共享）
4. 依次执行：
   ```powershell
   cd C:\Users\<user>\Desktop\win7-smoke
   .\deploy.ps1 -InstallerPath C:\path\to\Sage-Setup-X.Y.Z.exe -BackendHost <host-ip>
   .\install.ps1 -InstallerPath C:\path\to\Sage-Setup-X.Y.Z.exe
   .\launch-test.ps1 -KillAfterSeconds 30 -ScreenshotPath C:\Users\<user>\Desktop\launch.png
   .\verify-ollama.ps1 -OllamaHost <host-ip>
   .\teardown.ps1
   ```
5. 把 `*-result.json` 和 `launch.png` 通过 SMB / 共享文件夹带回 host review

### 3.2 SSH 推送模式（自动化）

Win7 VM 装了 OpenSSH 后（KB 3033929 后支持），host 端用 `scp` + `ssh`：

```bash
# 1. 拷贝脚本到 VM
scp -r scripts/win7-smoke/ admin@<vm-ip>:C:/Users/admin/win7-smoke/

# 2. 拷贝 Sage 安装包
scp release/Sage-Setup-X.Y.Z.exe admin@<vm-ip>:C:/Users/admin/Sage-Setup.exe

# 3. 远程依次执行 5 步
ssh admin@<vm-ip> "powershell -ExecutionPolicy Bypass -File C:/Users/admin/win7-smoke/deploy.ps1 -InstallerPath C:/Users/admin/Sage-Setup.exe -BackendHost <host-ip>"
ssh admin@<vm-ip> "powershell -ExecutionPolicy Bypass -File C:/Users/admin/win7-smoke/install.ps1 -InstallerPath C:/Users/admin/Sage-Setup.exe"
ssh admin@<vm-ip> "powershell -ExecutionPolicy Bypass -File C:/Users/admin/win7-smoke/launch-test.ps1 -ScreenshotPath C:/Users/admin/launch.png"
ssh admin@<vm-ip> "powershell -ExecutionPolicy Bypass -File C:/Users/admin/win7-smoke/verify-ollama.ps1 -OllamaHost <host-ip>"
ssh admin@<vm-ip> "powershell -ExecutionPolicy Bypass -File C:/Users/admin/win7-smoke/teardown.ps1"

# 4. 拉回结果
scp admin@<vm-ip>:C:/Users/admin/win7-smoke/*-result.json ./smoke-results/
scp admin@<vm-ip>:C:/Users/admin/launch.png ./smoke-results/

# 5. 检查 PASS/FAIL
for f in smoke-results/*-result.json; do
  echo "=== $f ==="
  python3 -c "import json; d=json.load(open('$f')); print('Overall:', all(c['pass'] for c in d.get('checks',{}).values()))"
done
```

### 3.3 WinRM 模式（最自动化，但 Win7 WinRM 默认未启）

Win7 自带 WinRM 但服务默认停止。要启用：

```cmd
# Win7 VM (管理员 cmd)
winrm quickconfig -transport:http
winrm set winrm/config/service @{AllowUnencrypted="true"}
```

Host 端：

```bash
pip install pywinrm
python3 scripts/win7-smoke/orchestrate.py --vm <vm-ip> \
    --installer release/Sage-Setup-X.Y.Z.exe \
    --ollama-host <host-ip> \
    --collect-dir ./smoke-results/
```

`orchestrate.py` 在 Phase 5 follow-up 时补（用户启用 WinRM 后再加）。

## 4. 失败排错速查

| FAIL 项 | 排错动作 |
|---|---|
| deploy: KB3033929 missing | `Get-HotFix -Id KB3033929` 验证；`wusa /uninstall /kb:3033929` 不存在则需手动装 |
| deploy: backend TCP fail | host 上 `curl http://127.0.0.1:8765/health` 验证；防火墙 `netsh advfirewall firewall add rule name=Sage dir=in action=allow protocol=TCP localport=8765` |
| deploy: ollama TCP fail | host 上 `curl http://127.0.0.1:11434/api/tags`；同上防火墙规则加 11434 |
| install: exit code != 0 | NSIS 日志在 `%TEMP%\nsis-*.log`；常见原因：UAC 阻断、磁盘空间不足、VC++ Redist 缺失 |
| launch: main_window not appeared | 收集 `%APPDATA%\Sage\logs\*.log`；用 `electron --enable-logging` 重启 Sage 看 stdout |
| launch: backend_health fail | Sage 已启动但后端没启 — conda env `sage-backend` 在 Win7 上要 `conda init powershell` 后才能 `conda run` |
| launch: screenshot blank | 截全屏而非 Sage 窗口（脚本已 fallback）；或 Sage 启动后等更长（参数 `--KillAfterSeconds 60`） |
| ollama: tags fail | host 防火墙 / Ollama 服务未启 / `OLLAMA_HOST=0.0.0.0` 未设 |
| ollama: chat > 60s | CPU 跑 1.5B 模型首 token 慢是正常的；改 GPU 跑或换更小模型 |

## 5. 烟测产物

执行完后 host 端 `smoke-results/` 目录：

```
smoke-results/
├── deploy-result.json         # OS / KB / 端口 验证
├── install-result.json        # NSIS exit code + 安装目录
├── launch-result.json         # 主窗口出现时间 + 后端健康 + 截图路径
├── launch.png                 # Sage 主窗口截图（人工 review 关键）
├── ollama-result.json         # Ollama + 后端 chat 链路
├── teardown-result.json       # 卸载 + 日志收集
└── Sage-logs/                 # AppData\Roaming\Sage\logs 拷贝
    ├── backend-*.log
    └── electron-*.log
```

把这些 commit 到 `archive/win7-smoke-results/<date>/` 留档。

## 6. 相关文档

- [docs/technical/20-electron-win7.md §7](../../../docs/technical/20-electron-win7.md) — 完整 SOP（含 VM 配置、Ollama 启动等）
- [docs/technical/20-electron-win7.md §5.1](../../../docs/technical/20-electron-win7.md) — CI 轻量烟测对比（这个是真机版）
- [package.json `electron:dist`](../../../package.json) — 怎么出 `Sage-Setup-X.Y.Z.exe`