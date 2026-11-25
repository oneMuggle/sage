# 173 · 自部署服务通用化框架（P0–P2）

> 三期均已落地：P0 激活 DrawIO 渲染，P1 统一富媒体契约，P2 声明式服务注册。
> 计划文档：`docs/plans/2026-11-25-selfhosted-service-framework.md`。

## 背景

Sage 后续要接入多种自部署服务（MinerU 文档解析、DrawIO 图表渲染、Zotero 文献库等）。
若每个服务都按旧 MinerU 范式手写 domain/adapter/settings/route 一套，会产生大量同质样板。
通用化目标是让"新增一个自部署服务"变成：

1. 一份 MCP server 或 Python adapter 实现；
2. 一个声明式 spec（`backend/services/external_services/builtin.py`）；
3. 一个前端 spec（`src/features/settings/externalServices/registry.ts`）。

## 架构分层

```
┌─ 前端 Message.tsx ── toolRenderers + mediaRef 渲染 ─┐
│  P1：richMedia 渲染器 + 历史回读 + 代码块注册表      │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 后端 backend/mcp ── McpTool / pool ────────────────┐
│  P1：图片结果落 MediaStore，返回 RichMedia 引用      │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 服务声明 backend/services/external_services ───────┐
│  P2：Spec + Registry + SecretBox + 状态路由          │
│  内置声明：MinerU（DrawIO / Zotero 仍走 MCP 通道）    │
└───────────────────────────────────────────────────────┘
                      ▲
┌─ 服务本体 ──────────────────────────────────────────┐
│  packages/drawio-mcp-server（Node + Puppeteer）       │
│  backend/services/document_parse（MinerU adapter）    │
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
P1 起：McpTool 把图片落 MediaStore，前端只消费 /api/v1/media/<id> 引用
（SVG 图表走交互查看器；历史消息回读走同一通道路径）
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
# 持久化后模型侧看到 text，UI 侧从 metadata.mediaRefs 拿到 /api/v1/media/<id>
```

**桌面端 E2E：**

```bash
npm run dev
SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python \
  ./node_modules/.bin/electron --no-sandbox .
```

会话中发「画一个三节点流程图」，确认气泡内出现可交互图表。

### 打包状态（已知缺口）

当前构建钩子 `build:drawio-mcp` 已挂到 `electron:build`（`scripts/build-drawio-mcp.mjs`），
`PUPPETEER_SKIP_DOWNLOAD=1` 跳过 Chromium 下载以避免 CI 与打包期 ~150 MB 下载。

**打包态缺口（P0 不解决，留给后续迭代）：**

- `electron-builder.yml` 的 `files` 未包含 `packages/drawio-mcp-server`，因此安装包内
  `packages/.../dist/index.js` 不存在，`builtin_server_configs()` 识别不到 drawio；
- 即便把 dist + node_modules 打进 `extraResources`，打包态没有独立的 `node` 可执行文件
  供后端 spawn —— 需要绑定 Electron 自身的 node 运行时（`ELECTRON_RUN_AS_NODE=1` 注入
  子进程）或捆绑独立 node runtime。

上述两项留作后续迭代（P3 或独立功能），当前仅在开发模式自部署环境生效。PR 描述明确标注。

## P1 · 统一富媒体契约

### 契约（`backend/domain/media.py`）

工具产出的图片 / 图表 / 音频 / 文档不再内联 base64，统一改为 URL 引用：

| 字段 | 说明 |
|------|------|
| `id` | MediaStore 主键 |
| `kind` | `image` / `diagram` / `audio` / `document` |
| `mime_type` | 原始 MIME |
| `api_url` | 唯一载荷来源：`/api/v1/media/<id>`（`backend/api/media_routes.py` 提供） |
| `format` / `title` / `source` | 可选元数据 |
| `interactive` | 提示渲染器可提供缩放/全屏（SVG 图表典型场景） |

`media_envelope(text, media, extra_metadata)` 组装工具结果：`text` 给模型看，
`metadata.mediaRefs` / `metadata.richMedia` 给 UI 看。`McpTool`（`backend/mcp/tool.py`）
自动把 MCP image 结果落 MediaStore 并改写为引用。

### 前端消费

- `src/shared/lib/richMedia.ts`：`RichMediaRef`（字段与后端 `to_dict()` 一一对应）、
  `isInteractiveDiagram(media)`（`interactive && mime_type === 'image/svg+xml'`）。
- `src/shared/api/mediaApi.ts`：`resolveMediaUrl` / `fetchMediaBlobUrl`（带授权头拉取 blob）。
- `src/widgets/chat/SvgDiagramViewer.tsx`：拖拽平移、Ctrl+滚轮缩放、双击复位、
  适应屏幕 / 实际大小、下载 PNG/SVG、全屏；对象是 `<img>`，不注入 HTML。
- `Message.tsx` 工具卡片：优先渲染 `mediaRefs`；历史回读时从持久化 metadata 恢复
  （`49828abd7`），因此刷新会话后图表仍在。
- `src/widgets/markdown/codeFenceRegistry.ts`：围栏代码块语言分发注册表
  （`mermaid` / `html` 富渲染，其余交给 Shiki；忽略大小写与首尾空白）。

检查口径：会话数据库与工具结果中不应再出现 `data:image/...;base64`，
只应有 `/api/v1/media/` 引用。

## P2 · 声明式服务注册

### 后端 spec（`backend/services/external_services/`）

`ExternalServiceSpec`（`spec.py`，纯数据、无 I/O）：

```python
ExternalServiceSpec(
    name="mineru",
    preference_key="mineru_service",
    title="MinerU 文档解析",
    api_prefix="mineru",                 # 状态路由 /api/v1/<prefix>/status
    defaults={...},                      # 缺省值
    aliases={"baseUrl": ["base_url"], ...},  # 规范键 ← 历史键回退
    env_bindings=[EnvBinding("baseUrl", "SAGE_MINERU_BASE_URL"), ...],
    secret_fields=[SecretField("apiKey", "mineru:api_key")],
    probe=_probe_mineru,                 # async (values) -> status dict
)
```

- `registry.py`：`register_service` / `get_service(name)` / `get_by_preference_key(key)` /
  `all_services()`；内置声明在 `builtin.py` 顶层注册（惰性导入避免循环依赖）。
- `settings.py`：三层合并 `defaults ← preferences（已解密，含别名回退）← 非空 env`；
  `load_service_settings(spec)` 为唯一读取入口。
- `SecretBox`（`backend/services/secret_box.py`）：按 `secret_fields` 对 JSON blob 的叶子值
  静态加密，密文格式 `enc:<scheme>:v1:<payload>`；账户名如 `mineru:api_key`。
  `SettingsRepository.get/set` 按 `get_by_preference_key` 分发，不再硬编码服务名。
  测试可用 `SAGE_SECRET_SCHEME=test` 强制 base64 对称实现。
- 状态路由（`backend/api/external_service_routes.py`）：
  `build_external_service_router(spec)` 装配 `GET /api/v1/<prefix>/status`；
  响应只含 `configured/enabled/hasApiKey/reachable/error/reason` + 探活返回的附加字段，
  **绝不回显密钥**；未配置时短路不探活；探活异常转成可读 `error` 而非 500。

### 前端 spec（`src/features/settings/externalServices/`）

```ts
interface ExternalServiceUiSpec {
  key: PreferenceKey;          // preferences 键
  title: string; description: string;
  fields: { jsonKey; label; type: 'text'|'password'|'number'|'boolean'; placeholder? }[];
  defaults: Record<string, string | number | boolean>;
  statusEndpoint: string;      // 缺省状态来源
  testId?: string;
  fetchStatus?(): Promise<ExternalServiceStatus> | ExternalServiceStatus; // 复用既有 API 客户端
  renderStatus?(status, config): ReactNode;                              // 服务专属状态区
}
```

`ExternalServiceCard({ spec })` 负责：并行拉取状态 + preferences、按字段渲染表单
（密码脱敏、布尔成组、数字约束）、保存 JSON blob、保存后刷新状态。
`MineruServiceCard` 现在只是一层薄包装：提供 MinerU 的 spec、`mineruApi.status` 与
自定义状态区（auth mode / 需 API Key 告警）。

### 新增一个自部署服务（照抄清单）

1. **后端**：实现协议客户端 / MCP server；
2. `builtin.py` 追加 `ExternalServiceSpec`（defaults、aliases、env_bindings、secret_fields、probe）；
3. `backend/main.py` 装配 `build_external_service_router(get_service("<name>"))`；
4. **前端**：在 `settingsClient.ts` 的 `PreferenceKey` 增加 preferences 键；
5. 写一张 spec + `<ExternalServiceCard spec={spec} />` 包装组件并挂到设置页。

### 当前注册范围

- **MinerU**：已注册（P2 首个迁移对象；settings 读取、密钥加密、状态路由、前端卡片全部
  由 spec 驱动）。
- **DrawIO**：走 MCP 通道 + `DRAWIO_BASE_URL` 环境变量，无 preferences 配置项，暂不注册
  spec —— 当需要界面配置或状态端点时按上面清单登记即可。
- **Zotero**：走 MCP 通道，同理。

## 打包态与未覆盖项

| 项 | 状态 |
|---|---|
| DrawIO 打包进安装包 | 未解决（见 P0「打包状态」），开发模式可用 |
| B7 真机 E2E（draw.io 实例 + 桌面端交互、会话切换、DB 无 base64） | 待人工验证 |
| `release/win7` 同步 | 待 cherry-pick + py3.8 适配验证 |

## 风险

| 风险 | 缓解 |
|---|---|
| Puppeteer Chromium 下载拖慢 CI | `scripts/build-drawio-mcp.mjs` 强制 `PUPPETEER_SKIP_DOWNLOAD=1` |
| 用户环境无 Chrome / Edge | drawio 注册保持"启用"但运行时报错；后续可考虑内置 Chromium |
| embed.diagrams.net 在部分网络环境不可达 | 推荐自部署 docker `jgraph/drawio` |
| 打包态 drawio 未启用 | 已知缺口，PR 描述显式标注；P3 迭代补 |
| 服务密钥落库明文 | SecretBox 字段加密（平台不可用时诚实降级 + doctor 告警） |
