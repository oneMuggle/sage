import { describe, expect, it } from 'vitest';

import { auditSidebarProjectListGovernance } from '../sections/SidebarProjectList';

describe('SidebarProjectList P150 governance audit', () => {
  it('returns healthy defaults for SidebarProjectList governance', () => {
    const res = auditSidebarProjectListGovernance();
    expect(res.module).toBe('src/widgets/sidebar/sections/SidebarProjectList.tsx');
    expect(res.phase).toBe('P150');
    expect(res.projectCount).toBe(3);
    expect(res.hasActiveProject).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('normalizes negative projectCount to 0', () => {
    const res = auditSidebarProjectListGovernance({
      projectCount: -4,
      hasActiveProject: false,
    });
    expect(res.projectCount).toBe(0);
    expect(res.hasActiveProject).toBe(false);
    expect(res.healthy).toBe(true);
  });
});
