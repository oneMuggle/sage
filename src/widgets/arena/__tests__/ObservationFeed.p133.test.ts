import { describe, expect, it } from 'vitest';

import {
  auditObservationFeed,
  exportObservationFeedAuditJson,
} from '../ObservationFeed';

describe('ObservationFeed audit diagnostics', () => {
  it('audits empty and populated observation feeds', () => {
    const empty = auditObservationFeed();
    expect(empty.schemaVersion).toBe('1.0');
    expect(empty.module).toBe('src/widgets/arena/ObservationFeed.tsx');
    expect(empty.entryCount).toBe(0);
    expect(empty.isEmpty).toBe(true);

    const populated = auditObservationFeed(4);
    expect(populated.entryCount).toBe(4);
    expect(populated.isEmpty).toBe(false);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportObservationFeedAuditJson(3));
    expect(parsed.componentName).toBe('ObservationFeed');
    expect(parsed.entryCount).toBe(3);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
