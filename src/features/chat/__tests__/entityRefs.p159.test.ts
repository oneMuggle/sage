import { describe, expect, it } from 'vitest';

import {
  auditEntityRefsGovernance,
  buildEntityRefsAuditJson,
  ENTITY_REF_KINDS,
} from '../entityRefs';

describe('entityRefs governance audit (P159)', () => {
  it('verifies entity reference kinds and default suggestion count', () => {
    const report = auditEntityRefsGovernance();
    expect(report.module).toBe('features.chat.entityRefs');
    expect(report.phase).toBe('P159');
    expect(report.kindCount).toBe(ENTITY_REF_KINDS.length);
    expect(report.defaultSuggestionCount).toBe(4);
    expect(report.healthy).toBe(true);
  });

  it('maintains JSON audit helper serialization', () => {
    const raw = buildEntityRefsAuditJson('wiki:plan');
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
