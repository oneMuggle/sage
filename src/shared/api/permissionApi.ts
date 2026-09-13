/**
 * Sage API - Permission presets & session auto-approval audit (对标 S3, 2026-09-13)
 *
 * - 三档 preset（careful / standard / auto）映射到后端既有 permission_mode
 *   （prompt / workspace_write / full_access），零后端语义改动。
 * - 会话自动放行列表：本会话未经用户确认即放行的工具调用（"已自动批准 N 次"）。
 */

import { invoke } from './desktopInvoke';
import { handleApiError } from './utils';

export type PermissionPreset = 'careful' | 'standard' | 'auto';

export const PERMISSION_PRESETS: readonly PermissionPreset[] = ['careful', 'standard', 'auto'];

export interface PermissionPresetState {
  preset: PermissionPreset;
  /** 后端真实 permission_mode（read_only 等非三档值时 custom=true） */
  mode: string;
  custom: boolean;
}

export interface AutoApprovalRecord {
  seq: number;
  session_id: string;
  tool_name: string;
  capability: 'read' | 'write' | 'execute' | string;
  mode: string;
  reason: string;
  summary: string;
  created_at: number;
}

export interface SessionAutoApprovals {
  session_id: string;
  /** 有副作用（write/execute）的自动放行次数 */
  count: number;
  /** 含只读在内的全部自动放行次数 */
  total: number;
  items: AutoApprovalRecord[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function asPreset(v: unknown): PermissionPreset {
  return v === 'careful' || v === 'standard' || v === 'auto' ? v : 'standard';
}

export const permissionApi = {
  async getPreset(): Promise<PermissionPresetState> {
    const fallback: PermissionPresetState = { preset: 'standard', mode: 'workspace_write', custom: false };
    try {
      const raw = await invoke<unknown>('permissions_get_preset', {});
      if (!isRecord(raw)) return fallback;
      return {
        preset: asPreset(raw.preset),
        mode: typeof raw.mode === 'string' ? raw.mode : fallback.mode,
        custom: raw.custom === true,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async setPreset(preset: PermissionPreset): Promise<void> {
    try {
      await invoke('permissions_set_preset', { preset });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async getSessionAutoApprovals(
    sessionId: string,
    options?: { limit?: number; sideEffectOnly?: boolean },
  ): Promise<SessionAutoApprovals> {
    const empty: SessionAutoApprovals = { session_id: sessionId, count: 0, total: 0, items: [] };
    if (!sessionId) return empty;
    try {
      const raw = await invoke<unknown>('permissions_session_auto_approvals', {
        sessionId,
        limit: options?.limit ?? 50,
        sideEffectOnly: options?.sideEffectOnly ?? true,
      });
      if (!isRecord(raw)) return empty;
      const items = Array.isArray(raw.items)
        ? (raw.items as unknown[]).filter(isRecord).map(
            (r): AutoApprovalRecord => ({
              seq: Number(r.seq) || 0,
              session_id: String(r.session_id ?? sessionId),
              tool_name: String(r.tool_name ?? ''),
              capability: String(r.capability ?? 'write'),
              mode: String(r.mode ?? ''),
              reason: String(r.reason ?? ''),
              summary: String(r.summary ?? ''),
              created_at: Number(r.created_at) || 0,
            }),
          )
        : [];
      return {
        session_id: sessionId,
        count: Number(raw.count) || 0,
        total: Number(raw.total) || 0,
        items,
      };
    } catch {
      // 纯增强信息：失败静默
      return empty;
    }
  },
};
