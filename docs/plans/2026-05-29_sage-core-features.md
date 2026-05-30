# Sage 核心功能实现计划

**日期**: 2026-05-29
**状态**: 阶段 1-4 已完成，阶段 5（测试）待实施

## 需求概述

1. **设置页面 - LLM 端点配置持久化** - 模型设置跨会话保存
2. **LLM 连接测试** - "测试连接"按钮验证 API 可达性
3. **基础对话功能** - 使用持久化设置，流式输出，错误处理
4. **会话管理修复** - 新建会话后第一条消息正确关联

## 当前架构问题

| 问题 | 影响 |
|------|------|
| Settings 全用 `useState`，无持久化 | 刷新丢失所有配置 |
| Chat API 硬编码调用 Tauri invoke | 无法动态配置模型参数 |
| 无 settings store / 类型定义 | 各组件无法共享配置 |
| 会话创建有 bug | 第一条消息不进入新会话 |

---

## 阶段 1：设置基础设施（最高优先级）

### Step 1：定义设置类型
**新文件**: `src/types/settings.ts`
- 创建 `AppSettings` 接口（apiUrl, model, maxContext, temperature 等）
- 定义默认值常量
- 添加 version 字段用于未来迁移

### Step 2：创建设置持久化层
**新文件**: `src/lib/settings.ts`
- `loadSettings()` - 从 localStorage 读取，合并默认值
- `saveSettings()` - 合并并持久化
- `resetSettings()` - 恢复默认值
- JSON 解析错误处理 + 版本迁移支持

### Step 3：连接设置页面到 Store
**修改**: `src/pages/Settings.tsx`
- 替换所有 `useState` 为 `useSettings` hook
- 添加"恢复默认"按钮

### Step 4：添加"测试连接"按钮
**修改**: `src/pages/Settings.tsx`
- Model 标签页 API URL 旁添加测试按钮
- 显示加载/成功/失败状态

### Step 5：API 连接测试端点
**修改**: `src/lib/api.ts`
- 新增 `configApi.testConnection()` 方法

### Step 6：Settings Hook
**新文件**: `src/hooks/useSettings.ts`
- 封装持久化层为 React hook
- 提供类型化 getter（getApiUrl, getModel 等）

---

## 阶段 2：对话 + 设置集成（高优先级）

### Step 7：Chat 使用设置
**修改**: `src/lib/api.ts`, `src/hooks/useChat.ts`
- `chatApi.chat()` 接受 config 参数
- `useChat` 读取设置并传递配置
- apiUrl 未配置时显示友好错误

### Step 8：流式输出支持
**修改**: `useChat.ts`, `api.ts`, `Message.tsx`
- `chatApi.streamChat()` 使用 Tauri 事件监听
- 流式消息追加 + 完成标记
- 根据设置.toggle 控制流式/非流式

### Step 9：错误处理 UX
**修改**: `useChat.ts`, `Chat.tsx`
- 替换 `console.error` 为错误状态
- 区分"未配置"/"连接失败"/"API 错误"
- 失败消息添加重试按钮

---

## 阶段 3：会话修复（中优先级）

### Step 10：修复会话创建 Bug
**修改**: `Chat.tsx`, `useChat.ts`
- 当前 bug：创建会话后仍用 null sessionId 发消息
- 修复：await createSession → 设置 ID → 再 sendMessage

### Step 11：持久化当前会话 ID
**修改**: `src/lib/store.ts`
- localStorage 保存/恢复 currentSessionId

### Step 12：侧边栏连接状态
**修改**: `Sidebar.tsx`
- 替换硬编码"已连接"为动态状态
- 启动时自动测试连接

---

## 阶段 4：其他页面后端集成（较低优先级）

Step 13-16：Memory / Knowledge / Agents / Skills 页面接入真实后端（依赖 Rust Tauri 命令实现）

---

## 阶段 5：完善与测试

### Step 17：设置验证
- API URL 格式验证
- maxContext 范围验证
- temperature 0-2 范围验证

### Step 18：单元测试
- settings 加载/保存/合并
- API 错误处理/重试逻辑
- useChat 发送/接收流程

---

## 实施步骤

- [x] 步骤 1：写入计划文档
- [x] 步骤 2：定义设置类型 (src/types/settings.ts)
- [x] 步骤 3：创建设置持久化层 (src/lib/settings.ts)
- [x] 步骤 4：创建 Settings Hook (src/hooks/useSettings.ts)
- [x] 步骤 5：连接设置页面到 Store
- [x] 步骤 6：添加"测试连接"按钮
- [x] 步骤 7：API 连接测试端点
- [x] 步骤 8：Chat 使用设置
- [x] 步骤 9：错误处理 UX
- [x] 步骤 10：修复会话创建 Bug
- [x] 步骤 11：持久化当前会话 ID
- [x] 步骤 12：侧边栏连接状态
- [x] 步骤 13：Memory 错误处理改善
- [x] 步骤 14：Knowledge 真实 API 集成
- [x] 步骤 15：Skills 真实 API 集成
- [x] 步骤 16：Agents 真实 API 集成

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| Tauri 后端命令未实现 | 高 | 前端先用 mock/stub，连接测试优雅降级 |
| 流式输出需要 Rust 事件循环 | 高 | 先实现非流式备选，流式通过设置开关 |
| localStorage 在 Tauri 不可用 | 中 | try-catch 包裹，降级为内存存储 |
