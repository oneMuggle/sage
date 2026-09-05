# Sage 升级系统设计

> **状态**：已批准，待实施  
> **日期**：2026-09-05  
> **作者**：Claude Code + Sage Team  
> **目标用户**：技术用户/早期采用者（接受每周/双周更新，有一定问题排查能力）

## 1. 背景与目标

### 1.1 需求

Sage 桌面应用需要实现：
1. **覆盖升级**：安装新版本时保留用户数据（知识库、设置、聊天记录），覆盖安装到原目录
2. **自动升级**：应用启动时检查更新，根据用户策略自动下载/安装
3. **升级失败回退**：新版本启动失败时自动回退到上一稳定版本，或在 N 天内允许手动回退

### 1.2 设计原则

- **YAGNI**：MVP 先实现整体打包更新，架构上预留组件化扩展点
- **可控性**：技术用户群体偏好透明可控，提供多种更新策略选择
- **安全性**：HTTPS + SHA-512 校验 + 代码签名，防止中间人攻击
- **渐进式**：元数据服务先用 JSON 文件存储，后续演进到数据库

## 2. 整体架构

### 2.1 组件分层

```
┌─────────────────────────────────────────────────────────┐
│                    Sage Desktop Client                  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Update Manager (Electron main process)          │  │
│  │  - 版本检查调度器                                  │  │
│  │  - 下载/安装协调器（调用 electron-updater）         │  │
│  │  - 回退状态机                                      │  │
│  └──────────────────────────────────────────────────┘  │
│                        ↓ IPC                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Update UI (React renderer)                      │  │
│  │  - 更新提示对话框                                  │  │
│  │  - 下载进度显示                                    │  │
│  │  - 设置页（更新策略选择）                           │  │
│  │  - 回退操作入口                                    │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         ↓ HTTP
┌─────────────────────────────────────────────────────────┐
│              Update Metadata Service                     │
│              (FastAPI, /api/v1/updates/* )              │
│  - GET /channels/{channel}/latest                       │
│  - GET /channels/{channel}/history                      │
│  - POST /rollbacks (记录回退事件)                        │
└─────────────────────────────────────────────────────────┘
                         ↓ 
┌─────────────────────────────────────────────────────────┐
│              File Storage (S3 / 自建 HTTP)              │
│  - /releases/v0.3.0/Sage-Setup-0.3.0.exe               │
│  - /releases/v0.3.0/latest.yml                          │
│  - /releases/v0.3.0/Sage-0.3.0.AppImage                │
│  - /releases/v0.3.0/latest-linux.yml                    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流（正常升级）

1. 启动时（或定时）：客户端 → 元数据服务 → 获取最新版本
2. 比对本地版本 → 有新版 → 触发更新流程
3. 根据用户策略：
   - `manual`：弹提示，用户点"下载"
   - `auto-download`：静默下载，完成后提示"安装"
   - `auto-install`：下载安装后提示"重启应用"
4. 下载：electron-updater → 文件存储 → 下载到临时目录
5. 校验：SHA-512 + 签名验证（electron-updater 内置）
6. 安装前：备份关键用户数据路径（元数据 + 向量库）
7. 触发安装：`electron-updater.quitAndInstall()`
8. 新进程启动 → Launcher 健康检查 → 成功则 commit / 失败则 rollback

### 2.3 元数据服务部署

**推荐方案**：复用现有 Python 后端（FastAPI），路由独立为模块。

- 开发/测试：`http://127.0.0.1:8765/api/v1/updates/*`
- 生产：`https://updates.sage.app`（反向代理到后端）

## 3. 元数据服务设计

### 3.1 API 端点

```
GET /api/v1/updates/channels/{channel}/latest
  - 返回指定渠道的最新版本元数据
  - channel: stable | beta | alpha

GET /api/v1/updates/channels/{channel}/history?limit=10
  - 返回版本历史（用于 UI 显示 changelog）

POST /api/v1/updates/rollbacks
  - 客户端回退时上报事件（用于监控回退率）
  - Body: { from_version, to_version, reason, crash_count, timestamp }
```

### 3.2 数据模型

```python
class UpdateManifest:
    version: str                    # "0.3.0"
    channel: str                    # "stable" | "beta" | "alpha"
    release_date: datetime
    release_notes: str              # Markdown 格式
    min_upgradable_version: str     # "0.2.0"（低于此版本需全量安装）
    
    # 文件信息（按平台）
    files: dict[str, FileMeta]      # {"win-x64": ..., "linux-appimage": ...}
    
    # 组件版本（为未来"按组件更新"预留）
    components: dict[str, str]      # {"electron": "0.3.0", "python": "3.11.9", "backend": "0.3.0"}

class FileMeta:
    filename: str                   # "Sage-Setup-0.3.0.exe"
    url: str                        # "https://updates.sage.app/releases/v0.3.0/Sage-Setup-0.3.0.exe"
    sha512: str                     # 文件哈希（electron-updater 校验用）
    size: int                       # 字节数
    signature: str                  # 代码签名（Windows: Authenticode, Linux: GPG）
```

### 3.3 响应示例

```json
{
  "version": "0.3.0",
  "channel": "stable",
  "release_date": "2026-09-10T10:00:00Z",
  "release_notes": "### 新功能\n- 支持知识库批量导入\n\n### 修复\n- 修复 Python 后端内存泄漏",
  "min_upgradable_version": "0.2.0",
  "files": {
    "win-x64": {
      "filename": "Sage-Setup-0.3.0.exe",
      "url": "https://updates.sage.app/releases/v0.3.0/Sage-Setup-0.3.0.exe",
      "sha512": "abc123...",
      "size": 157286400,
      "signature": "..."
    },
    "linux-appimage": {
      "filename": "Sage-0.3.0.AppImage",
      "url": "https://updates.sage.app/releases/v0.3.0/Sage-0.3.0.AppImage",
      "sha512": "def456...",
      "size": 148992000,
      "signature": "..."
    }
  },
  "components": {
    "electron": "0.3.0",
    "python": "3.11.9",
    "backend": "0.3.0"
  }
}
```

### 3.4 元数据存储

**MVP 阶段**：JSON 文件（`updates/manifests/stable.json`）
- 简单，无需数据库
- 发布新版本时手动更新 JSON + 上传文件到 S3
- 适合早期版本（< 100 用户）

**后续演进**：SQLite / PostgreSQL
- 支持版本历史查询、回退事件统计
- 支持 A/B 测试（灰度发布）

### 3.5 与 electron-updater 的集成

electron-updater 需要 `latest.yml`（Windows）或 `latest-linux.yml`（Linux）文件：

```yaml
# latest.yml（由 electron-builder 自动生成）
version: 0.3.0
files:
  - url: Sage-Setup-0.3.0.exe
    sha512: abc123...
    size: 157286400
path: Sage-Setup-0.3.0.exe
sha512: abc123...
releaseDate: 1694347200
```

**集成方式**：
- 元数据服务的 `files["win-x64"].url` 指向 `latest.yml`
- electron-updater 读取 `latest.yml` → 下载实际安装包
- Sage 客户端先查元数据服务（获取 release_notes、components 等扩展字段）→ 再调 electron-updater（传入 `latest.yml` URL）

## 4. 客户端更新状态机

### 4.1 状态机设计

```
                    ┌──────────────┐
                    │    idle      │ ← 启动 / 重置
                    └──────┬───────┘
                           │ checkForUpdates()
                           ↓
                    ┌──────────────┐
                    │  checking    │ → 失败 → idle (retry 后)
                    └──────┬───────┘
                           │ 有新版
                           ↓
                    ┌──────────────┐
                    │  available   │ → 用户策略 == "manual"? → 等用户点"下载"
                    └──────┬───────┘                           ↓
                           │ 策略 == "auto-download"       [manual-pending]
                           ↓                                   │ 用户点"下载"
                    ┌──────────────┐                           ↓
                    │ downloading  │ ←─────────────────────────┘
                    └──────┬───────┘
                           │ 下载完成
                           ↓
                    ┌──────────────┐
                    │ ready-to-    │ → 策略 == "auto-install"? → 自动 quitAndInstall()
                    │ install      │                           ↓
                    └──────┬───────┘                     [auto-pending]
                           │ 用户点"安装"                     │ 等用户"重启"
                           ↓                                 ↓
                    ┌──────────────┐
                    │  installing  │ → 应用退出，新进程启动
                    └──────┬───────┘
                           │ 新进程启动 + 健康检查
                           ↓
                    ┌──────────────┐
              ┌─────│   committed  │ ← 健康检查通过，记录为 lastKnownGood
              │     └──────────────┘
              │              │
              │              │ N 天内用户点"回退"
              │              ↓
              │     ┌──────────────┐
              │     │ rolled-back  │ → 恢复到 lastKnownGood 版本
              │     └──────────────┘
              │
              │ 健康检查失败（崩溃 / 后端冒烟失败）
              ↓
       ┌──────────────┐
       │ auto-rollback│ → 自动恢复到 lastKnownGood
       └──────────────┘
```

### 4.2 状态持久化

```typescript
// ~/.sage/update-state.json
{
  "currentVersion": "0.3.0",
  "lastKnownGoodVersion": "0.2.5",       // 上次健康检查通过的版本
  "lastKnownGoodInstallDate": "2026-09-10T10:00:00Z",
  "crashCount": 0,                       // 当前版本连续崩溃次数
  "rollbackWindowDays": 7,               // 可手动回退的天数
  "updateStrategy": "auto-download",     // "manual" | "auto-download" | "auto-install"
  "lastCheckTime": "2026-09-15T08:00:00Z",
  "pendingUpdate": null                  // { version, downloadedAt } 或 null
}
```

### 4.3 更新策略配置

```typescript
type UpdateStrategy = "manual" | "auto-download" | "auto-install";

// 设置页 UI
<SettingsSection title="更新策略">
  <RadioGroup value={strategy} onChange={setStrategy}>
    <Radio value="manual">
      手动更新（每次更新需我确认下载和安装）
    </Radio>
    <Radio value="auto-download">
      自动下载，手动安装（推荐：下载无感，安装前确认）
    </Radio>
    <Radio value="auto-install">
      自动下载安装（最激进：下载完成后自动安装，重启后生效）
    </Radio>
  </RadioGroup>
</SettingsSection>
```

### 4.4 IPC 通信

```typescript
// 主进程 → 渲染进程（事件）
ipcMain.on("update:state-changed", (event, state: UpdateState) => {
  mainWindow.webContents.send("update:state-changed", state);
});

// 渲染进程 → 主进程（操作）
ipcMain.handle("update:check", async () => {
  return updateManager.checkForUpdates();
});

ipcMain.handle("update:download", async () => {
  return updateManager.downloadUpdate();
});

ipcMain.handle("update:install", async () => {
  return updateManager.installUpdate();
});

ipcMain.handle("update:rollback", async () => {
  return updateManager.rollback();
});

ipcMain.handle("update:setStrategy", async (event, strategy: UpdateStrategy) => {
  return updateManager.setStrategy(strategy);
});
```

## 5. 覆盖升级流程

### 5.1 覆盖升级的核心语义

**"覆盖升级"= 保留用户数据 + 覆盖应用文件到原安装目录**

**用户数据路径**（独立于应用安装目录）：
```
Windows: %APPDATA%/Sage/
  ├── config.json
  ├── knowledge-base/        # 向量数据库
  ├── chat-history/
  └── logs/

Linux: ~/.config/Sage/
  ├── config.json
  ├── knowledge-base/
  ├── chat-history/
  └── logs/
```

**应用文件路径**（安装目录）：
```
Windows: C:\Users\<user>\AppData\Local\Programs\Sage\
  ├── Sage.exe
  ├── resources/
  │   ├── python/           # 嵌入式 Python 运行时
  │   ├── backend/          # Python 后端代码
  │   └── sage-core/
  └── ...

Linux (AppImage): /opt/Sage/Sage-0.3.0.AppImage
Linux (deb): /opt/Sage/
```

### 5.2 Windows NSIS 配置

```yaml
# electron-builder.yml
nsis:
  oneClick: false                   # 显示安装向导（用户可选择）
  perMachine: false                 # HKCU 安装，不需要管理员权限
  allowToChangeInstallationDirectory: true  # 允许用户选择安装目录
  allowElevation: true              # 如果用户选择 Program Files，需要提权
  installerIcon: build/icon.ico
  uninstallerIcon: build/icon.ico
  installerHeaderIcon: build/icon.ico
  
  # 关键：卸载旧版时保留用户数据
  deleteAppDataOnUninstall: false   # ← 默认就是 false，但显式声明
  
  # 安装前脚本：备份关键配置
  include: build/installer-upgrade.nsh
```

### 5.3 自定义 NSIS 脚本

```nsis
; build/installer-upgrade.nsh
; 安装前：检测是否已安装旧版
Function .onInit
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Sage" "InstallLocation"
  ${If} $0 != ""
    ; 已安装旧版，进入升级模式
    StrCpy $INSTDIR $0              ; 使用原安装目录
    StrCpy $UPGRADE_MODE "1"
  ${EndIf}
FunctionEnd

; 安装前：备份关键配置（如果升级模式）
Function .onInstSuccess
  ${If} $UPGRADE_MODE == "1"
    ; 备份 config.json（如果存在）
    CreateDirectory "$APPDATA\Sage\backup"
    CopyFiles /SILENT "$APPDATA\Sage\config.json" "$APPDATA\Sage\backup\config.json.bak"
  ${EndIf}
FunctionEnd
```

### 5.4 Linux 升级方式

**AppImage**：
- 用户手动下载新 AppImage → 替换旧文件 → 直接运行
- 无自动升级（AppImage 设计如此）
- 可选：集成 AppImageUpdate（差分更新工具）

**deb 包**：
- `sudo dpkg -i sage_0.3.0_amd64.deb` → 自动覆盖安装
- 用户数据在 `~/.config/Sage/`，不受影响

### 5.5 备份与恢复机制

```typescript
class UpgradeCoordinator {
  async backupUserData() {
    const backupDir = path.join(app.getPath("userData"), "backup");
    await fs.mkdir(backupDir, { recursive: true });
    
    // 备份关键文件
    const filesToBackup = [
      "config.json",
      "knowledge-base/metadata.json",  // 向量库元数据
      "chat-history/index.json"
    ];
    
    for (const file of filesToBackup) {
      const src = path.join(app.getPath("userData"), file);
      const dest = path.join(backupDir, `${file}.bak`);
      
      if (await fs.pathExists(src)) {
        await fs.copy(src, dest);
        logger.info(`Backed up ${file}`);
      }
    }
    
    return backupDir;
  }
  
  async restoreUserData(backupDir: string) {
    const filesToRestore = await fs.readdir(backupDir);
    
    for (const backupFile of filesToRestore) {
      const originalName = backupFile.replace(".bak", "");
      const src = path.join(backupDir, backupFile);
      const dest = path.join(app.getPath("userData"), originalName);
      
      await fs.copy(src, dest, { overwrite: true });
      logger.info(`Restored ${originalName}`);
    }
  }
}
```

### 5.6 覆盖升级流程（完整）

```
1. 用户触发安装（或自动安装）
   ↓
2. UpgradeCoordinator.backupUserData()
   - 备份 config.json、知识库元数据等到 backup/
   ↓
3. electron-updater.quitAndInstall()
   - 应用退出
   - NSIS 安装器启动
   ↓
4. NSIS 安装器
   - 检测旧版安装路径（读注册表）
   - 使用原安装目录（覆盖模式）
   - 卸载旧版（deleteAppDataOnUninstall=false，保留用户数据）
   - 安装新版到同目录
   ↓
5. 新进程启动
   - Electron main.ts 加载
   - 启动 Python 后端
   ↓
6. Launcher 健康检查（第 6 节详述）
   - 检查前端主窗口加载
   - 检查 Python 后端 /health 响应
   ↓
7. 健康检查通过
   - UpdateManager.commitUpdate()
   - 记录 currentVersion = 新版本
   - 记录 lastKnownGoodVersion = 新版本
   - 清理 backup/（可选，7 天后自动清理）
   ↓
   健康检查失败
   - UpdateManager.rollback()
   - 恢复到 lastKnownGoodVersion（第 6 节详述）
```

### 5.7 错误处理

```typescript
class UpgradeCoordinator {
  async installUpdate() {
    try {
      await this.backupUserData();
      autoUpdater.quitAndInstall();
    } catch (error) {
      logger.error("Upgrade failed", error);
      
      // 安装失败，恢复备份
      await this.restoreUserData(this.backupDir);
      
      // 通知渲染进程
      this.emitStateChange({ 
        status: "error", 
        error: "升级失败，已恢复原始数据" 
      });
      
      // 不退出应用，用户可以继续使用旧版
    }
  }
}
```

## 6. 回退机制

### 6.1 回退的两类场景

| 场景 | 触发条件 | 实现难度 | MVP 范围 |
|---|---|---|---|
| **软崩溃**（Electron 还能运行）| Python 后端健康检查失败 / 渲染进程崩溃 / 主窗口加载失败 | 低 | ✅ 必做 |
| **硬崩溃**（Electron 无法启动）| Electron 进程崩溃 / 启动期 JS 异常 | 高（需外部 Launcher）| ⏸️ 后续演进 |

MVP 聚焦**软崩溃自动回退 + 手动回退**，硬崩溃回退作为 v2 扩展点。

### 6.2 软崩溃自动回退

#### 健康检查点

```typescript
class LauncherHealthChecker {
  async runPostStartupChecks(): Promise<HealthCheckResult> {
    const checks = [
      this.checkMainWindowLoaded(),        // 3 秒内主窗口可见
      this.checkPythonBackendHealthy(),    // /health 返回 200
      this.checkDatabaseAccessible(),      // 向量库能读写
      this.checkCoreIpcResponsive(),       // IPC 调用能在 5 秒内响应
    ];
    
    const results = await Promise.allSettled(checks);
    return {
      passed: results.every(r => r.status === "fulfilled"),
      details: results
    };
  }
  
  private async checkPythonBackendHealthy() {
    const maxRetries = 10;
    const retryInterval = 1000; // 1 秒
    
    for (let i = 0; i < maxRetries; i++) {
      try {
        const response = await fetch("http://127.0.0.1:8765/health", {
          timeout: 2000
        });
        if (response.ok) return;
      } catch {
        // 继续重试
      }
      await sleep(retryInterval);
    }
    
    throw new Error("Python backend failed to become healthy after 10s");
  }
}
```

#### 崩溃计数 + 自动回退触发

```typescript
class UpdateManager {
  async onAppStartup() {
    // 1. 读取状态
    const state = await this.loadState();
    
    // 2. 如果是新安装版本（currentVersion 与上次记录不同）
    if (state.currentVersion !== state.lastRecordedVersion) {
      state.crashCount = 0;
      state.lastRecordedVersion = state.currentVersion;
    }
    
    // 3. 运行健康检查
    const health = await this.healthChecker.runPostStartupChecks();
    
    if (!health.passed) {
      state.crashCount++;
      await this.saveState();
      
      if (state.crashCount >= 3) {
        // 连续 3 次启动都失败 → 自动回退
        logger.error("Auto-rollback triggered: 3 consecutive failed startups");
        await this.rollback("auto-rollback:health-check-failed");
        return;
      }
      
      // 提示用户
      this.showDialog({
        title: "启动失败",
        message: `应用启动出现异常（${state.crashCount}/3 次）。继续失败将自动回退到 ${state.lastKnownGoodVersion}。`,
        buttons: ["重试", "回退到上一版本", "查看详情"]
      });
    } else {
      // 健康检查通过，重置崩溃计数
      if (state.crashCount > 0) {
        state.crashCount = 0;
        await this.saveState();
      }
      
      // 首次通过 → commit 为新版本
      await this.commitUpdate();
    }
  }
}
```

### 6.3 手动回退（N 天窗口）

```typescript
class UpdateManager {
  async canManualRollback(): Promise<{ allowed: boolean, reason?: string }> {
    const state = await this.loadState();
    
    if (!state.lastKnownGoodVersion) {
      return { allowed: false, reason: "没有已知的稳定版本" };
    }
    
    if (state.currentVersion === state.lastKnownGoodVersion) {
      return { allowed: false, reason: "当前已是稳定版本" };
    }
    
    const installDate = new Date(state.lastKnownGoodInstallDate);
    const daysSinceInstall = (Date.now() - installDate.getTime()) / (1000 * 60 * 60 * 24);
    
    if (daysSinceInstall > state.rollbackWindowDays) {
      return { 
        allowed: false, 
        reason: `回退窗口已关闭（${state.rollbackWindowDays} 天）` 
      };
    }
    
    return { allowed: true };
  }
  
  async manualRollback() {
    const check = await this.canManualRollback();
    if (!check.allowed) {
      throw new Error(check.reason);
    }
    
    await this.rollback("manual-rollback:user-requested");
  }
}
```

### 6.4 回退的实现机制

**核心问题**：新版已覆盖安装，如何恢复到上一版？

**策略：保留上一版安装包 + 旧安装目录快照**

```
Windows 升级前目录结构：
  C:\Users\<user>\AppData\Local\Programs\Sage\              ← 当前版本 (v0.2.5)
  C:\Users\<user>\AppData\Local\Programs\Sage\.prev\        ← 上一版快照 (v0.2.4)
  %APPDATA%\Sage\updates\cache\
    └── Sage-Setup-0.2.5.exe                                ← 上一版安装包

升级过程：
  1. 当前目录 Sage\ 重命名为 Sage\.prev\ (原子操作，瞬间)
  2. NSIS 安装器创建新的 Sage\ 目录 (v0.3.0)
  3. 如果健康检查失败:
     a. 删除新 Sage\ 目录
     b. 把 Sage\.prev\ 重命名回 Sage\ (恢复 v0.2.5)
     c. 启动应用
```

#### 实现代码

```typescript
class RollbackExecutor {
  private installDir = path.dirname(process.execPath);
  private prevDir = path.join(this.installDir, "..", ".prev");
  private updateCacheDir = path.join(app.getPath("userData"), "updates", "cache");
  
  async prepareForUpgrade() {
    // 升级前：备份当前安装目录为 .prev
    if (await fs.pathExists(this.prevDir)) {
      await fs.remove(this.prevDir); // 清理旧的 .prev
    }
    
    // Windows: 应用还在运行，不能直接 rename 自己的目录
    // 解决：写一个 post-install 脚本，在应用退出后执行
    const renameScript = this.generatePostInstallScript();
    await fs.writeFile(
      path.join(this.installDir, "..", ".prepare-rollback.bat"),
      renameScript
    );
  }
  
  private generatePostInstallScript(): string {
    return `
@echo off
timeout /t 2 /nobreak >nul
move /y "${this.installDir}" "${this.prevDir}"
del "%~f0"
`;
  }
  
  async rollback(reason: string) {
    logger.info(`Rolling back: ${reason}`);
    
    // 1. 上报回退事件
    await this.reportRollbackEvent(reason);
    
    // 2. 检查 .prev 目录是否存在
    if (!await fs.pathExists(this.prevDir)) {
      // 没有 .prev，尝试用安装包重新安装
      await this.reinstallFromPackage();
      return;
    }
    
    // 3. 删除新版安装目录
    await fs.remove(this.installDir);
    
    // 4. 恢复 .prev 为正式目录
    await fs.rename(this.prevDir, this.installDir);
    
    // 5. 更新状态
    const state = await this.loadState();
    state.currentVersion = state.lastKnownGoodVersion;
    state.crashCount = 0;
    await this.saveState();
    
    // 6. 重启应用
    app.relaunch();
    app.exit(0);
  }
  
  private async reinstallFromPackage() {
    // 从缓存的安装包重新安装上一版
    const state = await this.loadState();
    const packagePath = path.join(
      this.updateCacheDir, 
      `Sage-Setup-${state.lastKnownGoodVersion}.exe`
    );
    
    if (!await fs.pathExists(packagePath)) {
      throw new Error("No rollback package available");
    }
    
    // 静默重新安装
    const { spawn } = require("child_process");
    const installer = spawn(packagePath, ["/S", "/D=" + this.installDir]);
    await new Promise((resolve, reject) => {
      installer.on("exit", (code: number) => {
        code === 0 ? resolve(null) : reject(new Error(`Installer exited with ${code}`));
      });
    });
  }
}
```

### 6.5 存储开销控制

| 项目 | 占用空间 | 清理策略 |
|---|---|---|
| 上一版安装包（缓存）| ~150MB | 升级成功后 7 天自动清理 |
| `.prev` 目录（文件级快照）| ~200MB | 升级成功后立即删除 |
| `update-state.json` | ~1KB | 永久保留 |
| 回退日志 | ~100KB | 滚动保留最近 10 条 |

**总开销**：升级期间最多 ~350MB，升级成功后回落到 ~150MB（仅保留安装包供紧急回退）。

用户可在设置中手动清理缓存：
```typescript
async clearUpdateCache() {
  await fs.remove(this.updateCacheDir);
  await fs.remove(this.prevDir);
  logger.info("Update cache cleared");
}
```

### 6.6 硬崩溃回退（v2 扩展点）

MVP 不做，但架构预留：

```typescript
// 外部 Launcher（未来实现）
// Windows: 注册为默认启动程序（Start Menu 快捷方式指向 launcher.exe）
// Linux: shell 脚本包装

interface ExternalLauncher {
  // 启动 Sage 前：
  // 1. 读取 update-state.json 的 crashCount
  // 2. 启动 Sage 进程
  // 3. 监控进程退出码
  //    - exit(0): 正常退出
  //    - exit(non-zero) 或超时: crashCount++
  // 4. crashCount >= 3: 触发 rollback
  launch(): Promise<void>;
}
```

## 7. 安全与校验

### 7.1 威胁模型

| 威胁 | 风险 | 防御 |
|---|---|---|
| 中间人篡改下载的安装包 | 恶意代码注入 | HTTPS + SHA-512 校验 + 代码签名 |
| 元数据服务被攻破 | 伪造"最新版本"指向恶意包 | HTTPS + 元数据签名（可选）|
| 本地状态文件被篡改 | 绕过回退机制 | 状态文件 HMAC（可选）|
| 回退机制被滥用 | 恶意降级到含漏洞版本 | 回退目标必须是 lastKnownGood，不允许任意版本 |

### 7.2 传输层安全

**强制 HTTPS**：
- 元数据服务：`https://updates.sage.app/*`
- 文件存储：`https://cdn.sage.app/*`（S3 + CloudFront）

**证书钉扎（Certificate Pinning）**：
```typescript
// Electron main.ts
app.on("certificate-error", (event, webContents, url, error, certificate, callback) => {
  // 只对更新服务器启用证书钉扎
  if (url.startsWith("https://updates.sage.app/")) {
    const expectedFingerprint = "AB:CD:EF:..."; // 从 config 读取
    if (certificate.fingerprint !== expectedFingerprint) {
      logger.error("Certificate pinning failed for update server");
      callback(false);
      return;
    }
  }
  callback(true);
});
```

### 7.3 安装包完整性校验

**SHA-512 校验**（electron-updater 内置）：

```yaml
# latest.yml（由 electron-builder 自动生成）
version: 0.3.0
files:
  - url: Sage-Setup-0.3.0.exe
    sha512: abc123...  # ← electron-builder 计算
    size: 157286400
```

electron-updater 下载后自动校验：
```typescript
autoUpdater.on("error", (error) => {
  if (error.message.includes("sha512")) {
    logger.error("Package integrity check failed — possible tampering");
    // 不触发安装，通知用户
  }
});
```

### 7.4 代码签名

**Windows（Authenticode）**：
```yaml
# electron-builder.yml
win:
  signtoolOptions:
    sign: scripts/sign-windows.js  # 自定义签名脚本
    signingHashAlgorithms:
      - sha256
```

签名脚本（Phase 3 实现）：
```javascript
// scripts/sign-windows.js
exports.default = async function sign(configuration) {
  // 使用 EV 代码签名证书（硬件 token 或云 HSM）
  // 避免私钥泄露风险
  const certFingerprint = process.env.WINDOWS_CERT_FINGERPRINT;
  
  await execa("signtool", [
    "sign",
    "/fd", "sha256",
    "/sha1", certFingerprint,
    "/tr", "http://timestamp.digicert.com",
    "/td", "sha256",
    configuration.path
  ]);
};
```

**Linux（GPG 签名）**：
```bash
# 发布流程（CI/CD）
gpg --detach-sign --armor Sage-0.3.0.AppImage
# 生成 Sage-0.3.0.AppImage.asc

# 客户端校验（electron-updater 自动）
# latest-linux.yml 包含：
# - url: Sage-0.3.0.AppImage
#   sha512: ...
#   signature: <base64-encoded GPG signature>
```

### 7.5 元数据服务认证

**方案 A：只读公开 API（MVP）**
- `/api/v1/updates/channels/{channel}/latest` 无需认证
- 依赖 HTTPS + SHA-512 + 代码签名保证安全
- 简单，但无法防止元数据服务被攻破

**方案 B：元数据签名（推荐，v1.1）**
```python
# 元数据服务端
import json
import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def sign_manifest(manifest: dict) -> str:
    """用私钥签名元数据"""
    private_key = load_private_key()  # 从 HSM / 环境变量
    manifest_json = json.dumps(manifest, sort_keys=True)
    signature = private_key.sign(
        manifest_json.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()

# 响应包含签名
{
  "manifest": {...},
  "signature": "base64..."
}
```

客户端校验：
```typescript
async function verifyManifestSignature(response: any) {
  const publicKey = loadEmbeddedPublicKey(); // 嵌入在 Electron 代码中
  const manifestJson = JSON.stringify(response.manifest, null, 2);
  const signature = Buffer.from(response.signature, "base64");
  
  const isValid = publicKey.verify(
    signature,
    Buffer.from(manifestJson),
    padding.PKCS1v15(),
    hashes.SHA256()
  );
  
  if (!isValid) {
    throw new Error("Manifest signature invalid — possible tampering");
  }
}
```

**方案 C：双向认证（v2，如需灰度发布）**
- 客户端用 API Key 认证
- 服务端根据用户 ID / 渠道返回不同版本
- 用于 A/B 测试、灰度发布

### 7.6 本地状态文件保护

```typescript
// update-state.json 的完整性校验
import { createHmac } from "crypto";

class StateManager {
  private secretKey = "sage-update-state-key"; // 从环境变量读取
  
  async saveState(state: UpdateState) {
    const stateJson = JSON.stringify(state);
    const hmac = createHmac("sha256", this.secretKey)
      .update(stateJson)
      .digest("hex");
    
    const payload = {
      state,
      hmac
    };
    
    await fs.writeFile(this.statePath, JSON.stringify(payload));
  }
  
  async loadState(): Promise<UpdateState> {
    const payload = JSON.parse(await fs.readFile(this.statePath, "utf-8"));
    const expectedHmac = createHmac("sha256", this.secretKey)
      .update(JSON.stringify(payload.state))
      .digest("hex");
    
    if (payload.hmac !== expectedHmac) {
      logger.error("State file tampered — resetting to defaults");
      return this.getDefaultState();
    }
    
    return payload.state;
  }
}
```

### 7.7 回退目标的限制

```typescript
async function rollback(targetVersion?: string) {
  const state = await loadState();
  
  // 只允许回退到 lastKnownGood，不允许任意版本
  if (targetVersion && targetVersion !== state.lastKnownGoodVersion) {
    throw new Error("Can only rollback to lastKnownGoodVersion");
  }
  
  // 防止降级攻击：lastKnownGood 必须 >= minUpgradableVersion
  const manifest = await fetchLatestManifest();
  if (compareVersions(state.lastKnownGoodVersion, manifest.min_upgradable_version) < 0) {
    throw new Error("lastKnownGoodVersion is too old — full reinstall required");
  }
  
  // 执行回退
  await rollbackExecutor.rollback(state.lastKnownGoodVersion);
}
```

## 8. 配置与可扩展性

### 8.1 配置文件结构

```typescript
// ~/.sage/update-config.json
{
  "updateStrategy": "auto-download",     // "manual" | "auto-download" | "auto-install"
  "channel": "stable",                   // "stable" | "beta" | "alpha"
  "rollbackWindowDays": 7,               // 手动回退窗口（天）
  "autoRollbackThreshold": 3,            // 连续失败 N 次触发自动回退
  "checkIntervalHours": 24,              // 自动检查更新间隔（小时）
  "updateServerUrl": "https://updates.sage.app",
  "enableTelemetry": true,               // 是否上报回退事件
  "cacheRetentionDays": 7                // 安装包缓存保留天数
}
```

**默认值**（首次启动时生成）：
```typescript
const DEFAULT_CONFIG: UpdateConfig = {
  updateStrategy: "auto-download",
  channel: "stable",
  rollbackWindowDays: 7,
  autoRollbackThreshold: 3,
  checkIntervalHours: 24,
  updateServerUrl: "https://updates.sage.app",
  enableTelemetry: true,
  cacheRetentionDays: 7
};
```

### 8.2 设置页 UI

```tsx
// src/pages/settings/UpdateSettings.tsx
export function UpdateSettings() {
  const [config, setConfig] = useUpdateConfig();
  
  return (
    <SettingsPage title="更新设置">
      <Section title="更新策略">
        <RadioGroup 
          value={config.updateStrategy}
          onChange={(v) => setConfig({ ...config, updateStrategy: v })}
        >
          <Radio value="manual">手动更新</Radio>
          <Radio value="auto-download">自动下载，手动安装（推荐）</Radio>
          <Radio value="auto-install">自动下载安装</Radio>
        </RadioGroup>
      </Section>
      
      <Section title="更新渠道">
        <Select 
          value={config.channel}
          onChange={(v) => setConfig({ ...config, channel: v })}
        >
          <Option value="stable">稳定版（推荐）</Option>
          <Option value="beta">测试版（可能有 bug）</Option>
          <Option value="alpha">预览版（最新功能，不稳定）</Option>
        </Select>
      </Section>
      
      <Section title="高级选项">
        <NumberInput
          label="回退窗口（天）"
          value={config.rollbackWindowDays}
          onChange={(v) => setConfig({ ...config, rollbackWindowDays: v })}
          min={1}
          max={30}
        />
        
        <NumberInput
          label="自动检查间隔（小时）"
          value={config.checkIntervalHours}
          onChange={(v) => setConfig({ ...config, checkIntervalHours: v })}
          min={1}
          max={168}
        />
        
        <Button onClick={clearCache}>清理更新缓存</Button>
      </Section>
    </SettingsPage>
  );
}
```

### 8.3 可扩展性设计

#### 8.3.1 按组件更新（v2）

**数据模型预留**：
```typescript
interface UpdateManifest {
  version: string;
  components: {
    electron: string;
    python: string;
    backend: string;
  };
  // ...
}
```

**未来实现**：
```typescript
class ComponentUpdateManager {
  async checkComponentUpdates() {
    const manifest = await fetchLatestManifest();
    const current = await getCurrentComponentVersions();
    
    const updates = [];
    if (manifest.components.electron !== current.electron) {
      updates.push({ component: "electron", version: manifest.components.electron });
    }
    if (manifest.components.python !== current.python) {
      updates.push({ component: "python", version: manifest.components.python });
    }
    // ...
    
    return updates;
  }
  
  async downloadComponentUpdate(component: string) {
    // 只下载特定组件的更新包
    // 例如：python-runtime-3.11.10.zip
  }
}
```

#### 8.3.2 灰度发布（v2）

**元数据服务扩展**：
```python
# FastAPI 后端
@app.get("/api/v1/updates/channels/{channel}/latest")
async def get_latest(channel: str, user_id: str = None):
    manifest = get_manifest(channel)
    
    # 灰度逻辑
    if channel == "stable" and user_id:
        rollout_percentage = get_rollout_percentage(manifest.version)
        if hash(user_id) % 100 >= rollout_percentage:
            # 用户不在灰度范围内，返回上一版本
            return get_previous_manifest(channel)
    
    return manifest
```

**客户端上报 user_id**：
```typescript
async function checkForUpdates() {
  const userId = await getUserId(); // 从本地配置或生成 UUID
  const response = await fetch(
    `${UPDATE_SERVER}/api/v1/updates/channels/stable/latest?user_id=${userId}`
  );
  // ...
}
```

#### 8.3.3 外部 Launcher（v2）

预留接口：
```typescript
interface LauncherInterface {
  // 外部 Launcher 调用这些接口
  onStartupComplete(success: boolean): void;
  onHealthCheckPassed(passed: boolean): void;
  requestRollback(): void;
}

// Electron main.ts
if (process.env.SAGE_LAUNCHER_MODE) {
  const launcher = createLauncherInterface();
  
  app.on("ready", () => {
    launcher.onStartupComplete(true);
  });
  
  healthChecker.on("check-complete", (result) => {
    launcher.onHealthCheckPassed(result.passed);
  });
  
  ipcMain.on("update:rollback", () => {
    launcher.requestRollback();
  });
}
```

### 8.4 日志与监控

#### 日志记录

```typescript
class UpdateLogger {
  private logPath = path.join(app.getPath("userData"), "logs", "update.log");
  
  info(message: string, context?: any) {
    this.write("INFO", message, context);
  }
  
  error(message: string, error?: Error) {
    this.write("ERROR", message, { error: error?.message, stack: error?.stack });
  }
  
  private write(level: string, message: string, context?: any) {
    const entry = {
      timestamp: new Date().toISOString(),
      level,
      message,
      context
    };
    
    fs.appendFile(this.logPath, JSON.stringify(entry) + "\n");
  }
}
```

**日志保留策略**：
- 单文件最大 10MB
- 滚动保留最近 5 个文件（`update.log.1`, `update.log.2`, ...）
- 用户可在设置中导出日志

#### 监控指标（Telemetry）

```typescript
interface UpdateTelemetry {
  event: "update-check" | "update-download" | "update-install" | "update-rollback";
  timestamp: string;
  version: string;
  channel: string;
  duration?: number;      // 下载/安装耗时（秒）
  success: boolean;
  error?: string;
  crashCount?: number;    // 回退时的崩溃次数
}

async function reportTelemetry(event: UpdateTelemetry) {
  const config = await loadConfig();
  if (!config.enableTelemetry) return;
  
  await fetch(`${config.updateServerUrl}/api/v1/telemetry/updates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event)
  });
}
```

### 8.5 测试策略

#### 单元测试

```typescript
// tests/unit/update-manager.test.ts
describe("UpdateManager", () => {
  it("should trigger auto-rollback after 3 failed health checks", async () => {
    const manager = new UpdateManager();
    
    // 模拟 3 次启动失败
    await manager.onAppStartup(); // crashCount = 1
    await manager.onAppStartup(); // crashCount = 2
    await manager.onAppStartup(); // crashCount = 3, 触发回退
    
    const state = await manager.loadState();
    expect(state.currentVersion).toBe(state.lastKnownGoodVersion);
  });
  
  it("should not allow rollback outside window", async () => {
    const manager = new UpdateManager();
    
    // 设置 lastKnownGoodInstallDate 为 10 天前
    const state = await manager.loadState();
    state.lastKnownGoodInstallDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
    await manager.saveState();
    
    const result = await manager.canManualRollback();
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("窗口已关闭");
  });
});
```

#### 集成测试

```typescript
// tests/integration/update-flow.test.ts
describe("Update Flow (Integration)", () => {
  it("should download and install update successfully", async () => {
    // Mock 元数据服务
    mockServer.get("/api/v1/updates/channels/stable/latest", (req, res) => {
      res.json({
        version: "0.3.0",
        files: { "win-x64": { url: "http://mock-cdn/Sage-0.3.0.exe", sha512: "..." } }
      });
    });
    
    // Mock 文件服务器
    mockServer.get("/releases/v0.3.0/Sage-0.3.0.exe", (req, res) => {
      res.sendFile("/path/to/test-fixture.exe");
    });
    
    const manager = new UpdateManager();
    await manager.checkForUpdates();
    await manager.downloadUpdate();
    
    const state = await manager.loadState();
    expect(state.pendingUpdate).not.toBeNull();
  });
});
```

#### E2E 测试

```typescript
// tests/e2e/update-e2e.test.ts
describe("Update E2E", () => {
  it("should upgrade from v0.2.5 to v0.3.0 and rollback on failure", async () => {
    // 1. 安装 v0.2.5
    await installVersion("0.2.5");
    
    // 2. 启动应用，检查更新
    const app = await launchApp();
    await app.updateManager.checkForUpdates();
    
    // 3. 下载并安装 v0.3.0
    await app.updateManager.downloadUpdate();
    await app.updateManager.installUpdate();
    
    // 4. 模拟健康检查失败
    await mockPythonBackendFailure();
    
    // 5. 连续启动 3 次，触发自动回退
    for (let i = 0; i < 3; i++) {
      await app.restart();
      await app.updateManager.onAppStartup();
    }
    
    // 6. 验证回退到 v0.2.5
    const state = await app.updateManager.loadState();
    expect(state.currentVersion).toBe("0.2.5");
  });
});
```

## 9. 实施计划

### 9.1 工作量估算

| 模块 | 工作量 | 优先级 |
|---|---|---|
| 元数据服务（FastAPI + JSON 存储）| 2 天 | P0 |
| 客户端 UpdateManager（状态机 + IPC）| 3 天 | P0 |
| 覆盖升级协调器（备份 + 恢复）| 2 天 | P0 |
| 回退机制（自动 + 手动）| 3 天 | P0 |
| 安全（HTTPS + 签名 + 校验）| 2 天 | P0 |
| 设置页 UI | 1 天 | P1 |
| 日志 + Telemetry | 1 天 | P1 |
| 测试（unit + integration + e2e）| 3 天 | P1 |
| **总计** | **~17 天** | |

### 9.2 里程碑

**M1：元数据服务 + 基础更新流程（P0，5 天）**
- FastAPI 路由 `/api/v1/updates/*`
- UpdateManager 状态机
- electron-updater 集成
- 基本的版本检查 + 下载 + 安装

**M2：覆盖升级 + 回退机制（P0，5 天）**
- NSIS 配置 + 自定义脚本
- UpgradeCoordinator（备份 + 恢复）
- Launcher 健康检查
- 自动回退 + 手动回退

**M3：安全 + 设置页（P0+P1，4 天）**
- HTTPS + SHA-512 校验
- 代码签名（Windows Authenticode + Linux GPG）
- 设置页 UI（更新策略 + 渠道选择）

**M4：日志 + 测试（P1，3 天）**
- UpdateLogger
- Telemetry 上报
- 单元测试 + 集成测试 + E2E 测试

## 10. 风险与缓解

### 10.1 技术风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| electron-updater 与自定义逻辑集成复杂 | 开发延期 | 先做 spike，验证集成点 |
| Windows 上应用运行时无法 rename 自己的目录 | 回退失败 | 用 post-install 脚本延迟执行 |
| Python 后端健康检查误判（网络延迟等）| 误触发回退 | 重试 10 次（10 秒），阈值可调 |
| 元数据服务被攻破 | 分发恶意更新 | v1.1 加元数据签名，MVP 依赖 HTTPS |

### 10.2 产品风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 用户不理解"自动回退"机制 | 误以为数据丢失 | UI 提示 + 日志可见 |
| 回退窗口（7 天）太短/太长 | 用户体验差 | 设置页可调，默认 7 天 |
| 更新包过大（~150MB）| 用户流量消耗 | 未来做差分更新（v2）|

## 11. 附录

### 11.1 术语表

- **lastKnownGood**：上次健康检查通过的版本
- **软崩溃**：Electron 还能运行时的崩溃（如 Python 后端启动失败）
- **硬崩溃**：Electron 无法启动（如进程崩溃、JS 异常）
- **覆盖升级**：保留用户数据，覆盖安装到原目录

### 11.2 参考资料

- [electron-updater 文档](https://www.electron.build/auto-update)
- [electron-builder NSIS 配置](https://www.electron.build/configuration/nsis)
- [Windows 代码签名](https://docs.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-portal)
- [Linux GPG 签名](https://www.gnupg.org/gph/en/manual.html)

### 11.3 决策记录

**D1：为什么用 electron-updater 而不是完全自研？**
- 理由：electron-updater 已实现下载、校验、续传等通用逻辑，重复造轮子成本高
- 权衡：与 electron-builder 强绑定，但 Sage 已用 electron-builder，无额外成本

**D2：为什么 MVP 不做硬崩溃回退？**
- 理由：需要外部 Launcher，增加复杂性；软崩溃已覆盖大部分场景
- 权衡：Electron 进程崩溃无法自动回退，但可通过手动回退解决

**D3：为什么元数据服务复用现有后端？**
- 理由：Sage 已有 FastAPI 基础设施，独立服务增加运维成本
- 权衡：更新服务与业务服务耦合，但路由独立，可独立部署
