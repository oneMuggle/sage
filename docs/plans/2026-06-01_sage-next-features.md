# 2026-06-01_sage-next-features

## 背景

Sage 基础对话链路已修复完成（API Key 传输、消息持久化、CI 通过）。但应用中仍有大量"半成品"功能影响用户体验。

**目标**：按优先级逐步完善，让应用真正可用。

## 阶段一：快速修复（低 effort，高可见度）

### 1. 消息代码高亮
- **文件**: `src/components/chat/Message.tsx`
- **变更**: 配置 `react-markdown` 的 `components` prop，使用已安装的 `react-syntax-highlighter` 渲染代码块
- **新增依赖**: `remark-gfm` (GitHub Flavored Markdown)
- **效果**: 代码块带语法高亮 + 复制按钮

### 2. 侧边栏会话管理
- **文件**: `src/components/layout/Sidebar.tsx`
- **变更**: 使用已有的 `SessionList`/`SessionItem` 组件替换内联渲染，添加删除功能，移除 5 条限制
- **效果**: 侧边栏可删除会话，显示更多元信息

### 3. Settings 连接测试增强
- **文件**: `src/lib/models.ts`, `src/pages/Settings.tsx`
- **变更**: 测试连接不仅调 `/models`，也发一个最小 chat completion 请求验证 API 可用
- **效果**: 更可靠的连接测试

### 4. Memory 页面修复
- **文件**: `src/pages/Memory.tsx`, `src/components/memory/MemoryBrowser.tsx`
- **变更**: 
  - "新建记忆"按钮实现弹窗保存记忆
  - "导出"按钮导出 JSON
  - Stats 从后端真实获取
  - 标签映射对齐后端类型

## 阶段二：错误处理与稳定性

### 5. Python 后端不可用时的 UI
- **文件**: `src-tauri/src/python.rs`, `src/App.tsx`
- **变更**: 
  - Tauri 启动失败时设置全局状态
  - 前端检测到后端不可达时显示友好页面而非红屏报错
  - 添加"重试连接"按钮

### 6. LLM 错误友好提示
- **文件**: `backend/core/agent.py`, `src/hooks/useChat.ts`, `src/components/chat/Message.tsx`
- **变更**:
  - 修复 `agent.py` except 块中 `assistant_message` 未定义的 bug
  - 区分 401(API Key 错误)、429(限流)、500(服务端错误)
  - 前端错误消息中文化

## 阶段三：工具系统（核心 AI 能力）

### 7. 工具 schema 发送到 LLM
- **文件**: `backend/core/agent.py`, `backend/core/llm_client.py`
- **变更**: `_call_llm()` 发送 `tools` 参数（OpenAI tool calling 格式）

### 8. ReAct 循环实现
- **文件**: `backend/core/agent.py`
- **变更**: 
  - `run_loop()` 实现 ReAct 循环
  - 解析 LLM 的 tool_calls 响应
  - 调用 `execute_tool()` 执行工具
  - 将工具结果反馈给 LLM
  - 循环直到无更多工具调用

### 9. 工具执行结果 UI 展示
- **文件**: `src/components/chat/Message.tsx`
- **变更**: 消息中显示工具调用过程（正在执行工具... → 工具结果）

## 实施步骤

- [ ] 步骤 1：安装 remark-gfm 依赖
- [ ] 步骤 2：Message.tsx 代码高亮 + 复制按钮
- [ ] 步骤 3：Sidebar.tsx 集成 SessionList/SessionItem
- [ ] 步骤 4：Settings 连接测试增强（chat completion 验证）
- [ ] 步骤 5：Memory 页面假按钮修复 + 真实 Stats
- [ ] 步骤 6：Tauri 后端启动失败 UI 处理
- [ ] 步骤 7：LLM 错误分类与友好提示
- [ ] 步骤 8：修复 agent.py except 块 bug
- [ ] 步骤 9：工具 schema 发送到 LLM
- [ ] 步骤 10：ReAct 循环实现
- [ ] 步骤 11：工具执行结果 UI 展示
- [ ] 步骤 12：推送 GitHub，追踪 CI，修复问题

## 风险评估

- **低**：阶段一改动小，风险低
- **中**：阶段二涉及错误路径，需要充分测试
- **高**：阶段三工具系统需要正确实现 ReAct 循环，是核心功能
