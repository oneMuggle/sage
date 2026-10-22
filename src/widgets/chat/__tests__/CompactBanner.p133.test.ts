import { describe, expect, it } from 'vitest';

import {
  auditCompactBanner,
  exportCompactBannerAuditJson,
} from '../CompactBanner';

describe('CompactBanner audit diagnostics', () => {
  it('audits compact banner message counts', () => {
    const def = auditCompactBanner();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/widgets/chat/CompactBanner.tsx');
    expect(def.beforeCount).toBe(20);
    expect(def.afterCount).toBe(6);
    expect(def.removedCount).toBe(14);

    const neg = auditCompactBanner(-1, -2, -3);
    expect(neg.beforeCount).toBe(0);
    expect(neg.afterCount).toBe(0);
    expect(neg.removedCount).toBe(0);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportCompactBannerAuditJson(30, 10, 20));
    expect(parsed.componentName).toBe('CompactBanner');
    expect(parsed.removedCount).toBe(20);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
