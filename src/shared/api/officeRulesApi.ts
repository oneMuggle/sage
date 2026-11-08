/**
 * Rules CRUD / extraction / audit client.
 *
 * FastAPI HTTP routes reached through the authenticated Electron relay; bodies
 * and responses stay snake_case. Camel-casing happens in
 * src/features/office/rules/ruleMapping.ts.
 */

import { backendRequest } from './backendRequest';
import type {
  WireAuditRequest,
  WireAuditResult,
  WireConflictResult,
  WireDeleteResult,
  WireExportRequest,
  WireExtractRequest,
  WireExtractResult,
  WireGroupInput,
  WireGroupPatch,
  WireImportResult,
  WireRule,
  WireRuleGroup,
  WireRuleInput,
  WireRulePack,
  WireRulePatch,
} from './types';
import { handleApiError } from './utils';

const RULES_PREFIX = '/api/v1/rules';

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  try {
    return await backendRequest<T>(
      options.body === undefined ? { path, method } : { path, method, body: options.body },
    );
  } catch (error) {
    throw handleApiError(error);
  }
}

function groupPath(groupId: string): string {
  return `${RULES_PREFIX}/groups/${encodeURIComponent(groupId)}`;
}

function rulePath(ruleId: string): string {
  return `${RULES_PREFIX}/rules/${encodeURIComponent(ruleId)}`;
}

export const officeRulesApi = {
  listGroups(): Promise<WireRuleGroup[]> {
    return request(`${RULES_PREFIX}/groups`);
  },

  createGroup(input: WireGroupInput): Promise<WireRuleGroup> {
    return request(`${RULES_PREFIX}/groups`, { method: 'POST', body: input });
  },

  updateGroup(groupId: string, patch: WireGroupPatch): Promise<WireRuleGroup> {
    return request(groupPath(groupId), { method: 'PUT', body: patch });
  },

  deleteGroup(groupId: string): Promise<WireDeleteResult> {
    return request(groupPath(groupId), { method: 'DELETE' });
  },

  createRule(groupId: string, input: WireRuleInput): Promise<WireRule> {
    return request(`${groupPath(groupId)}/rules`, { method: 'POST', body: input });
  },

  updateRule(ruleId: string, patch: WireRulePatch): Promise<WireRule> {
    return request(rulePath(ruleId), { method: 'PUT', body: patch });
  },

  deleteRule(ruleId: string): Promise<WireDeleteResult> {
    return request(rulePath(ruleId), { method: 'DELETE' });
  },

  extractRules(input: WireExtractRequest): Promise<WireExtractResult> {
    return request(`${RULES_PREFIX}/extract`, { method: 'POST', body: input });
  },

  checkConflicts(ruleIds: string[]): Promise<WireConflictResult> {
    return request(`${RULES_PREFIX}/check-conflicts`, {
      method: 'POST',
      body: { rule_ids: ruleIds },
    });
  },

  exportPack(input: WireExportRequest): Promise<WireRulePack> {
    return request(`${RULES_PREFIX}/export`, { method: 'POST', body: input });
  },

  importPack(pack: WireRulePack): Promise<WireImportResult> {
    return request(`${RULES_PREFIX}/import`, { method: 'POST', body: pack });
  },

  audit(input: WireAuditRequest): Promise<WireAuditResult> {
    return request(`${RULES_PREFIX}/audit`, { method: 'POST', body: input });
  },
};
