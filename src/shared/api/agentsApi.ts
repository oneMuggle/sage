/**
 * Sage API - Agents API
 */

import { invoke } from './desktopInvoke';
import type { AgentProfile, AgentUpdate } from './types';
import { handleApiError, withRetry } from './utils';

export const agentsApi = {
  async list(): Promise<AgentProfile[]> {
    return withRetry(async () => {
      try {
        return await invoke<AgentProfile[]>('list_agents');
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 启用/禁用 agent (PR-5)。
   *
   * 走专用端点 `PATCH /api/v1/agents/{id}/toggle`, 与 `update()` 区分:
   * - toggle 是高频、单字段、可审计的独立操作
   * - 返回完整更新后的 profile, 调用方一次 setState 即可
   *
   * @throws 后端 404 (id 不存在) 或 422 (类型错) 经 handleApiError 包装
   */
  async toggle(id: string, enabled: boolean): Promise<AgentProfile> {
    return withRetry(async () => {
      try {
        return await invoke<AgentProfile>('toggle_agent', { id, enabled });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /**
   * 部分更新 agent (PR-4)。
   *
   * Tauri 命令签名 `update_agent(id, update)`, 不接受整 AgentProfile —
   * 调用方应传 diff (例如 `{ name: '新名' }`), 不要把当前 profile 整对象塞进来。
   *
   * 后端 Pydantic 校验:
   * - role 必须 ∈ {coordinator, researcher, coder, memory_manager} 否则 422
   * - max_iterations 必须 ∈ [1, 50] 否则 422
   * - 空 body 视为 no-op, 200 返回当前 profile, updated_at 不刷新
   *
   * @throws 后端 404 / 422 经 handleApiError 包装
   */
  async update(id: string, update: AgentUpdate): Promise<AgentProfile> {
    return withRetry(async () => {
      try {
        return await invoke<AgentProfile>('update_agent', { id, update });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
