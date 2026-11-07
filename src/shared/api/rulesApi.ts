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
};
