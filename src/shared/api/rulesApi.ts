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

export type PatchAction = 'add' | 'update' | 'delete' | 'toggle';

/** apply 的单条执行结果；`invalid` 与 `conflict` 都算未应用。 */
export type PatchResultStatus = 'applied' | 'invalid' | 'conflict';

export interface PatchOperation {
  opId: string;
  action: PatchAction;
  layer: RuleLayer;
  ruleId: string | null;
  /** 可写层为条目快照；新增为空对象。 */
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
  expectedUpdatedAt: number | null;
  /** 预览阶段已判定的不可执行原因（readonly_layer / rule_not_found 等）。 */
  error: string | null;
}

export interface PatchPreviewResponse {
  llmAvailable: boolean;
  message: string;
  operations: PatchOperation[];
}

export interface PatchApplyResult {
  opId: string;
  status: PatchResultStatus;
  message: string;
  /** conflict 时附带的当前值。 */
  current: Record<string, unknown> | null;
}

export interface PatchApplyResponse {
  results: PatchApplyResult[];
  applied: number;
  failed: number;
}

interface PatchOperationWire {
  op_id: string;
  action: PatchAction;
  layer: RuleLayer;
  rule_id: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
  expected_updated_at: number | null;
  error: string | null;
}

function mapPatchOperation(wire: PatchOperationWire): PatchOperation {
  return {
    opId: wire.op_id,
    action: wire.action,
    layer: wire.layer,
    ruleId: wire.rule_id ?? null,
    before: wire.before ?? {},
    after: wire.after ?? {},
    reason: wire.reason ?? '',
    expectedUpdatedAt: wire.expected_updated_at ?? null,
    error: wire.error ?? null,
  };
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

  async previewPatch(
    projectId: string,
    input: { instruction: string; ruleId?: string | null },
  ): Promise<PatchPreviewResponse> {
    const response = await invoke<{
      llm_available: boolean;
      message: string;
      operations: PatchOperationWire[];
    }>('rules_patch_preview', {
      projectId,
      instruction: input.instruction,
      ruleId: input.ruleId ?? null,
    });
    return {
      llmAvailable: Boolean(response.llm_available),
      message: response.message ?? '',
      operations: (response.operations ?? []).map(mapPatchOperation),
    };
  },

  async applyPatch(
    projectId: string,
    input: { instruction: string; operations: PatchOperation[] },
  ): Promise<PatchApplyResponse> {
    const response = await invoke<{
      results: Array<{
        op_id: string;
        status: PatchResultStatus;
        message: string;
        current?: Record<string, unknown> | null;
      }>;
      applied: number;
      failed: number;
    }>('rules_patch_apply', {
      projectId,
      instruction: input.instruction,
      operations: input.operations.map((operation) => ({
        opId: operation.opId,
        action: operation.action,
        layer: operation.layer,
        ruleId: operation.ruleId,
        before: operation.before,
        after: operation.after,
        reason: operation.reason,
        expectedUpdatedAt: operation.expectedUpdatedAt,
      })),
    });
    return {
      results: (response.results ?? []).map((item) => ({
        opId: item.op_id,
        status: item.status,
        message: item.message ?? '',
        current: item.current ?? null,
      })),
      applied: Number(response.applied ?? 0),
      failed: Number(response.failed ?? 0),
    };
  },
};
