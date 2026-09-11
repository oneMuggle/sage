# 可插拔更新源（Pluggable Update Providers）

> 让 Sage 不再绑死官方更新服务器——你可以把更新源换成 GitHub / Gitee / GitLab 仓库，甚至自建 HTTP 服务。

## 什么是更新源？

更新源就是 Sage 检查"有没有新版本"的地方。默认情况下，Sage 会去官方服务器 `updates.sage.app` 查。可插拔更新源允许你：

- 把更新源切到 **GitHub Releases**（仓库 `owner/repo`，如 `oneMuggle/sage`）
- 把更新源切到 **Gitee Releases**（国内用户友好）
- 把更新源切到 **GitLab Releases**（含自建 GitLab 实例的 baseUrl）
- 自建 HTTP 端点（advanced，需 RSA 公钥）

---

## 快速开始

### 1. 进入更新源设置

打开 Sage → 点击右上角 **⚙️ 设置** → 左侧栏选 **更新源** tab。

首次进入会看到一个表格：

| 名称 | 类型 | 默认 | 启用 | 操作 |
|---|---|---|---|---|
| Official (updates.sage.app) | generic-http | ★ | ✓ | 测试连接 |

官方源不可删除，但你可以把它从"默认"切下来。

### 2. 添加自定义源

点击右上角 **＋ 添加更新源** 按钮，会弹出添加向导：

| 步骤 | 提示 | 必填 |
|---|---|---|
| 1. 平台 | github / gitee / gitlab / 自建 HTTP | 必选 |
| 2. 显示名称 | 在表格里看到的中文/英文名 | 必填 |
| 3. 仓库路径 | `owner/repo`（GitHub/GitLab）或 `owner/repo`（Gitee） | 必填 |
| 4. 自建地址 | GitLab 自建 baseUrl 或 自建 HTTP 的 manifest URL | 视情况 |
| 5. 凭证 | 私有仓库需填 access_token / PRIVATE-TOKEN（自动 mask，不会显示原文） | 选填 |
| 6. 渠道映射 | 哪些 release channel 走这个源 | 全部勾选 |

填写完毕点 **确认**，新行立刻出现在表格里。

### 3. 设为默认

找到你刚加的行，点 **设为默认** 按钮。该行的"默认"列会出现 ★，原默认行 ★ 消失。

### 4. 测试连接

点 **测试连接** 按钮：

- 成功 → 弹窗显示「连接成功（xx ms）」，并在控制台打印耗时
- 失败 → 弹窗显示具体原因（如「凭证无效（HTTP 401）」、「项目不存在（HTTP 404）」、「平台返回 HTTP 500」）

测试不修改任何设置，纯粹是连通性 + 凭证可用性检查。

### 5. 删除自定义源

点 **删除** 按钮 → 二次确认 → 移除。

> ⚠️ 不能删除官方源。如果它是当前默认源，删除其他源后默认会自动切回官方。

---

## 4 个平台分别怎么填

### GitHub

| 字段 | 例子 | 说明 |
|---|---|---|
| 仓库 | `oneMuggle/sage` | owner/repo 形式 |
| Token | `ghp_xxx...` | 私有仓库必填，公开仓库留空 |
| baseUrl | 留空 | 公开 GitHub 走 api.github.com；想用 GitHub Enterprise 填 `https://github.acme.com/api/v3` |

### Gitee（码云）

| 字段 | 例子 | 说明 |
|---|---|---|
| 仓库 | `muggle/sage-mirror` | owner/repo 形式 |
| Token | 私人令牌 | https://gitee.com/profile/personal_access_tokens 新建，需 `projects` scope |
| baseUrl | 留空 | 公开 Gitee 走 gitee.com/api/v5；自建 Gitee 填对应地址 |

### GitLab

| 字段 | 例子 | 说明 |
|---|---|---|
| 项目 | `mygroup/sage-fork` | URL-encoded group/subgroup/project 形式 |
| Token | `glpat-xxx...` | PRIVATE-TOKEN（Project Access Token），需 `read_api` scope |
| baseUrl | `https://gitlab.acme.com` | 自建 GitLab 必填；公开 gitlab.com 留空 |

### 自建 HTTP（advanced）

仅在你自建了 Sage-compatible manifest 端点时使用。需要：

- 一个 HTTPS URL 返回 manifest JSON（含 `version`、`channel`、`assets`、`signature`）
- 一个 RSA 公钥（用于校验 manifest 签名）

详细 manifest schema 见 [`docs/technical/56-update-providers.md`](../../technical/56-update-providers.md) §4.2。

---

## 常见问题

### Q: 加了自定义源但检查更新仍然走官方？

检查两点：

1. 该源是否设为默认（★ 标记）
2. 当前 channel 是否在 channelMap 里勾选（比如你想看 beta 渠道，但 channelMap.beta 没勾）

### Q: Token 会泄露吗？

不会。Token 在主进程用 Electron `safeStorage` 加密后存到本地 electron-store（macOS Keychain / Windows DPAPI / Linux kwallet），renderer 通过 IPC 拿到的永远是 `'***masked***'`。截图分享设置页也是安全的。

### Q: 测试连接成功，但实际下载失败？

测试只检查连通性 + 凭证可用性。下载阶段还要校验：

- 当前 channel 是否有对应 release（alpha 渠道需要仓库打过 alpha tag 并勾选 channelMap）
- 平台 release 必须包含与你系统匹配的 asset（Windows `.exe` / macOS `.dmg` / Linux `.AppImage`）

### Q: 切换默认源后要重启吗？

不需要。UpdateManager 在下次检查更新时自动用新默认源。

### Q: 如何临时回滚到只用官方源？

在设置页把官方源之外的全部自定义源删除，或者：

```bash
# 重启 Sage 时关闭 pluggable UI（紧急回滚）
SAGE_EXPERIMENTAL_PROVIDERS=0 ./Sage.AppImage
```

关闭后 UI 看不到更新源 tab，自动回到只用官方源的旧行为。

### Q: 多渠道（alpha / beta / stable）能同时配多个源吗？

可以。比如你可以：

- 官方源 → stable（channelMap.stable=true）
- 自己的 GitHub fork → alpha（channelMap.alpha=true）

不同 channel 走不同源。UpdateManager 按 channel 查表。

---

## 与现有更新流程的关系

可插拔更新源**不改变**更新流程的下载/校验/安装步骤——这些仍由 Electron `app.updateFromFile()` 处理。它只是把"去哪里找新版本"这一步从硬编码变成可配置。

如果你之前用过「立即检查更新」，体验完全一样，只是背后的查询 endpoint 变了。