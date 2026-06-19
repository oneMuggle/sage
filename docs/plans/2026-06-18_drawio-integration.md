# Draw.io 图表集成实现计划（v2）

> 创建日期：2026-06-18  
> 更新日期：2026-06-18  
> 状态：✅ 已完成  
> 复杂度：中-高  
> 实际工期：~1 天（集中实现）

---

## 一、背景与目标

### 1.1 背景

用户希望在 sage 项目中集成 draw.io 图表功能。AI 通过 MCP Server 调用 draw.io 生成图表，将预览图（SVG/PNG）直接显示在聊天会话区域。

### 1.2 核心需求

- ✅ 通过 **MCP Server** 调用 draw.io（非嵌入编辑器）
- ✅ 图表预览图**内联显示在聊天消息中**
- ✅ 连接**自托管 Docker draw.io** 实例
- ❌ 不需要嵌入完整 draw.io 编辑器

### 1.3 参考项目

`/home/fz/project/next-ai-draw-io` — 其中的 `packages/mcp-server/` 提供了 MCP Server 实现，但**依赖浏览器窗口**进行渲染（通过 `open()` 打开浏览器，postMessage 与 draw.io iframe 通信）。需要改造为 headless 方案。

---

## 二、技术方案

### 2.1 核心问题

参考项目的 MCP Server 的 XML → SVG/PNG 转换**完全依赖浏览器端的 draw.io iframe**。MCP Server 本身（Node.js 进程）不做任何渲染，它通过以下链路与浏览器通信：

```
MCP Server → HTTP API (localhost:6002) → 浏览器页面 → draw.io iframe → postMessage → 导出图片
```

这意味着需要一个浏览器实例来完成渲染。参考项目直接打开用户浏览器窗口，但对 sage 来说更合适的方案是 **headless 浏览器**（Puppeteer）。

### 2.2 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                      Sage 桌面应用                            │
├──────────────────────────────────────────────────────────────┤
│  前端 (React)                                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  ChatMessage 组件                                       │ │
│  │  - 检测 tool_result 中的 image/svg 类型                 │ │
│  │  - 内联渲染 <img src="data:image/svg+xml;base64,..." /> │ │
│  └────────────────────────────────────────────────────────┘ │
│                          ↕ SSE (AgentEvent)                  │
│  后端 (FastAPI)                                              │
│  ┌────────────────┐    ┌──────────────────────────────────┐ │
│  │  MCP Client    │────│  Agent (ReAct 循环)               │ │
│  │  Manager       │    │  - LLM 调用 diagram 工具          │ │
│  │  - 管理 MCP    │    │  - 工具结果包含 SVG/PNG 数据      │ │
│  │    Server 进程  │    │  - 结果传递给前端渲染              │ │
│  └───────┬────────┘    └──────────────────────────────────┘ │
└──────────┼──────────────────────────────────────────────────┘
           │ stdio (MCP Protocol)
           ▼
┌──────────────────────────────────────┐
│  draw.io MCP Server (Node.js)        │
│  - 自包含，独立进程                    │
│  - Puppeteer headless 浏览器          │
│  - 连接自托管 draw.io Docker 实例     │
│                                      │
│  工具：                               │
│  - render_diagram(xml) → SVG/PNG     │
│  - edit_diagram(xml, ops) → SVG/PNG  │
└──────────┬───────────────────────────┘
           │ HTTP (postMessage)
           ▼
┌──────────────────────────────────────┐
│  自托管 draw.io Docker                │
│  http://localhost:8080                │
│  (jgraph/drawio 镜像)                 │
└──────────────────────────────────────┘
```

### 2.3 两种 MCP Server 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A: Puppeteer Headless（推荐）** | MCP Server 内置 Puppeteer，在 headless 浏览器中加载 draw.io 并导出 | 无 UI 弹窗、自包含、生产可用 | 需安装 Chromium (~170MB)、首次启动慢 |
| **B: 复用参考项目 MCP Server** | 直接使用 `@next-ai-drawio/mcp-server`，打开浏览器窗口 | 零开发、功能完整 | 每次弹出浏览器窗口、用户体验差 |

**推荐方案 A** — 创建轻量 Puppeteer-based MCP Server。

### 2.4 sage 后端 MCP Client 设计

sage 目前没有 MCP 客户端支持。需要新增：

```
backend/
├── mcp/
│   ├── __init__.py
│   ├── client.py          # MCP Client — 管理 MCP Server 进程
│   ├── config.py          # MCP Server 配置（路径、环境变量）
│   └── types.py           # MCP 数据类型定义
├── adapters/out/mcp/
│   └── mcp_tool_adapter.py  # ToolPort 适配器 — 将 MCP 工具暴露为 BaseTool
```

**核心流程：**

1. `McpClient` 启动 MCP Server 子进程（stdio transport）
2. 发现 MCP Server 注册的工具 → 转换为 sage 的 `ToolSpec`
3. 注册到 `ToolRegistry`（或作为独立的 `McpToolAdapter`）
4. Agent 的 ReAct 循环中，LLM 可调用这些 MCP 工具
5. 工具返回的 SVG/PNG 数据通过 `ToolResult.metadata` 传递给前端

### 2.5 前端图片渲染

在 `Message.tsx` 的 tool_call 渲染区域，检测工具结果中的图片数据：

```tsx
// 当 tool_call.result 包含 image/svg 类型时
if (tc.name === 'render_diagram' && tc.result?.metadata?.imageData) {
  const { imageData, format } = tc.result.metadata;
  return <img src={imageData} alt="AI 生成的图表" className="max-w-full rounded border" />;
}
```

---

## 三、实施步骤

### 阶段 1：draw.io Docker 部署与验证（0.5 天）

- [ ] 步骤 1.1 — 部署 draw.io Docker 实例
  ```bash
  docker run -d --name drawio -p 8080:8080 jgraph/drawio
  ```
- [ ] 步骤 1.2 — 验证 embed API
  - 确认 `http://localhost:8080/?embed=1&proto=json` 可访问
  - 测试 postMessage 通信（load / export）

### 阶段 2：创建 draw.io MCP Server（3-4 天）

- [ ] 步骤 2.1 — 创建项目结构
  ```
  packages/drawio-mcp-server/
  ├── package.json
  ├── tsconfig.json
  └── src/
      ├── index.ts              # MCP 入口 (stdio transport)
      ├── renderer.ts           # Puppeteer 渲染器
      ├── drawio-bridge.ts      # draw.io postMessage 通信
      ├── diagram-operations.ts # 图表操作（从参考项目移植）
      └── xml-validation.ts     # XML 验证/修复（从参考项目移植）
  ```

- [ ] 步骤 2.2 — 实现 Puppeteer 渲染器
  ```typescript
  // renderer.ts — 核心
  class DrawioRenderer {
    private browser: puppeteer.Browser;
    private page: puppeteer.Page;

    async init(drawioBaseUrl: string) {
      this.browser = await puppeteer.launch({ headless: true });
      this.page = await this.browser.newPage();
      // 加载 draw.io embed 页面
      await this.page.goto(`${drawioBaseUrl}/?embed=1&proto=json&spin=0`);
      // 等待 draw.io 初始化完成
      await this.waitForInit();
    }

    async renderDiagram(xml: string, format: 'svg' | 'png' = 'svg'): Promise<string> {
      // 1. postMessage({ action: 'load', xml })
      // 2. 等待渲染完成
      // 3. postMessage({ action: 'export', format })
      // 4. 接收导出结果 (data URL)
      // 5. 返回 data URL
    }
  }
  ```

- [ ] 步骤 2.3 — 实现 MCP 工具注册
  ```typescript
  // index.ts
  server.tool('render_diagram', '渲染 draw.io 图表为 SVG 或 PNG', {
    xml: z.string(),
    format: z.enum(['svg', 'png']).optional(),
  }, async ({ xml, format }) => {
    const validatedXml = validateAndFixXml(xml);
    const dataUrl = await renderer.renderDiagram(validatedXml, format ?? 'svg');
    return {
      content: [{ type: 'text', text: '图表已生成' }],
      // 图片数据通过 metadata 或特殊 content type 返回
    };
  });
  ```

- [ ] 步骤 2.4 — 移植 XML 工具函数
  - 从参考项目移植 `validateAndFixXml()`、`isMxCellXmlComplete()` 等
  - 从参考项目移植 `applyDiagramOperations()`（用于 edit_diagram）

- [ ] 步骤 2.5 — 测试 MCP Server
  - 使用 MCP Inspector 测试工具调用
  - 验证 XML → SVG/PNG 转换正确性

### 阶段 3：sage 后端 MCP Client（2-3 天）

- [ ] 步骤 3.1 — 创建 MCP Client 模块
  ```python
  # backend/mcp/client.py
  class McpClient:
      """管理 MCP Server 子进程，通过 stdio 通信"""

      async def start(self, command: str, args: list[str], env: dict):
          """启动 MCP Server 子进程"""

      async def list_tools(self) -> list[McpToolSpec]:
          """发现 MCP Server 注册的工具"""

      async def call_tool(self, name: str, arguments: dict) -> McpToolResult:
          """调用 MCP 工具"""

      async def stop(self):
          """停止 MCP Server 子进程"""
  ```

- [ ] 步骤 3.2 — 创建 MCP 配置
  ```python
  # backend/mcp/config.py
  MCP_SERVERS = {
      "drawio": {
          "command": "node",
          "args": ["packages/drawio-mcp-server/dist/index.js"],
          "env": {
              "DRAWIO_BASE_URL": "http://localhost:8080",
          }
  }
  ```

- [ ] 步骤 3.3 — 创建 MCP ToolPort 适配器
  ```python
  # backend/adapters/out/mcp/mcp_tool_adapter.py
  class McpToolAdapter(ToolPort):
      """将 MCP Server 的工具暴露为 sage 的 ToolPort"""

      def list_tools(self) -> list[ToolSpec]:
          # 从 MCP Client 获取工具列表 → 转换为 ToolSpec

      async def execute(self, name: str, args: dict) -> ToolResult:
          # 调用 MCP Client → 等待结果 → 转换为 ToolResult
          # 图片数据通过 ToolResult.metadata 传递
  ```

- [ ] 步骤 3.4 — 集成到 Agent 循环
  - 在 `register_all_tools()` 中注册 MCP 工具
  - 确保 `ToolResult.metadata` 能携带图片数据
  - 确保 SSE 事件能传递图片数据到前端

### 阶段 4：前端图片内联渲染（1-2 天）

- [ ] 步骤 4.1 — 扩展 ToolCall 类型
  ```typescript
  // shared/lib/store.ts
  interface ToolCall {
    name: string;
    args: Record<string, unknown>;
    result?: string;
    metadata?: {               // 新增
      imageData?: string;      // base64 data URL
      imageFormat?: 'svg' | 'png';
    };
  }
  ```

- [ ] 步骤 4.2 — 修改 Message.tsx 渲染逻辑
  - 检测 `tool_call.metadata.imageData`
  - 渲染 `<img>` 标签内联显示图表
  - 支持点击放大查看

- [ ] 步骤 4.3 — 处理 SSE 事件中的图片数据
  - 确保 `AgentEvent.tool_result` 能传递 metadata
  - 在 `useChat.ts` 中正确解析和存储

### 阶段 5：系统提示词与体验优化（1-2 天）

- [ ] 步骤 5.1 — 添加图表系统提示词
  - 指导 LLM 何时使用 `render_diagram` 工具
  - 提供 draw.io XML 生成的最佳实践

- [ ] 步骤 5.2 — 错误处理
  - draw.io Docker 不可用时的降级提示
  - XML 无效时的自动修复和重试
  - Puppeteer 超时处理

---

## 四、涉及的文件与模块

### 新增文件

| 位置 | 文件 | 描述 |
|------|------|------|
| `packages/drawio-mcp-server/` | 整个目录 | MCP Server（独立 npm 包） |
| `backend/mcp/` | `client.py`, `config.py`, `types.py` | MCP Client 模块 |
| `backend/adapters/out/mcp/` | `mcp_tool_adapter.py` | MCP ToolPort 适配器 |
| `src/widgets/chat/DiagramPreview.tsx` | 新组件 | 图表预览组件（可选） |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/widgets/chat/Message.tsx` | tool_call 图片内联渲染 |
| `src/shared/lib/store.ts` | ToolCall 类型扩展 metadata |
| `src/shared/api/api.ts` | AgentEvent 类型扩展 |
| `src/features/send-message/useChat.ts` | 处理工具结果中的图片数据 |
| `backend/tools/__init__.py` | 注册 MCP 工具 |
| `backend/core/legacy/agent.py` | 传递 metadata |

---

## 五、风险评估

| 风险 | 级别 | 缓解策略 |
|------|------|----------|
| **Puppeteer 安装体积大** (~170MB Chromium) | 🟡 中 | 可使用 `puppeteer-core` + 系统已安装的 Chrome |
| **draw.io Docker 未部署** | 🟢 低 | 提供 Docker Compose 配置 + 部署文档 |
| **headless 渲染超时** | 🟡 中 | 设置超时 + 重试 + 错误反馈 |
| **MCP Client 稳定性** | 🟡 中 | 进程管理 + 自动重启 + 健康检查 |
| **图片数据体积大** | 🟡 中 | SVG 优先（文本格式，可压缩）；PNG 限制分辨率 |
| **SSE 传输图片数据** | 🔴 高 | 考虑替代方案：存储到临时文件，传递文件路径/URL |

### SSE 图片数据传输方案

**方案 A：直接在 SSE 中传 base64**（简单但体积大）
- SVG 文本通常 5-50KB → 可接受
- PNG base64 通常 100KB-1MB → 可能阻塞流

**方案 B：存储到临时文件，传递路径**（推荐）
- 后端收到 SVG/PNG → 写入 `temp/diagrams/{id}.svg`
- SSE 传递文件路径 → 前端通过 HTTP 加载
- 优点：不阻塞 SSE 流，支持大图片

**方案 C：Data URL（MVP 先用这个）**
- SVG 作为 data URL 直接嵌入 tool_result
- MVP 阶段 SVG 体积可控，后续优化为方案 B

---

## 六、依赖项

| 依赖 | 说明 | 状态 |
|------|------|------|
| Docker + `jgraph/drawio` | 自托管 draw.io 实例 | 需用户部署 |
| Node.js + npm | MCP Server 运行时 | ✅ 已有 |
| `puppeteer` | headless 浏览器 | 需安装 |
| `@modelcontextprotocol/sdk` | MCP 官方 SDK | 需安装 |
| `linkedom` | Node.js DOM polyfill | 需安装 |
| `zod` | 工具参数校验 | ✅ 已有（后端） |
| Python `mcp` 库 | sage 的 MCP Client | 需评估/安装 |

---

## 七、验收标准

### MVP 验收

- [ ] draw.io Docker 实例正常运行
- [ ] MCP Server 能启动 Puppeteer 并连接 draw.io
- [ ] `render_diagram(xml)` 工具返回 SVG data URL
- [ ] sage 后端能发现并调用 MCP 工具
- [ ] 聊天消息中内联显示 SVG 图表预览
- [ ] 用户请求"画一个流程图"→ AI 生成 XML → 预览图显示在聊天中

### 增强功能（后续）

- [ ] `edit_diagram` — 编辑现有图表
- [ ] 导出为文件（.drawio / .png / .svg）
- [ ] 图表历史记录
- [ ] 点击图表放大查看

---

## 八、参考资源

- 参考项目 MCP Server：`/home/fz/project/next-ai-draw-io/packages/mcp-server/`
- MCP 协议规范：https://modelcontextprotocol.io
- MCP SDK (TypeScript)：https://github.com/modelcontextprotocol/typescript-sdk
- MCP SDK (Python)：https://github.com/modelcontextprotocol/python-sdk
- draw.io embed 文档：https://www.drawio.com/doc/embed
- Puppeteer 文档：https://pptr.dev
