import { describe, expect, it } from 'vitest';

import {
  auditWorkspaceApiGovernance,
  formatWorkspaceBindingJson,
  formatWorkspaceBindingSummary,
} from '../workspaceApi';

describe('workspaceApi P177 governance audit', () => {
  it('audits workspaceApi governance contract and workspace binding formatters', () => {
    const raw = auditWorkspaceApiGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.workspace_api.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.supportsCheckpoints).toBe(true);
    expect(formatWorkspaceBindingSummary(null)).toBe('unbound');
    expect(JSON.parse(formatWorkspaceBindingJson(null)).bound).toBe(false);
  });
});
