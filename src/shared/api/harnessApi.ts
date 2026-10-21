/**
 * Harness API 客户端 —— 调后端 ``/api/v1/harness/*`` 路由
 * （见 ``backend/api/harness_routes.py``）。
 *
 * 走 ``backendRequest`` —— 与 ``manage-endpoints/api.ts`` 同款，
 * 经 Electron IPC bridge 透传到本机后端（``electron/main.ts``
 * ``sage:backend-request`` handler），不直接打 fetch，避免 CORS。
 */

import type {
  HarnessComponent,
  HarnessComponentListResponse,
  HarnessNeedingImprovementResponse,
} from '../../entities/harness/types';
import { backendRequest } from './backendRequest';
import { isDemoMode } from './demoFlag';

export const harnessApi = {
  /**
   * 列出 harness 组件及其 effectiveness 指标。
   *
   * 与 ``GET /api/v1/harness/components`` 对应；可按 ``type`` 过滤
   * （合法值由后端 ``HARNESS_COMPONENT_TYPES`` 常量限定）。
   */
  async listComponents(type?: string): Promise<HarnessComponentListResponse> {
    if (isDemoMode()) return demoList(type);
    const query = type ? `?type=${encodeURIComponent(type)}` : '';
    return backendRequest<HarnessComponentListResponse>({
      path: `/api/v1/harness/components${query}`,
      method: 'GET',
    });
  },

  /** 列出效果不佳待改进的组件。 */
  async listNeedingImprovement(): Promise<HarnessNeedingImprovementResponse> {
    if (isDemoMode()) return { items: [], total: 0 };
    return backendRequest<HarnessNeedingImprovementResponse>({
      path: '/api/v1/harness/needing-improvement',
      method: 'GET',
    });
  },

  /** 手动记录一次组件使用（测试 / 调试用）。 */
  async recordUsage(
    componentId: string,
    payload: { success: boolean; latency_ms: number },
  ): Promise<HarnessComponent> {
    if (isDemoMode()) {
      throw new Error('演示模式下无法 record usage');
    }
    return backendRequest<HarnessComponent>({
      path: `/api/v1/harness/components/${encodeURIComponent(componentId)}/record`,
      method: 'POST',
      body: payload,
    });
  },
};

/**
 * Demo 模式下的桩数据 —— 让开发期即使后端没启动也能预览 UI。
 *
 * 仅展示两条合成数据；不做真实埋点。
 */
function demoList(type?: string): HarnessComponentListResponse {
  const items: HarnessComponent[] = [
    {
      id: 'tool:bash',
      type: 'tool_guidance',
      name: 'bash',
      version: '1.0.0',
      config: {},
      effectiveness: {
        usage_count: 42,
        success_rate: 0.92,
        avg_latency_ms: 320.5,
        user_satisfaction: null,
        last_used_at: '2026-10-21T10:00:00Z',
      },
      needs_improvement: false,
      created_at: '2026-10-20T08:00:00Z',
      updated_at: '2026-10-21T10:00:00Z',
    },
    {
      id: 'skill:academic-search',
      type: 'skills',
      name: 'academic-search',
      version: '1.0.0',
      config: {},
      effectiveness: {
        usage_count: 5,
        success_rate: 0.6,
        avg_latency_ms: 1800.0,
        user_satisfaction: null,
        last_used_at: '2026-10-21T09:30:00Z',
      },
      needs_improvement: true,
      created_at: '2026-10-20T09:00:00Z',
      updated_at: '2026-10-21T09:30:00Z',
    },
  ];
  const filtered = type ? items.filter((c) => c.type === type) : items;
  return {
    items: filtered,
    total: filtered.length,
    component_types: [
      'system_prompt',
      'guardrails',
      'memory',
      'tool_guidance',
      'subagents',
      'skills',
      'scripts',
      'plugins',
    ],
  };
}
