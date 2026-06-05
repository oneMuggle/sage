# 2026-06-01_sage-core-llm-conversation-foundation

## 背景与目标

Sage 已具备完整架构（React + Tauri + Python FastAPI），前端构建和 CI 均通过。但存在关键缺陷：**LLM API Key 未从前端传递到 Python 后端**，导致实际对话无法工作。

**目标**：

1. 修复完整对话链路，用户配置 LLM 端点后能正常对话
2. 实现消息持久化，刷新页面后能加载历史消息
3. 修复 CI/CD 过时版本警告
4. 清理文档，确保 README 与实际架构一致

## 涉及文件与模块

| 层级         | 文件                           | 变更类型                                             |
| ------------ | ------------------------------ | ---------------------------------------------------- |
| 前端 API     | `src/lib/api.ts`               | 新增 `apiKey` 字段                                   |
| Rust/Tauri   | `src-tauri/src/models.rs`      | 新增 `api_key` 字段                                  |
| Rust/Tauri   | `src-tauri/src/commands.rs`    | 新增 `api_key` 参数                                  |
| Python API   | `backend/api/routes.py`        | 扩展 ChatRequest + 实现 get_messages + 透传 LLM 配置 |
| Python Core  | `backend/core/agent.py`        | chat() 接受动态 LLM 配置                             |
| Python Data  | `backend/data/session_repo.py` | 新增 MessageRepository                               |
| Python Entry | `backend/main.py`              | 端口从环境变量读取                                   |
| CI/CD        | `.github/workflows/ci.yml`     | Node 20, Python 3.11, 修复 py_compile                |
| 文档         | `README.md`                    | 修正过时内容                                         |

## 技术方案

### 数据流修复

```
Settings (localStorage) → useChat hook → chatApi.chat(apiKey, apiUrl, model)
  → Tauri invoke('agent_chat', { apiKey, apiUrl, model, ... })
  → Rust commands.rs → POST /chat (含 api_key)
  → Python routes.py → SageAgent(api_key, base_url, model).chat()
  → LLMClient(api_key, base_url).chat() → 真实 LLM 响应
```

### 消息持久化

在 `agent.chat()` 中，将用户消息和助手回复写入 `messages` 表。新增 `MessageRepository` 提供 CRUD 操作。

## 实施步骤

- [x] 步骤 1：扩展 Python ChatRequest 模型（api_key, api_url, model, temperature）
- [x] 步骤 2：Python chat() 端点透传 LLM 配置到 SageAgent
- [x] 步骤 3：前端 ChatConfig 增加 apiKey 并透传
- [x] 步骤 4：Rust ChatRequest 增加 api_key 字段
- [x] 步骤 5：Rust agent_chat 命令增加 api_key 参数
- [x] 步骤 6：SageAgent.chat() 接受动态 LLM 配置
- [x] 步骤 7：实现 get_messages 端点
- [x] 步骤 8：新增 MessageRepository 类
- [x] 步骤 9：Agent 对话消息写入数据库
- [x] 步骤 10：CI Node.js 升级到 20
- [x] 步骤 11：CI Python 升级到 3.11
- [x] 步骤 12：修复 CI py_compile 命令
- [x] 步骤 13：更新 README.md（暂缓，不影响功能）
- [x] 步骤 14：Python 端口从环境变量读取
- [x] 步骤 15：推送 GitHub，追踪 CI，修复暴露问题

## 风险评估

- **高**：API Key 传输链断裂 → 第一阶段修复
- **中**：Python 后端 Tauri 生产模式路径 → 先保证开发模式
- **低**：CI 版本升级 → 依赖兼容性良好
