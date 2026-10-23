import { describe, expect, it } from 'vitest';

import {
  auditLastWorkspaceGovernance,
  formatLastWorkspaceJson,
  formatLastWorkspaceSummary,
} from '../lastWorkspace';

describe('lastWorkspace P179 governance audit', () => {
  it('audits lastWorkspace governance contract and summary helpers', () => {
    const raw = auditLastWorkspaceGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.last_workspace.governance.v1');
    expect(parsed.phase).toBe('P179');
    expect(parsed.storageKey).toBe('sage-last-workspace-path');
    expect(formatLastWorkspaceSummary('/repo')).toBe('persisted · /repo');
    expect(JSON.parse(formatLastWorkspaceJson('/repo')).persisted).toBe(true);
  });
});
