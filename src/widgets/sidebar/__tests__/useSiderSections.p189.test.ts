import { describe, expect, it } from 'vitest';

import { auditSiderSectionsGovernance } from '../useSiderSections';

describe('auditSiderSectionsGovernance (Phase P189)', () => {
  it('returns deterministic P189 governance audit payload', () => {
    const payload = JSON.parse(auditSiderSectionsGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('sider-sections');
    expect(payload.phase).toBe('P189');
    expect(payload.audited).toBe(true);
  });
});
