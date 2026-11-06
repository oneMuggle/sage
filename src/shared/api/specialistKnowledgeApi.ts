/**
 * Sage API - 专家知识绑定 CRUD（M2-Task 2）
 *
 * 对应后端 `backend/api/specialist_routes.py` 的三个端点：
 *
 * - `GET    /api/v1/specialists/{agent_id}/knowledge` → KnowledgeBinding[]
 * - `POST   /api/v1/specialists/{agent_id}/knowledge` → KnowledgeBinding（201）
 * - `DELETE /api/v1/specialists/{agent_id}/knowledge/{binding_id}` → 204
 *
 * 走 `backendRequest`（Electron 主进程直连后端），而不是 `invoke` 命令表：
 * 知识绑定是专家子资源，命令表没有（也不值得加）对应 command route。
 * DELETE 返回 204 无 body，main 进程默认 `response.json()` 会解析失败，
 * 因此显式 `responseType: 'text'`。
 */

import { backendRequest } from './backendRequest';
import type { KnowledgeBinding, KnowledgeBindingCreate } from './types/domainEntityTypes';

function knowledgePath(agentId: string): string {
  return `/api/v1/specialists/${encodeURIComponent(agentId)}/knowledge`;
}

export const specialistKnowledgeApi = {
  /** 列出专家的全部知识绑定（按 created_at 升序）。404 = 专家不存在。 */
  async list(agentId: string): Promise<KnowledgeBinding[]> {
    return backendRequest<KnowledgeBinding[]>({
      method: 'GET',
      path: knowledgePath(agentId),
    });
  },

  /** 新增一条绑定。`payload.agent_id` 会被强制覆盖为路径里的 agentId。 */
  async create(
    agentId: string,
    payload: Omit<KnowledgeBindingCreate, 'agent_id'>,
  ): Promise<KnowledgeBinding> {
    return backendRequest<KnowledgeBinding>({
      method: 'POST',
      path: knowledgePath(agentId),
      body: { ...payload, agent_id: agentId },
    });
  },

  /** 删除一条绑定。204 无 body；404 = 专家或绑定不存在。 */
  async remove(agentId: string, bindingId: string): Promise<void> {
    await backendRequest<string>({
      method: 'DELETE',
      path: `${knowledgePath(agentId)}/${encodeURIComponent(bindingId)}`,
      responseType: 'text',
    });
  },
};
