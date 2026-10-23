import { describe, expect, it } from 'vitest';

import {
  auditUseResizableSidebarGovernance,
  formatResizableSidebarJson,
  formatResizableSidebarSummary,
} from '../useResizableSidebar';

describe('useResizableSidebar P181 governance audit', () => {
  it('audits useResizableSidebar governance contract and sidebar width formatters', () => {
    const raw = auditUseResizableSidebarGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.use_resizable_sidebar.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.storageKey).toBe('sidebar-width');
    expect(formatResizableSidebarSummary(100, false)).toContain('sidebar=260px');
    expect(JSON.parse(formatResizableSidebarJson(600, true)).width).toBe(480);
  });
});
