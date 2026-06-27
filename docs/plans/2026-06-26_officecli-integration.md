# OfficeCLI 集成方案

> 参考 AionUi 项目的实现，为 Sage 项目集成 OfficeCLI，实现 Office 文档（PPT/Word/Excel）的本地预览。

## 1. 背景与目标

### 1.1 背景

AionUi 通过外部二进制工具 **OfficeCLI**（.NET 编写，发布在 https://github.com/iOfficeAI/OfficeCLI）实现 Office 文档的预览。OfficeCLI 以子进程方式运行，对外暴露 HTTP 服务，将 `.pptx/.docx/.xlsx` 渲染为网页（支持 PPT Morph 转场等高级特性）。AionUi 通过 Rust 后端 `aioncore` 启动它；Sage 的 Python FastAPI 后端可以用等价的方式接管该职责。

### 1.2 目标

- 用户在 Sage 中点击 `.pptx / .docx / .xlsx` 文件时，在应用内直接预览，无需外部软件
- 复用 AionUi 的 `OfficeWatchViewer` 组件（`docType` 参数化，一份代码覆盖三类文档）
- 复用 AionUi 的 5 个错误码分类，便于国际化与用户引导
- 保持 Sage 已有架构（Electron + React + FastAPI）不被破坏
- 可选：桌面端缺失二进制时自动下载安装，降低用户门槛

### 1.3 非目标（v1 范围外）

- 不实现文档编辑、协同编辑
- 不替换 Office 文件在系统中的默认打开方式
- 不引入 LibreOffice / MS Office 等重型依赖

---

## 2. 涉及的文件与模块

### 2.1 后端（Python FastAPI）

| 路径 | 用途 |
|---|---|
| `backend/api/office_preview.py`（新增） | `APIRouter(prefix="/office-preview")`，挂载到 `/api/v1`（与 `wiki_routes.py` / `orchestration_router.py` 同模式）；暴露 6 个端点：`/ppt/start`、`/ppt/stop`、`/word/start`、`/word/stop`、`/excel/start`、`/excel/stop` |
| `backend/api/office_status_ws.py`（新增） | WebSocket 端点 `/api/v1/office-preview/ws`，推送 `installing / starting / ready / error` 状态。**注：main 上目前无 WS 基础设施**（`grep -rn "websocket" backend/` 仅命中注释），实现时需先引入 FastAPI WebSocket 路由（建议单独 PR 引入 WS 基础设施后再接入业务） |
| `backend/api/office_watch_proxy.py`（新增，可选） | `/api/v1/office-watch-proxy/{port}/{path:path}` 反向代理，Web 模式用 |
| `backend/services/officecli/__init__.py`（新增） | 包标识文件 |
| `backend/services/officecli/manager.py`（新增） | 管理 `officecli` 子进程生命周期：发现二进制、启动、端口探测、停止 |
| `backend/services/officecli/installer.py`（新增） | 自动下载安装 OfficeCLI（首次使用时触发，跨平台：Linux/macOS/Windows） |
| `backend/services/officecli/sandbox.py`（新增） | 校验文件路径是否在工作区内（对应 `PATH_OUTSIDE_SANDBOX`） |
| `backend/services/officecli/ports.py`（新增，可选） | 端口分配与回收辅助（防止多工作区端口冲突） |
| `backend/main.py` | 注册新路由与 WS 端点（`app.include_router(office_preview_router, prefix="/api/v1")`） |
| `backend/requirements.txt` | 增加 `httpx`（反向代理）/ `aiofiles`（如需） |
| `backend/config.yaml` | 增加 `officecli.binary_path` / `officecli.auto_install` / `officecli.port_range` / `officecli.idle_timeout_seconds` |

### 2.2 前端（React）

| 路径 | 用途 |
|---|---|
| `src/features/office-preview/OfficeWatchViewer.tsx`（新增） | 从 AionUi 移植，参数化支持 `ppt / word / excel` |
| `src/features/office-preview/PptViewer.tsx`（新增） | 薄包装 |
| `src/features/office-preview/OfficeDocViewer.tsx`（新增） | 薄包装（Word） |
| `src/features/office-preview/ExcelViewer.tsx`（新增） | 薄包装 |
| `src/features/office-preview/useOfficePreview.ts`（新增） | Hook：调用 `/api/v1/office-preview/{doc}/start` 与 WS 状态订阅 |
| `src/features/office-preview/errorActions.ts`（新增） | 错误码 → 用户动作映射（安装链接、重试、命令提示） |
| `src/features/office-preview/constants.ts`（新增） | `OFFICECLI_INSTALL_URL` / `OFFICECLI_SERVER_INSTALL_COMMAND` |
| `src/shared/api/httpBridge.ts`（新增或扩展） | 统一 HTTP 客户端（baseUrl 走 vite proxy / 环境变量） |
| `src/shared/api/wsBridge.ts`（新增或扩展） | WebSocket 客户端（状态推送） |
| `src/pages/chat/components/PreviewPanel.tsx`（修改） | 根据文件后缀路由到对应 Viewer |
| `src/features/office-preview/i18n/*.json`（新增） | 12 语种错误/安装提示文案（可从 AionUi 直接迁移） |

### 2.3 Electron 主进程（可选）

| 路径 | 用途 |
|---|---|
| `electron/ipc/officePreview.ts`（新增，可选） | 若 Web 模式不需要反向代理，可在主进程直接走 HTTP 调 FastAPI；Web 模式则需要反向代理 |

### 2.4 配置 / 部署

| 路径 | 用途 |
|---|---|
| `vite.config.ts` | 新增 `server.proxy` 配置 `/api/office-watch-proxy` 转发到后端（Web 模式）；当前 main 上无 `proxy:` 块，需新增 |
| `backend/config.yaml` | 增加 `officecli.binary_path` / `officecli.auto_install` / `officecli.port_range` |
| `electron-builder.yml` | （可选）捆绑 officecli 二进制到 `resources/bundled-officecli/` |

---

## 3. 技术方案

### 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  React (Renderer)                                            │
│  ┌──────────────────────────┐  ┌──────────────────────────┐ │
│  │  PptViewer / Word / Excel│  │  useOfficePreview hook   │ │
│  │  (薄包装)                 │→ │  start / stop / status   │ │
│  └──────────────────────────┘  └──────────────────────────┘ │
│                  │                           │                │
│                  ▼                           ▼                │
│         <WebviewHost url={watchUrl} />  HTTP + WebSocket     │
└─────────────────────────────────────────────────────────────┘
                        │
                        │ HTTP POST / WS
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Python FastAPI (port 8765)                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  /api/{doc}-preview/start → OfficePreviewManager     │   │
│  │  /api/{doc}-preview/stop  → kill subprocess          │   │
│  │  /ws → OfficeStatusPublisher                         │   │
│  │  /api/office-watch-proxy/{port}/{path} → reverse proxy│   │
│  └──────────────────────────────────────────────────────┘   │
│                        │                                     │
│                        │ subprocess                          │
│                        ▼                                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  officecli watch <file>                              │   │
│  │  (本地 HTTP 服务，监听 127.0.0.1:<dynamicPort>)       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 接口契约

完全对齐 AionUi 的 IPC/HTTP 约定，方便前端代码移植：

#### HTTP

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/v1/office-preview/ppt/start` | `{ file_path, workspace? }` | `{ url: str, error?: OfficeWatchErrorCode }` |
| POST | `/api/v1/office-preview/ppt/stop` | `{ file_path }` | `{}` |
| POST | `/api/v1/office-preview/word/start` | 同上 | 同上 |
| POST | `/api/v1/office-preview/word/stop` | 同上 | 同上 |
| POST | `/api/v1/office-preview/excel/start` | 同上 | 同上 |
| POST | `/api/v1/office-preview/excel/stop` | 同上 | 同上 |

`OfficeWatchErrorCode` 枚举：
- `OFFICECLI_NOT_FOUND` → 二进制不存在
- `OFFICECLI_INSTALL_FAILED` → 自动下载失败
- `OFFICECLI_PORT_TIMEOUT` → 启动后 30s 未监听端口
- `OFFICECLI_START_FAILED` → 启动时报错
- `PATH_OUTSIDE_SANDBOX` → 文件路径不在工作区内

#### WebSocket

端点：`ws://127.0.0.1:8765/api/v1/office-preview/ws`

消息类型：
- `{ type: "ppt-preview.status", state: "installing" | "starting" | "ready" | "error", file_path?, message? }`
- `{ type: "word-preview.status", ... }`
- `{ type: "excel-preview.status", ... }`

### 3.3 后端核心实现要点

#### 3.3.1 OfficePreviewManager（关键类）

```python
class OfficePreviewManager:
    """每个文件路径一个子进程，按 file_path 索引"""
    def __init__(self, config: OfficeCliConfig): ...
    async def start(self, file_path: Path, workspace: Optional[Path]) -> StartResult:
        # 1. sandbox 校验
        # 2. 找到 officecli 二进制（或触发 installer）
        # 3. asyncio.create_subprocess_exec("officecli", "watch", str(file_path))
        # 4. 解析 stdout 拿到动态端口（officecli watch 输出 URL）
        # 5. 返回 { url: "http://127.0.0.1:<port>" }
    async def stop(self, file_path: Path) -> None:
        # 终止子进程 + 清理
    async def status_stream(self) -> AsyncIterator[StatusEvent]:
        # 推送状态给 WS
```

#### 3.3.2 端口探测策略

OfficeCLI 的 `watch` 命令启动后会打印 URL 到 stdout（参考 AionUi 的解析逻辑）。使用 `asyncio.create_subprocess_exec` + `stdout.readline()` 抓取，带 30s 超时。

#### 3.3.3 自动安装

首次 `OFFICECLI_NOT_FOUND` 时触发：
- Linux/macOS: `curl -fsSL https://d.officecli.ai/install.sh | bash`
- Windows: 下载 `https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/officecli-win-x64.zip` 解压
- 安装过程通过 WS 推送 `installing` 状态

#### 3.3.4 Sandbox 校验

```python
def validate_sandbox(file_path: Path, workspace: Optional[Path]) -> None:
    resolved = file_path.resolve()
    if workspace and not resolved.is_relative_to(workspace.resolve()):
        raise SandboxViolationError(resolved)
    # 额外防御：禁止符号链接逃逸
```

### 3.4 前端核心实现要点

#### 3.4.1 OfficeWatchViewer 移植

从 AionUi 直接移植 `packages/desktop/src/renderer/pages/conversation/Preview/components/viewers/OfficeWatchViewer.tsx`，做以下适配：
- 将 `bridge.pptPreview.start.invoke` 替换为 `httpBridge.post('/api/ppt-preview/start', ...)`
- `<WebviewHost>` 在 Sage 中替换为 `<webview>`（Electron）或 `<iframe>`（Web 模式）
- 错误状态渲染复用 AionUi 的 `resolveOfficeErrorActions` 逻辑

#### 3.4.2 文件类型路由

在 `PreviewPanel` 中：

```tsx
const viewer = useMemo(() => {
  switch (ext) {
    case 'pptx': case 'ppt': return <PptViewer file={file} />;
    case 'docx': case 'doc': return <OfficeDocViewer file={file} />;
    case 'xlsx': case 'xls': return <ExcelViewer file={file} />;
    // 其他格式走原逻辑
  }
}, [file]);
```

#### 3.4.3 卸载清理

```tsx
useEffect(() => {
  return () => {
    httpBridge.post('/api/ppt-preview/stop', { file_path: file.path });
  };
}, [file.path]);
```

### 3.5 国际化

直接从 AionUi 复制 12 个语种的 `preview.json`，合并进 Sage 的 i18n 系统：
- 关键 keys: `officecliNotFound`, `installing`, `installHint`, `startFailed`, `portTimeout`, `sandboxViolation`
- 文件路径: `src/features/office-preview/i18n/{locale}/preview.json`

---

## 4. 实施步骤

> 每步都可独立验证，按顺序推进。

### 里程碑 1：后端骨架（1-2 天）

- [ ] 新建 `backend/services/officecli/manager.py`，实现 `OfficePreviewManager` 骨架（无自动安装）
- [ ] 新建 `backend/services/officecli/sandbox.py`，实现路径校验
- [ ] 新建 `backend/api/office_preview.py`（`APIRouter(prefix="/office-preview")`），注册 6 个端点（3 doc × start/stop）
- [ ] 在 `backend/main.py` 注册路由：`app.include_router(office_preview_router, prefix="/api/v1")`
- [ ] 写 pytest 单元测试覆盖：sandbox 校验、文件不存在、重复 start

**验证：** `curl -X POST http://127.0.0.1:8765/api/v1/office-preview/ppt/start -d '{"file_path":"/tmp/x.pptx"}'` 返回 501/503（officecli 未安装）而非 404。

### 里程碑 2：二进制发现与手动安装指引（0.5 天）

- [ ] 在 `backend/services/officecli/manager.py` 中增加 `find_binary()`：按优先级查找
  - `config.officecli.binary_path`
  - `~/.officecli/bin/officecli`
  - `PATH` 中的 `officecli`
- [ ] 找不到时返回 `OFFICECLI_NOT_FOUND`，响应中包含安装命令/链接
- [ ] 在 Sage 前端增加"安装 OfficeCLI"引导页

**验证：** 手动从 https://github.com/iOfficeAI/OfficeCLI/releases 下载，放到 `~/.officecli/bin/`，start 端点返回 200。

### 里程碑 3：前端 Viewer 移植（1-2 天）

- [ ] 从 AionUi 复制 `OfficeWatchViewer.tsx` 到 `src/features/office-preview/`
- [ ] 适配：替换 `bridge.*` 调用为 `httpBridge.post` / `wsBridge.subscribe`
- [ ] 创建 `PptViewer` / `OfficeDocViewer` / `ExcelViewer` 三个薄包装
- [ ] 在 `PreviewPanel` 中根据文件后缀路由
- [ ] 增加 `useOfficePreview` Hook 封装 start/stop/status

**验证：** 在 Sage 中点击一个 .pptx 文件，弹出预览面板，能看到渲染内容。

### 里程碑 4：WebSocket 状态推送（0.5-1 天）

- [ ] 新建 `backend/api/ws/office_status.py`
- [ ] 在 FastAPI 主 WS 端点增加 3 类消息分发
- [ ] 前端 `useOfficePreview` 订阅 status，渲染 `installing / starting / ready / error` 状态 UI

**验证：** 第一次 start 时，UI 显示"正在安装 officecli..."→"正在启动..."→"就绪"。

### 里程碑 5：自动安装（1 天）

- [ ] 新建 `backend/services/officecli/installer.py`
- [ ] Linux/macOS：调用官方 install.sh
- [ ] Windows：下载 release zip 解压到 `~/.officecli/bin/`
- [ ] 安装失败返回 `OFFICECLI_INSTALL_FAILED` + 详细错误
- [ ] 安装过程通过 WS 推送 `installing` 状态

**验证：** 清空 `~/.officecli/`，在 UI 点击 .pptx 预览，自动下载并渲染成功。

### 里程碑 6：Web 模式反向代理（1 天，可选）

- [ ] 新建 `backend/api/routes/proxy.py`
- [ ] 实现 `/api/office-watch-proxy/{port}/{path}`，使用 `httpx.AsyncClient` 反向代理到 `127.0.0.1:<port>`
- [ ] 处理 WebSocket 升级（officecli 内部可能有 WS，如需要）
- [ ] 在 `vite.config.ts` 增加 dev 代理规则

**验证：** Web 模式（非 Electron）下预览 Office 文件，iframe 同源加载成功。

### 里程碑 7：测试与文档（1 天）

- [ ] 后端 pytest 单元测试覆盖率 ≥ 80%
- [ ] 前端 Vitest 单元测试（mock HTTP/WS）
- [ ] E2E 测试（Playwright）：点击 .pptx → 预览渲染
- [ ] 用户手册：`docs/user-manual/XX-office-preview.md`
- [ ] 技术文档：`docs/technical/XX-officecli-integration.md`（归档本计划）

**验证：** CI 全绿，文档合并到主手册。

---

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| OfficeCLI 二进制体积大（.NET 自包含 ~100MB） | 中 | 默认不捆绑，按需下载；提供 config 选项跳过自动安装 |
| Linux 需 `libicu-dev` 系统依赖 | 中 | 在 installer 中检测并给出明确错误提示；Docker 镜像预装 |
| OfficeCLI 是外部项目，版本升级可能破坏兼容 | 低 | 锁定最低版本；通过 install.sh 走官方发布渠道 |
| 子进程泄漏（忘记 stop） | 中 | 加进程表 + 空闲超时回收；FastAPI shutdown 钩子清理所有子进程 |
| 沙箱逃逸（符号链接等） | 中 | `is_relative_to` + 真实路径解析 + 禁止符号链接跨区 |
| 多工作区场景下端口冲突 | 低 | 端口由 officecli 自选，manager 只读 URL |

### 5.2 依赖

- **外部依赖：** OfficeCLI 二进制（https://github.com/iOfficeAI/OfficeCLI）
- **Python 依赖：** `httpx`（反向代理）, `aiofiles`（如需要）, `watchfiles`（可选：工作区监听触发自动预览）
- **前端依赖：** 无新增（沿用 React + vite）
- **系统依赖（Linux）：** `libicu-dev`

### 5.3 与现有架构的兼容性

- ✅ 不改变 FastAPI 启动流程（只新增路由）
- ✅ 不改变 Electron 主进程结构（HTTP/WS 走现有 8765 端口）
- ✅ 不改变 vite 配置（除非启用 Web 模式反向代理）
- ✅ 前端为纯新增模块，不影响已有 pages/features

### 5.4 与 AionUi 的差异

| 维度 | AionUi | Sage |
|---|---|---|
| 后端 | Rust `aioncore` | Python FastAPI |
| 子进程管理 | Rust `tokio::process` | Python `asyncio.create_subprocess_exec` |
| 二进制分发 | 捆绑到 `resources/bundled-aioncore/` | 按需下载（v1），可升级为捆绑 |
| Web 模式 | `@aionui/web-host` 反向代理 | FastAPI 内置反向代理 |
| 工作区监听 | Rust `notify` crate | 可选用 `watchfiles` 或 AionUi 兼容的 WS 事件 |

### 5.5 ⚠️ release/win7 分支不兼容（关键限制）

**OfficeCLI 无法在 Windows 7 上运行。**

**原因分析：**
- OfficeCLI 基于 **.NET 10 SDK** 构建，发布为自包含二进制（.NET 运行时嵌入在二进制中）
- **.NET 10 运行时不支持 Windows 7**（微软在 .NET Core 3.1 之后即放弃 Win7 支持，.NET 5/6/7/8/9/10 均不支持）
- 自包含部署仅捆绑运行时二进制，不改变 OS 兼容性矩阵
- Sage 的 `release/win7` 分支锁定 **Windows 7 SP1** 为目标平台

**影响范围：**
- 本方案**仅适用于 `main` 分支**
- `release/win7` 分支无法使用 OfficeCLI 实现 Office 预览

**release/win7 分支的替代方案（需独立规划）：**

| 方案 | 优点 | 缺点 | 推荐度 |
|---|---|---|---|
| **A. 纯 Python 渲染**（python-docx + openpyxl + python-pptx → HTML） | 无外部依赖，跨平台 | PPT 渲染效果差，无动画/Morph，开发量大 | ⭐⭐ |
| **B. LibreOffice headless 转 HTML/PDF** | 渲染质量高，格式兼容好 | 体积大（~300MB），启动慢，需捆绑或用户自装 | ⭐⭐⭐ |
| **C. 调用系统默认应用**（`os.startfile()` / `open()`） | 零开发成本，渲染完美 | 离开应用窗口，无法在应用内预览 | ⭐⭐⭐⭐ |
| **D. 云端预览**（Microsoft Graph API / Google Docs Viewer） | 渲染完美，无本地依赖 | 需联网，需 OAuth，隐私敏感 | ⭐⭐ |
| **E. 仅显示文件元信息 + "用系统应用打开"按钮** | 实现简单，零依赖 | 非真正预览 | ⭐⭐⭐ |

**建议：** `release/win7` 分支采用 **方案 C（调用系统默认应用）** 作为 v1，后续按需升级到方案 B。与 OfficeCLI 方案的接口保持一致（同一套 `useOfficePreview` Hook），通过后端能力检测自动降级。

---

## 6. 验收标准

1. 用户点击 `.pptx/.docx/.xlsx` → 应用内预览，无外部软件依赖
2. 缺失 OfficeCLI 时显示清晰引导（自动安装或手动命令）
3. 安装/启动过程中 UI 有状态反馈，不会卡死
4. 关闭预览面板 → 子进程立即终止，无泄漏
5. 路径沙箱校验生效，拒绝工作区外的文件
6. 单元测试覆盖率 ≥ 80%，E2E 测试覆盖核心流程
7. 用户手册与技术文档齐全

---

## 附录 A：AionUi 关键参考文件

| 文件 | 作用 |
|---|---|
| `packages/desktop/src/renderer/pages/conversation/Preview/components/viewers/OfficeWatchViewer.tsx` | 核心 Viewer 组件（移植源） |
| `packages/desktop/src/common/adapter/ipcBridge.ts` L1065-1085 | IPC/HTTP 契约（移植接口） |
| `packages/desktop/src/renderer/utils/previewError.ts` | 错误码分类（移植源） |
| `packages/desktop/src/renderer/hooks/file/useAutoPreviewOfficeFiles.ts` | 工作区文件监听自动预览（可选移植） |
| `packages/desktop/src/renderer/services/i18n/locales/*/preview.json` | 12 语种文案（移植源） |
| `tests/e2e/features/previews/preview-panel.e2e.ts` | E2E 测试参考 |
| `Dockerfile` | Linux `libicu-dev` 安装参考 |

## 附录 B：关键命令速查

```bash
# 手动安装 OfficeCLI（Linux/macOS）
curl -fsSL https://d.officecli.ai/install.sh | bash

# 手动验证
officecli watch /path/to/test.pptx
# 期望：输出 http://127.0.0.1:<port>，浏览器打开可预览

# Sage 后端健康检查
curl http://127.0.0.1:8765/health

# Sage 测试
pytest backend/tests/services/officecli/
npm run test -- src/features/office-preview/
```
