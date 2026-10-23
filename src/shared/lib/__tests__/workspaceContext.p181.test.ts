import { describe, expect, it } from 'vitest';

import {
  auditWorkspaceContextGovernance,
  formatWorkspaceBindingJson,
  formatWorkspaceBindingSummary,
} from '../workspaceContext';

describe('workspaceContext P181 governance audit', () => {
  it('audits workspaceContext governance contract and binding formatters', () => {
    const raw = auditWorkspaceContextGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.workspace_context.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.unmountedSummary).toContain('provider=unmounted');
    expect(formatWorkspaceBindingSummary({ binding: { workspacePath: '/repo' }, status: 'ready' })).toBe(
      'provider=mounted · status=ready · bound=true',
    );
    expect(JSON.parse(formatWorkspaceBindingJson(null)).providerMounted).toBe(false);
  });
});
