# 172 · 自部署服务通用化框架（P0：DrawIO 激活）

> 本文档分三期落地：P0 先激活 DrawIO（本期），P1 统一富媒体契约，P2 声明式服务注册。
> 计划文档：`docs/plans/2026-11-25-selfhosted-service-framework.md`。

## 背景

Sage 后续要接入多种自部署服务（MinerU 文档解析、DrawIO 图表渲染、Zotero 文献库等）。
若每个服务都按现有 MinerU 范式手写 domain/adapter/settings/route 一套，会产生大量同质样板。
通用化目标是让"新增一个自部署服务"变成：

1. 一份 MCP server 或 Python adapter 实现；
2. 一个声明式 spec（P2 阶段）；
3. 一个客户端薄层（P2 阶段）。

P0 的目标收敛为一条：让 DrawIO 图表渲染能在会话中真正显示出来。

## 架构分层

```
┌─ 前端 Message.tsx ── toolRenderers + mediaRef 渲染 ─┐
│  P1 完成：richMedia 渲染器 + 历史回读 + 代码块注册表 │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 后端 backend/mcp ── McpTool / pool ────────────────┐
│  P1 完成：图片结果落 MediaStore，返回 RichMedia 引用  │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 服务声明 backend/services/external_services ───────┐
│  P2 完成：Spec + Registry + SecretBox + 状态路由     │
│  内置声明：MinerU / DrawIO / Zotero                  │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 服务本体 ──────────────────────────────────────────┐
│  packages/drawio-mcp-server（Node + Puppeteer）       │
│  backend/services/mineru_adapter（Python）            │
│  backend/mcp/servers/zotero（Python）                 │
└───────────────────────────────────────────────────────┘
```

## P0 · DrawIO 激活

### 服务链路

```
用户请求 "画一个流程图"
    │
    ▼
LLM 调用工具 mcp__drawio__render_diagram(xml=...)
    │
    ▼
McpTool.execute → backend.mcp.pool → 子进程 node dist/index.js
    │
    ▼
packages/drawio-mcp-server/renderer.ts
    ├─ 读取 env: DRAWIO_BASE_URL (默认 http://localhost:8080)
    ├─ 读取 env: CHROME_PATH / PUPPETEER_EXECUTABLE_PATH
    ├─ 启动 Puppeteer (headless) 加载 embed 页面
    └─ 通过 postMessage 协议调用 draw.io 渲染 mxGraphModel → SVG/PNG data URL
    │
    ▼
MCP 响应 [{type: text, ...}, {type: image, data: base64, mimeType}]
    │
    ▼
P1 阶段：落 MediaStore + 返回 RichMedia 引用，前端渲染交互 SVG。
P0 基线：透传 base64，前端渲染 <img>（现有 imageData 通路）。
```

### 部署方式

开发 / CI：

```bash
# 方式 A：本地 docker
docker run -d --name sage-drawio -p 8080:8080 jgraph/drawio

# 方式 B：公网 embed 服务
export DRAWIO_BASE_URL=https://embed.diagrams.net
```

系统 Chrome（Linux 示例）：

```bash
export CHROME_PATH=/opt/google/chrome/chrome
```

Windows / macOS 可设置 `CHROME_PATH` 为 `chrome.exe` / `Google Chrome` 二进制路径；
`PUPPETEER_EXECUTABLE_PATH` 同名等价。

### 验证

**MCP 协议层（Node → 子进程）：**

```bash
cd packages/drawio-mcp-server
export CHROME_PATH=/opt/google/chrome/chrome
export DRAWIO_BASE_URL=http://127.0.0.1:8080
# 通过 @modelcontextprotocol/sdk 客户端直连，工具名 render_diagram，参数 xml
```

**后端 MCP 池（Python → 子进程）：**

```python
from backend.mcp.config import builtin_server_configs
from backend.mcp.pool import McpServerPool

cfg = [c for c in builtin_server_configs() if c.name == 'drawio'][0]
pool = McpServerPool()
pool.sync_configs([cfg])
pool.discover_all()
res = pool.call_tool('drawio', 'render_diagram', {'xml': '<mxGraphModel>...</mxGraphModel>'})
# res['content'] 包含 [{type:'text',...}, {type:'image', data:..., mimeType:'image/svg+xml'}]
```

**桌面端 E2E：**

```bash
npm run dev
SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python \
  ./node_modules/.bin/electron --no-sandbox .
```

会话中发「画一个三节点流程图」，确认气泡内出现图像。

### 打包状态（已知缺口）

当前构建钩子 `build:drawio-mcp` 已挂到 `electron:build`（`scripts/build-drawio-mcp.mjs`），
`PUPPETEER_SKIP_DOWNLOAD=1` 跳过 Chromium 下载以避免 CI 与打包期 ~150 MB 下载。

**打包态缺口（P0 不解决，留给后续迭代）：**

- `electron-builder.yml` 的 `files` 未包含 `packages/drawio-mcp-server`，因此安装包内
  `packages/.../dist/index.js` 不存在，`builtin_server_configs()` 识别不到 drawio；
- 即便把 dist + node_modules 打进 `extraResources`，打包态没有独立的 `node` 可执行文件
  供后端 spawn —— 需要绑定 Electron 自身的 node 运行时（`ELECTRON_RUN_AS_NODE=1` 注入
  子进程）或捆绑独立 node runtime。

上述两项留作后续迭代（P3 或独立功能），P0 仅在开发模式自部署环境生效。PR 描述明确标注。

## 后续路线

- **P1（统一富媒体契约）**：`backend/domain/media.py` RichMedia + 信封；McpTool 把
  图片结果落 MediaStore，返回 `api_url` 引用；前端 SvgDiagramViewer + 代码块注册表。
- **P2（声明式服务注册）**：`ExternalServiceSpec` + Registry + SecretBox 字段加密 +
  settings_repo 通用加载 + 状态路由 + 前端声明式服务卡片；MinerU 现有硬编码迁移。

## 风险

| 风险 | 缓解 |
|---|---|
| Puppeteer Chromium 下载拖慢 CI | `scripts/build-drawio-mcp.mjs` 强制 `PUPPETEER_SKIP_DOWNLOAD=1` |
| 用户环境无 Chrome / Edge | drawio 注册保持"启用"但运行时报错；后续可考虑内置 Chromium |
| embed.diagrams.net 在部分网络环境不可达 | 推荐自部署 docker `jgraph/drawio` |
| 打包态 drawio 未启用 | 已知缺口，PR 描述显式标注；P3 迭代补 |
