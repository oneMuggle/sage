# UI 集成方案：CSS 变量驱动的颜色系统

## 日期：2026-05-28

## 背景与目标

将 Open Design 中的 AI 桌面助手 UI 设计方案应用到 Sage 项目。核心要求：
- 所有颜色通过 CSS 变量管理，零硬编码
- Tailwind 配置引用 CSS 变量，支持透明度修饰符
- 组件代码使用语义化 token（`bg-primary`、`text-muted` 等）

## 涉及文件

| 文件 | 操作 |
|------|------|
| `src/index.css` | 扩展 CSS 变量色板 |
| `tailwind.config.js` | 重构颜色配置 |
| `src/components/common/Button.tsx` | 替换硬编码颜色 |
| `src/components/common/Input.tsx` | 替换硬编码颜色 |
| `src/components/common/Modal.tsx` | 替换硬编码颜色 |
| `src/components/layout/Layout.tsx` | 替换硬编码颜色 |
| `src/components/layout/Sidebar.tsx` | 替换硬编码颜色 |
| `src/components/session/SessionList.tsx` | 替换硬编码颜色 |
| `src/components/session/SessionItem.tsx` | 替换硬编码颜色 |
| `src/components/chat/ChatInput.tsx` | 替换硬编码颜色 |
| `src/components/chat/Message.tsx` | 替换硬编码颜色 |
| `src/components/chat/MessageList.tsx` | 替换硬编码颜色 |
| `src/pages/Chat.tsx` | 替换硬编码颜色 |
| `src/pages/Settings.tsx` | 替换硬编码颜色 |
| `src/pages/Agents.tsx` | 替换硬编码颜色 |
| `src/pages/Skills.tsx` | 替换硬编码颜色 |
| `src/components/skills/SkillCard.tsx` | 替换硬编码颜色 |
| `src/components/skills/SkillList.tsx` | 替换硬编码颜色 |
| `src/components/evolution/EvolutionPanel.tsx` | 替换硬编码颜色 |
| `src/components/evolution/EvolutionLog.tsx` | 替换硬编码颜色 |
| `src/components/memory/MemoryItem.tsx` | 替换硬编码颜色 |
| `src/components/memory/MemoryBrowser.tsx` | 替换硬编码颜色 |

## 语义化 Token 对照表

### 背景色
| Token | 用途 |
|-------|------|
| `bg-surface` | 页面主背景 |
| `bg-surface-elevated` | 卡片、弹窗 |
| `bg-surface-overlay` | 浮层、Tooltip |
| `bg-muted` | 侧栏、列表背景 |
| `bg-subtle` | 输入框、标签 |
| `bg-hover` | 悬停态背景 |
| `bg-active` | 激活态背景 |
| `bg-overlay` | 模态遮罩 |

### 文字色
| Token | 用途 |
|-------|------|
| `text-primary` | 主品牌色 |
| `text-text` | 正文默认色 |
| `text-secondary` | 次要文字色 |
| `text-muted` | 弱提示文字色 |
| `text-inverse` | 深色背景上的文字 |
| `text-success` | 成功态文字 |
| `text-error` | 错误态文字 |
| `text-warning` | 警告态文字 |
| `text-info` | 信息态文字 |
| `text-accent` | 强调色文字 |

### 边框色
| Token | 用途 |
|-------|------|
| `border-border` | 默认边框 |
| `border-border-hover` | 悬停态边框 |

### 角色色（Agent 类型标签）
| Token | 用途 |
|-------|------|
| `bg-role-blue` / `text-role-blue` | 协调器 |
| `bg-role-green` / `text-role-green` | 研究员 |
| `bg-role-purple` / `text-role-purple` | 工程师 |
| `bg-role-orange` / `text-role-orange` | 记忆管理 |

## 实施步骤

### Phase 1: CSS 变量体系定义
在 `:root` 和 `[data-theme="dark"]` 中扩展完整的语义化颜色体系，包含 RGB 三通道变量。

### Phase 2: Tailwind 配置重构
使用 `rgb(var(--xxx) / <alpha-value>)` 格式定义所有颜色。

### Phase 3: 组件颜色迁移
按文件分组替换所有硬编码颜色为语义化 token。

### Phase 4: 验证
Grep 扫描 + `npm run build` 验证。

## 实施状态

- [x] Phase 1: CSS 变量体系定义
- [x] Phase 2: Tailwind 配置重构
- [x] Phase 3: 组件颜色迁移
- [x] Phase 4: 验证

## 验证结果

- [x] TypeScript 编译通过 (`npx tsc --noEmit` 无错误)
- [x] 无 `gray-*`、`blue-*`、`red-*` 等硬编码颜色残留
- [x] 无 `text-white`、`bg-white`、`text-black`、`bg-black` 残留
- [x] 所有颜色使用语义化 token

---

# 第二阶段：Open Design Mockup 功能对齐

**日期：** 2026-05-28
**目标：** 将设计稿中的功能完整迁移到 React 项目

## 差距分析

| Mockup 元素 | 当前状态 | 操作 |
|---|---|---|
| Knowledge 页面 | 不存在 | 新建页面 + 3 组件 + 1 hook |
| Markdown 消息渲染 | 纯文本 | 集成 react-markdown |
| 知识引用 Chips | 不存在 | 新建 KnowledgeChip 组件 |
| 文件拖拽上传 | 不存在 | 新建 FileAttachment + hook |
| 消息气泡样式 | 基础实现 | 优化圆角、阴影、对齐 |
| Sidebar 导航 | 无 Knowledge | 添加导航项 |

## 实施步骤

### Phase 5: 基础设施扩展（CSS/Tailwind 增强）

- [x] 扩展 `src/index.css`：添加 `--space-*`、`--radius-*`、`--shadow-*`、`--transition-*` 变量
- [x] 更新 `tailwind.config.js`：引用新增 CSS 变量

### Phase 6: 知识管理模块（新建 5 文件）

- [x] 创建 `src/hooks/useKnowledge.ts`：状态管理 + mock 数据
- [x] 创建 `src/components/knowledge/KnowledgeCard.tsx`：多选卡片
- [x] 创建 `src/components/knowledge/KnowledgeList.tsx`：网格布局
- [x] 创建 `src/components/knowledge/KnowledgeBrowser.tsx`：整合搜索/筛选
- [x] 创建 `src/pages/Knowledge.tsx`：Knowledge 页面
- [x] 更新 `src/App.tsx`：添加 Knowledge 路由
- [x] 更新 `src/components/layout/Sidebar.tsx`：添加 Knowledge 导航

### Phase 7: 对话功能增强（修改 4 + 新建 3 文件）

- [x] 安装 `react-markdown` + `react-syntax-highlighter`
- [x] 增强 `src/components/chat/Message.tsx`：Markdown 渲染
- [x] 创建 `src/components/chat/KnowledgeChip.tsx`
- [x] 创建 `src/components/chat/FileAttachment.tsx`
- [x] 创建 `src/hooks/useFileUpload.ts`
- [x] 增强 `src/components/chat/ChatInput.tsx`：拖拽 + 知识引用
- [x] 更新 `src/pages/Chat.tsx`：状态整合

### Phase 8: 布局视觉对齐

- [x] 更新 `src/components/chat/MessageList.tsx`
- [x] 更新 `src/pages/Memory.tsx`
- [x] 更新 `src/pages/Settings.tsx`

### Phase 9: 验证

- [x] TypeScript 编译
- [x] 构建验证
- [x] 无 console.log 残留（仅 Skills.tsx 已有条目，非本次修改）
- [x] 无硬编码颜色残留

## 风险评估

| 风险 | 级别 | 缓解 |
|---|---|---|
| ChatInput 变更复杂度高 | 高 | 分步实施 |
| react-markdown 兼容性 | 中 | 使用稳定版本 |
| Tauri 拖拽行为差异 | 中 | 实际测试 |
| 知识管理 API 未实现 | 中 | mock 数据先行 |

## 验证结果

- [x] TypeScript 编译通过 (`npx tsc --noEmit` 无错误)
- [x] 构建成功 (`npm run build` 完成)
- [x] 无新增 console.log
- [x] 无新增硬编码颜色
- [x] 新增依赖：react-markdown@^9.0.0, react-syntax-highlighter@^15.5.0

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `src/hooks/useKnowledge.ts` | Knowledge 状态管理 + mock 数据 |
| `src/hooks/useFileUpload.ts` | 文件拖拽上传状态管理 |
| `src/components/knowledge/KnowledgeCard.tsx` | 知识文档卡片 |
| `src/components/knowledge/KnowledgeList.tsx` | 网格布局知识列表 |
| `src/components/knowledge/KnowledgeBrowser.tsx` | 搜索/筛选/列表整合 |
| `src/components/chat/KnowledgeChip.tsx` | 知识引用 chip |
| `src/components/chat/FileAttachment.tsx` | 文件附件显示 |
| `src/pages/Knowledge.tsx` | Knowledge 页面 |

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `src/index.css` | 添加间距、圆角、阴影、过渡 CSS 变量 |
| `tailwind.config.js` | 添加 spacing、borderRadius、boxShadow、transitionDuration token |
| `package.json` | 新增 react-markdown、react-syntax-highlighter 依赖 |
| `src/App.tsx` | 添加 Knowledge 路由 |
| `src/components/layout/Sidebar.tsx` | 添加知识库导航项 |
| `src/components/chat/Message.tsx` | 集成 react-markdown、知识引用、文件附件 |
| `src/components/chat/ChatInput.tsx` | 拖拽上传、知识引用选择器、图片/文件预览 |
| `src/components/chat/MessageList.tsx` | 传递 knowledgeRefs 和 attachments props |
| `src/pages/Chat.tsx` | 整合知识引用和文件附件状态 |
| `src/pages/Memory.tsx` | 布局对齐 mockup |
| `src/pages/Settings.tsx` | 4 标签页重构（通用/模型/记忆/网络） |
