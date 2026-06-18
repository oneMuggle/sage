# Draw.io 图表集成实现计划

> 创建日期：2026-06-18  
> 状态：进行中  
> 复杂度：中-高  
> 预计工期：8-11 天（MVP）

---

## 一、背景与目标

### 1.1 背景

用户希望在 sage 项目（React + Vite + Python FastAPI 桌面 AI 助手）中集成 draw.io 图表功能，使 AI 能够通过对话生成、展示和编辑可视化图表。参考项目 `next-ai-draw-io`（Next.js + AI SDK）提供了成熟的 draw.io 嵌入方案。

### 1.2 核心目标

- 用户在 sage 中通过聊天请求图表，AI 生成 draw.io XML
- 前端实时渲染可交互的 draw.io 图表
- 支持图表的编辑、导出、版本历史

### 1.3 参考项目

`/home/fz/project/next-ai-draw-io` - Next.js + AI SDK 实现的 draw.io AI 图表生成器

---

## 二、涉及的文件与模块

### 2.1 新增文件（FSD 结构）

```
src/
├── widgets/
│   └── diagram/                    # 新增 widget
│       ├── DiagramEditor.tsx       # 包装 react-drawio
│       ├── DiagramToolbar.tsx      # 导出/历史/清除按钮
│       └── index.ts
├── features/
│   └── manage-diagrams/            # 新增 feature
│       ├── DiagramContext.tsx       # 图表状态管理
│       ├── useDiagramTools.ts      # AI 工具调用处理
│       └── xmlUtils.ts             # XML 工具函数
├── pages/
│   └── Diagram.tsx                 # 新增页面
└── app/
    └── App.tsx                     # 添加 /diagrams 路由

backend/
└── tools/
    └── diagram_tool.py             # 新增图表工具
```

### 2.2 修改的现有文件

| 文件 | 修改内容 |
|---|---|
| `src/app/App.tsx` | 添加 `/diagrams` 路由 |
| `src/widgets/layout/Sidebar.tsx` | 添加图表页面导航入口 |
| `backend/tools/__init__.py` | 注册 DiagramTool |
| `backend/core/chat_service.py` | 注入图表系统提示词 |

---

## 三、技术方案

### 3.1 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    Sage 前端 (React)                     │
├─────────────────────────────────────────────────────────┤
│  /diagrams 页面                                          │
│  ┌─────────────────────┬───────────────────────────┐   │
│  │  DiagramEditor      │  ChatPanel                │   │
│  │  (react-drawio)     │  (复用现有 Chat 组件)      │   │
│  │                     │                           │   │
│  │  ← 渲染 XML ────────┤─── AgentEvent.tool_call → │   │
│  └─────────────────────┴───────────────────────────┘   │
│                         ↕ SSE                           │
├─────────────────────────────────────────────────────────┤
│                    Sage 后端 (FastAPI)                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  DiagramTool (display_diagram / edit_diagram)   │   │
│  │  → XML 验证 → 存储 → 透传给前端渲染              │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心技术选型

| 技术 | 用途 | 备注 |
|---|---|---|
| `react-drawio` | 嵌入 draw.io 编辑器 | 核心依赖，封装了 iframe postMessage |
| `@xmldom/xmldom` | XML DOM 操作 | edit_diagram 需要 |
| `react-resizable-panels` | 分栏布局 | 可选，可自实现 |
| React Context | 图表状态管理 | 页面级状态，与全局 store 解耦 |

### 3.3 工具调用处理方案

**方案：前端拦截 AgentEvent.tool_call 事件**

1. 后端 `DiagramTool.execute()` 只做 XML 验证/存储，结果作为 tool result 返回给 LLM
2. 前端监听 `AgentEvent` 流中的 `tool_call` 事件
3. 当 `tool_call.function.name === 'display_diagram'` 时，前端解析 XML 参数并渲染图表
4. 图表渲染本质上是客户端行为，不应由后端执行

### 3.4 系统提示词设计

```python
DIAGRAM_SYSTEM_PROMPT = """
你是专业的图表创建助手，专精 draw.io XML 生成。
当用户请求创建图表时，先用 2-3 句话描述布局计划，
然后使用 display_diagram 工具生成 XML。

工具说明：
- display_diagram(xml): 创建新图表
- edit_diagram(operations): 编辑现有图表元素

布局约束：
- 所有元素保持在单页视口内
- x: 0-800, y: 0-600
- 容器最大宽度 700px，最大高度 550px
"""
```

---

## 四、实施步骤

### 阶段 1：基础设施搭建（3-4 天）

- [ ] 步骤 1.1 — 安装前端依赖
  ```bash
  npm install react-drawio @xmldom/xmldom
  npm install -D @types/xmldom
  ```

- [ ] 步骤 1.2 — 创建 FSD 目录结构
  - `src/widgets/diagram/`
  - `src/features/manage-diagrams/`
  - `src/pages/Diagram.tsx`

- [ ] 步骤 1.3 — 创建 `DiagramEditor` 组件
  - 包装 `react-drawio` 的 `DrawIoEmbed`
  - 处理 onLoad/onExport 事件
  - 支持 dark mode、UI 主题切换

- [ ] 步骤 1.4 — 创建 `DiagramContext`
  - 从参考项目适配核心状态管理
  - `chartXML`, `diagramHistory`, `isDrawioReady`
  - `loadDiagram()`, `handleDiagramExport()`, `clearDiagram()`

- [ ] 步骤 1.5 — 添加路由和页面
  - `App.tsx` 新增 `/diagrams` 路由
  - 侧边栏添加导航入口

- [ ] 步骤 1.6 — 验证基础功能
  - 手动加载 XML 验证渲染
  - 导出功能测试

### 阶段 2：后端工具与 AI 集成（3-4 天）

- [ ] 步骤 2.1 — 创建 `DiagramTool`（后端）
  - `DisplayDiagramTool` - 生成图表
  - `EditDiagramTool` - 编辑图表
  - 在 `register_all_tools()` 中注册

- [ ] 步骤 2.2 — 前端工具调用拦截
  - 创建 `useDiagramTools.ts` hook
  - 监听 `AgentEvent.tool_call` 事件
  - 解析 XML 参数并调用 `diagramContext.loadDiagram()`

- [ ] 步骤 2.3 — 添加图表系统提示词
  - 创建 `backend/core/diagram_prompts.py`
  - 在 `ChatService` 中根据配置注入 prompt

- [ ] 步骤 2.4 — XML 工具函数移植
  - 从参考项目移植核心函数
  - `extractDiagramXML()`, `isRealDiagram()`, `validateAndFixXml()`
  - `wrapWithMxFile()`, `isMxCellXmlComplete()`, `applyDiagramOperations()`

### 阶段 3：UI 完善与集成（2-3 天）

- [ ] 步骤 3.1 — 分栏布局
  - 引入 `react-resizable-panels`
  - draw.io 编辑器 (67%) | 聊天面板 (33%)

- [ ] 步骤 3.2 — 导出功能
  - 支持 `.drawio` / `.svg` / `.png` 格式
  - 复用参考项目 `saveDiagramToFile` 逻辑

- [ ] 步骤 3.3 — 图表历史
  - 保存每次 AI 操作前的快照
  - 支持查看/回退到历史版本

- [ ] 步骤 3.4 — Electron 离线支持（可选）
  - 检测 Electron 环境
  - 使用本地打包的 draw.io 文件

### 阶段 4：增强功能（可选，5-7 天）

- [ ] 步骤 4.1 — `append_diagram` 截断续传
- [ ] 步骤 4.2 — VLM 视觉验证
- [ ] 步骤 4.3 — 云图标库支持 (AWS/Azure/GCP)
- [ ] 步骤 4.4 — 聊天消息内联图表预览

---

## 五、风险评估与依赖

### 5.1 风险评估

| 风险 | 级别 | 影响 | 缓解策略 |
|---|---|---|---|
| **LLM 生成无效 XML** | 🔴 高 | 图表无法渲染或渲染异常 | XML 验证 + 自动修复 + 错误反馈循环 |
| **前端工具调用拦截复杂度** | 🟡 中 | 需要修改现有 AgentEvent 处理流 | 利用已有的 `tool_calls` 事件通道 |
| **draw.io iframe 跨域通信** | 🟡 中 | postMessage API 可能有延迟 | `react-drawio` 已封装，生产验证 |
| **XML 截断（token 限制）** | 🟡 中 | 大型图表生成不完整 | MVP 限制图表复杂度；P2 加 `append_diagram` |
| **Electron 离线模式** | 🟡 中 | 需打包 draw.io 静态文件 | 参考项目的打包脚本 |

### 5.2 依赖项

| 依赖 | 说明 |
|---|---|
| `react-drawio` | 核心嵌入库，无替代品 |
| `@xmldom/xmldom` | XML DOM 操作 |
| `react-resizable-panels` | 分栏布局（可选） |
| 后端 LLM 配置 | 需确认 LLM 支持 tool_calls |
| draw.io CDN 访问 | 在线模式依赖 `embed.diagrams.net` |

---

## 六、关键技术决策

1. **前端嵌入 vs 后端渲染**：选择前端 `react-drawio` 嵌入，因为图表交互必须在浏览器端完成。

2. **工具调用处理位置**：前端拦截 `AgentEvent.tool_call` 事件，在客户端执行图表加载。后端的 `DiagramTool.execute()` 只做 XML 验证/存储。

3. **XML 验证策略**：MVP 使用客户端规则验证；P2 可选加 VLM 视觉验证。

4. **状态管理**：使用 React Context（`DiagramContext`）而非 Zustand，因为图表状态是页面级的。

5. **布局方案**：新增独立 `/diagrams` 页面，降低对现有 chat 页面的影响。

---

## 七、验收标准

### MVP 验收

- [ ] 用户可以通过 `/diagrams` 页面访问图表功能
- [ ] AI 可以通过 `display_diagram` 工具生成图表
- [ ] 图表在 draw.io 编辑器中正确渲染
- [ ] 用户可以手动编辑图表
- [ ] 用户可以导出图表为 `.drawio` / `.svg` / `.png`

### 增强功能验收

- [ ] 用户可以通过 `edit_diagram` 工具编辑现有图表
- [ ] 图表历史可以查看和回退
- [ ] Electron 离线模式下正常工作
- [ ] VLM 视觉验证可以检测图表错误

---

## 八、参考资源

- 参考项目：`/home/fz/project/next-ai-draw-io`
- react-drawio 文档：https://github.com/zhangfishiu/react-drawio
- draw.io 嵌入文档：https://www.drawio.com/doc/embed
