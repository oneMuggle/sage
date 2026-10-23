import { describe, expect, it } from 'vitest';

import {
  auditAnswerVersionsGovernance,
  buildAnswerVersionsAuditJson,
  lastTurnAnchorIndex,
} from '../answerVersions';

describe('answerVersions governance audit (P159)', () => {
  it('verifies answer version APIs and anchor helper contract', () => {
    const report = auditAnswerVersionsGovernance();
    expect(report.module).toBe('features.chat.answerVersions');
    expect(report.phase).toBe('P159');
    expect(report.hasFetchApi).toBe(true);
    expect(report.hasActivateApi).toBe(true);
    expect(report.hasAnchorHelper).toBe(true);
    expect(report.healthy).toBe(true);
    expect(lastTurnAnchorIndex([], 0)).toBe(-1);
  });

  it('maintains JSON audit helper serialization', () => {
    const raw = buildAnswerVersionsAuditJson();
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
