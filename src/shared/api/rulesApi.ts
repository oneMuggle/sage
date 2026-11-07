/**
 * 规则中心 API 客户端（M3，2026-11-07）。
 *
 * 后端返回 snake_case（`source_label` / `updated_at`），这里映射到 camelCase，
 * 与 projectApiTypes.ts 的模式一致。
 */

import { invoke } from './desktopInvoke';

export type RuleLayer = 'constraint' | 'playbook' | 'doc' | 'global';
export type RuleEditable = 'full' | 'partial' | 'readonly';

export interface RuleEntry {
  id: string;
  layer: RuleLayer;
  sourceLabel: string;
  scope: string;
  category: string;
  content: string;
  enabled: boolean;
  editable: RuleEditable;
  priority: number;
  trigger: string | null;
  updatedAt: number | null;
  origin: string | null;
}

export interface RuleConflict {
  a: string;
  b: string;
  category: string;
  triggers: Array<string | null>;
}

export interface EffectiveRulesResponse {
  entries: RuleEntry[];
  conflicts: RuleConflict[];
}

/** 可写层；`playbook` 只能跳转规程编辑器，不在此列。 */
export type CreatableRuleLayer = 'constraint' | 'doc' | 'global';

export interface RuleCreateInput {
  layer: CreatableRuleLayer;
  /** constraint：分类；doc/global：新小节标题。留空用后端默认值。 */
  category?: string;
  content: string;
  /** 仅 constraint 生效；`null` 表示始终生效。 */
  triggerPattern?: string | null;
  priority?: number;
  enabled?: boolean;
}

export interface RulePatchPayload {
  content?: string;
  category?: string;
  /** 传 `null` 或 `''` 都是「清空触发词」。 */
  triggerPattern?: string | null;
  priority?: number;
  enabled?: boolean;
}

export interface RulePatchInput {
  layer: RuleLayer;
  ruleId: string;
  patch: RulePatchPayload;
  /** 仅 constraint 支持；与后端 `updated_at` 不符时 409 `rule_conflict`。 */
  expectedUpdatedAt?: number | null;
}

export interface RawRulesResponse {
  path: string;
  content: string;
  truncated: boolean;
}

interface RuleEntryWire {
  id: string;
  layer: RuleLayer;
  source_label: string;
  scope: string;
  category: string;
  content: string;
  enabled: boolean;
  editable: RuleEditable;
  priority: number;
  trigger: string | null;
  updated_at: number | null;
  origin: string | null;
}

export function mapRuleEntry(wire: RuleEntryWire): RuleEntry {
  return {
    id: wire.id,
    layer: wire.layer,
    sourceLabel: wire.source_label,
    scope: wire.scope,
    category: wire.category,
    content: wire.content,
    enabled: wire.enabled,
    editable: wire.editable,
    priority: wire.priority,
    trigger: wire.trigger,
    updatedAt: wire.updated_at,
    origin: wire.origin,
  };
}

export const rulesApi = {
  async list(projectId: string): Promise<RuleEntry[]> {
    const response = await invoke<{ rules: RuleEntryWire[] }>('rules_list', { projectId });
    return (response.rules ?? []).map(mapRuleEntry);
  },

  async effective(projectId: string): Promise<EffectiveRulesResponse> {
    const response = await invoke<{ entries: RuleEntryWire[]; conflicts: RuleConflict[] }>(
      'rules_effective',
      { projectId },
    );
    return {
      entries: (response.entries ?? []).map(mapRuleEntry),
      conflicts: response.conflicts ?? [],
    };
  },

  async create(projectId: string, input: RuleCreateInput): Promise<void> {
    await invoke<{ ok: boolean }>('rules_create', { projectId, ...input });
  },

  async update(projectId: string, input: RulePatchInput): Promise<void> {
    await invoke<{ ok: boolean }>('rules_update', { projectId, ...input });
  },

  async remove(projectId: string, layer: RuleLayer, ruleId: string): Promise<void> {
    await invoke<{ ok: boolean }>('rules_delete', { projectId, layer, ruleId });
  },

  async raw(projectId: string, layer: CreatableRuleLayer): Promise<RawRulesResponse> {
    const response = await invoke<{
      path: string;
      content: string;
      truncated: boolean;
    }>('rules_raw', { projectId, layer });
    return {
      path: response.path ?? '',
      content: response.content ?? '',
      truncated: Boolean(response.truncated),
    };
  },
};
