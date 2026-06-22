/**
 * Sage API - 类型定义
 */

import type { LLMErrorResponse } from '../lib/errorMapping';

// ==================== Session & Message 类型 ====================

export interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  last_message_at: number | null;
  message_count: number;
  is_pinned: boolean;
  metadata?: Record<string, unknown>;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  created_at: number;
  model?: string;
  provider?: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
}

export interface ChatResponse {
  message: Message;
  session?: Session;
}

// ==================== Agent 流式事件 (PR-6) ====================

/** Agent 状态机 — 与后端 backend.core.legacy.agent_state.AgentState 一致 */
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'reasoning' // 携带 LLM 思考/推理过程内容（兼容旧事件）
  | 'reasoning_delta' // 流式 reasoning 分块（fake streaming）
  | 'reasoning_done' // reasoning 完成标记
  | 'acting'
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed';

/** 流式聊天工具调用 (对应 OpenAI 工具调用格式) */
export interface AgentToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    /** 字符串化的JSON 参数 */
    arguments: string;
  };
}

/** 流式聊天工具结果 */
export interface AgentToolResult {
  tool_call_id: string;
  role: 'tool';
  content: string;
}

/** 流式聊天事件 (NDJSON 协议的一行) */
export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  reasoning?: string; // LLM 思考/推理过程内容
  tool_call?: AgentToolCall;
  tool_result?: AgentToolResult;
  error?: string;
}

// ==================== 错误类型定义 ====================

export interface ApiError {
  error: string;
  message: string;
  details?: Record<string, unknown>;
  llmError?: LLMErrorResponse;
}

// ==================== Chat 配置 ====================

export interface ChatConfig {
  apiKey?: string;
  apiUrl?: string;
  model?: string;
  maxContext?: number;
  temperature?: number;
  // 推理参数（PR-7a 透传到后端 → LLMConfig → 请求体）
  // - provider: 前端在 settings 选的真实 provider,后端用它路由
  //   (openai / claude / gemini / deepseek / ollama / custom)
  // - reasoningEffort: OpenAI o1/o3/5 + DeepSeek OpenAI 兼容代理
  // - thinkingBudget: Gemini 2.5 OpenAI 兼容模式
  provider?: string;
  reasoningEffort?: 'low' | 'medium' | 'high';
  thinkingBudget?: number;
}

// ==================== Memory 类型定义 ====================

export interface Memory {
  id: string;
  content: string;
  summary?: string;
  memory_type?: 'episodic' | 'semantic' | 'working';
  session_id?: string;
  importance: number;
  tags: string[];
  created_at: number;
  accessed_at?: number;
  access_count: number;
}

// ==================== Knowledge 类型定义 ====================

export interface KnowledgeDoc {
  id: string;
  title: string;
  description: string;
  pages: number;
  updated_at: string;
  category: string;
  tags?: string[];
}

// ==================== Skills 类型定义 (PR-7) ====================

/**
 * SKILL.md v2 DispatchMode 元数据 (M9) — 嵌套对象, 与后端
 * backend/skills/skill_md/skill.py::DispatchMode 字段一一对应。
 *
 * - disable_model_invocation: true → chat 层阻止自动触发
 * - user_invocable: true → 用户可通过 slash command 主动调用
 * - user_invocable_name: slash command 名 (如 "/review");为 null 时回退到 name
 * - command_dispatch: 'auto' (默认, LLM 决定) / 'tool' (强制工具调用) / 'prompt' (注入 prompt)
 *
 * builtin 技能没有 dispatch key (后端 list_skills_extended 对 builtin 省略)。
 */
export interface SkillDispatch {
  disable_model_invocation: boolean;
  user_invocable: boolean;
  user_invocable_name: string | null;
  command_dispatch: 'auto' | 'tool' | 'prompt';
}

export interface Skill {
  name: string;
  description: string;
  triggers: string[];
  parameters: Record<string, unknown>;
  examples: string[];
  enabled: boolean;
  usage_count: number;
  // SKILL.md 适配层 (PR-8) 新增字段 — builtin 时不存在
  source?: 'builtin' | 'skillmd';
  body?: string;
  scripts?: string[];
  base_dir?: string;
  version?: string;
  // SKILL.md v2 DispatchMode (M9) — builtin 时不存在
  dispatch?: SkillDispatch;
}

export interface SkillExecuteRequest {
  action?: string;
  args?: Record<string, unknown>;
}

export interface SkillExecuteResult {
  success: boolean;
  content?: unknown;
  metadata: Record<string, unknown>;
  error?: string;
}

// ==================== Agents 类型定义 ====================

export interface AgentProfile {
  id: string;
  name: string;
  role: string;
  description: string;
  system_prompt: string;
  tools: string[];
  memory_access: string[];
  model_config: {
    model: string;
    temperature: number;
    max_tokens: number;
  };
  max_iterations: number;
  enabled: boolean;
  /** 后端 PR-3 起返回; PR-4 PATCH 后被刷新 */
  updated_at?: number;
}

/**
 * PR-4 `update_agent` 命令的部分更新 payload。
 *
 * 字段全为可选 — 仅传需要修改的字段, 缺省字段保留原值 (PATCH 语义)。
 * 形状匹配 Tauri `AgentUpdateRequest` (src-tauri/src/models.rs:134),
 * 后端再映射到 Pydantic `AgentUpdate` 做白名单/范围校验。
 *
 * 注: 仅暴露 9 个允许字段，不含 `id` (id 不可变, 见 agent_repo.py 注释)
 * 与 `updated_at` (DB 自动维护)。
 */
export interface AgentUpdate {
  name?: string;
  role?: string;
  system_prompt?: string;
  tools?: string[];
  memory_access?: string[];
  model_config?: AgentProfile['model_config'];
  max_iterations?: number;
  enabled?: boolean;
  description?: string;
}
