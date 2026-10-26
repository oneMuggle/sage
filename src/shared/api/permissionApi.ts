/**
 * Sage API - Permission presets & session auto-approval audit (对标 S3, 2026-09-13)
 *
 * - 三档 preset（careful / standard / auto）映射到后端既有 permission_mode
 *   （prompt / workspace_write / full_access），零后端语义改动。
 * - 会话自动放行列表：本会话未经用户确认即放行的工具调用（"已自动批准 N 次"）。
 */

import { isDemoMode } from './demoFlag';
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

/**
 * P2-5 渐进式授权策略。
 *
 * `consecutive` 的键是 `session_id|tool_name`，值是该会话内该工具**最近连续**
 * 被用户手动批准的次数。把它暴露给 UI，是为了让用户看得见「哪些工具已经
 * 攒够信任」—— 渐进式授权最容易被质疑的就是「它凭什么替我点同意」。
 */
export interface TrustPolicyState {
  enabled: boolean;
  threshold: number;
  default_threshold: number;
  consecutive: Record<string, number>;
}

export type PermissionRuleDecision = 'allow' | 'deny' | 'ask';

/**
 * 一条已保存（且生效）的权限规则，与后端规则列表响应同形。
 *
 * `plugin_name` / `plugin_status` 是 R101 的只读派生标注（插件
 * 归属与生命周期状态，另含派生值 `missing` / `all`），只供
 * 设置页提示「这条规则属于已卸载/无记录插件」；删除时不发送。
 */
export interface PermissionRuleItem {
  tool_pattern: string;
  decision: PermissionRuleDecision;
  plugin_name?: string | null;
  plugin_status?: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function asPreset(v: unknown): PermissionPreset {
  return v === 'careful' || v === 'standard' || v === 'auto' ? v : 'standard';
}

/**
 * 解析后端规则列表：只保留 tool_pattern 非空且 decision 合法的条目。
 * 后端 parse_rules 已按下同口径过滤，这里再做一层宽容解析，避免
 * 旧后端/异常响应把坏条目带进 UI。
 */
function parseRuleItems(raw: unknown): PermissionRuleItem[] {
  if (!isRecord(raw) || !Array.isArray(raw.rules)) return [];
  const items: PermissionRuleItem[] = [];
  for (const entry of raw.rules as unknown[]) {
    if (!isRecord(entry)) continue;
    const pattern = entry.tool_pattern;
    const decision = entry.decision;
    if (typeof pattern !== 'string' || pattern.length === 0) continue;
    if (decision !== 'allow' && decision !== 'deny' && decision !== 'ask') continue;
    items.push({
      tool_pattern: pattern,
      decision,
      plugin_name: typeof entry.plugin_name === 'string' ? entry.plugin_name : null,
      plugin_status: typeof entry.plugin_status === 'string' ? entry.plugin_status : null,
    });
  }
  return items;
}

export const permissionApi = {
  async getPreset(): Promise<PermissionPresetState> {
    const fallback: PermissionPresetState = {
      preset: 'standard',
      mode: 'workspace_write',
      custom: false,
    };
    if (isDemoMode()) return fallback;
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
    if (!sessionId || isDemoMode()) return empty;
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

  /**
   * P2-5 读取渐进式授权策略。demo 模式返回「关闭」—— 演示数据里没有真实的
   * 审批历史，报一个假的信任度只会误导。
   */
  async getTrustPolicy(): Promise<TrustPolicyState> {
    const fallback: TrustPolicyState = {
      enabled: false,
      threshold: 3,
      default_threshold: 3,
      consecutive: {},
    };
    if (isDemoMode()) return fallback;
    try {
      const raw = await invoke<unknown>('permissions_get_trust_policy', {});
      if (!isRecord(raw)) return fallback;
      const consecutive: Record<string, number> = {};
      if (isRecord(raw.consecutive)) {
        for (const [key, value] of Object.entries(raw.consecutive)) {
          const n = Number(value);
          if (Number.isFinite(n) && n > 0) consecutive[key] = n;
        }
      }
      return {
        enabled: raw.enabled === true,
        threshold: Number(raw.threshold) || fallback.threshold,
        default_threshold: Number(raw.default_threshold) || fallback.default_threshold,
        consecutive,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async setTrustPolicy(enabled: boolean, threshold?: number): Promise<TrustPolicyState> {
    const fallback: TrustPolicyState = {
      enabled,
      threshold: threshold ?? 3,
      default_threshold: 3,
      consecutive: {},
    };
    if (isDemoMode()) return fallback;
    try {
      const raw = await invoke<unknown>('permissions_set_trust_policy', { enabled, threshold });
      if (!isRecord(raw)) return fallback;
      return {
        enabled: raw.enabled === true,
        threshold: Number(raw.threshold) || fallback.threshold,
        default_threshold: fallback.default_threshold,
        consecutive: {},
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R97 读取已保存且生效的权限规则（设置页「已记住的规则」）。
   * demo 模式返回空列表——演示环境没有真实的已记住规则。
   */
  async listRules(): Promise<PermissionRuleItem[]> {
    if (isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_list_rules', {});
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R99 按内容逐条删除一条规则，返回服务端删除后
   * 的最新列表（UI 直接采用，不在前端自行 splice 后假定成功）。
   * 传入的是 listRules() 返回的行对象，其 tool_pattern/decision
   * 只是「删哪一条」的选择子，不是用户手输的新 pattern。
   */
  async deleteRule(rule: PermissionRuleItem): Promise<PermissionRuleItem[]> {
    if (isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_delete_rule', {
        toolPattern: rule.tool_pattern,
        decision: rule.decision,
      });
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R102 删除某个插件名下的全部已保存规则（按归属撤销持久信任）。
   * 只传插件名；删哪几条由后端按生命周期名单与结构化归属决定，
   * 返回删除后的最新列表，前端直接采用。
   */
  async deleteRulesByPlugin(pluginName: string): Promise<PermissionRuleItem[]> {
    if (isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_delete_rules_by_plugin', {
        pluginName,
      });
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R104 清理全部无归属插件孤儿规则（后端按 missing 类
   * 选集），返回删除后的最新列表。无参数：语义只有
   * 「全部孤儿」，客户端不传任何选择子。
   */
  async deleteOrphanRules(): Promise<PermissionRuleItem[]> {
    if (isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_delete_orphan_rules', {});
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R100 清空全部已记住规则（撤销全部持久信任），返回服务端
   * 清空后的最新列表（应为空）。无筛选参数：语义只有「全部」。
   */
  async clearRules(): Promise<PermissionRuleItem[]> {
    if (isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_clear_rules', {});
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R106 读取某会话「仅本次会话记住」的规则（聊天顶栏数据源）。
   * 形态与 listRules 同形（含 R101 归属标注），共用宽容解析；
   * demo 模式返回空列表（演示环境没有真实会话规则）。
   */
  async listSessionRememberedRules(sessionId: string): Promise<PermissionRuleItem[]> {
    if (!sessionId || isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_list_session_rules', { sessionId });
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R106 按内容撤销一条会话规则，返回服务端删除后的最新列表
   * （UI 直接采用）。传入的行对象来自 listSessionRememberedRules，
   * 其 tool_pattern/decision 只是删除选择子，不能创建任何规则。
   */
  async deleteSessionRememberedRule(
    sessionId: string,
    rule: PermissionRuleItem,
  ): Promise<PermissionRuleItem[]> {
    if (!sessionId || isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_delete_session_rule', {
        sessionId,
        toolPattern: rule.tool_pattern,
        decision: rule.decision,
      });
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * R106 清空某会话的全部会话规则，返回服务端清空后的最新
   * 列表（应为空）。只传会话 ID、无筛选参数，持久规则不受影响。
   */
  async clearSessionRememberedRules(sessionId: string): Promise<PermissionRuleItem[]> {
    if (!sessionId || isDemoMode()) return [];
    try {
      const raw = await invoke<unknown>('permissions_clear_session_rules', { sessionId });
      return parseRuleItems(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },
};

export function auditPermissionApiGovernance(
  state: {
    activePreset?: PermissionPreset | string;
    autoApprovalCount?: number;
  } = {},
): {
  module: 'src/shared/api/permissionApi.ts';
  phase: 'P145';
  activePreset: PermissionPreset;
  presetCount: number;
  autoApprovalCount: number;
  healthy: boolean;
} {
  const activePreset: PermissionPreset =
    state.activePreset === 'careful' || state.activePreset === 'auto'
      ? state.activePreset
      : 'standard';
  const presetCount = PERMISSION_PRESETS.length;
  const autoApprovalCount =
    typeof state.autoApprovalCount === 'number' && Number.isFinite(state.autoApprovalCount)
      ? Math.max(0, Math.trunc(state.autoApprovalCount))
      : 0;
  return {
    module: 'src/shared/api/permissionApi.ts',
    phase: 'P145',
    activePreset,
    presetCount,
    autoApprovalCount,
    healthy: presetCount === 3 && autoApprovalCount >= 0,
  };
}
