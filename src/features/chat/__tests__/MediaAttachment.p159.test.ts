import { describe, expect, it } from 'vitest';

import {
  auditMediaAttachmentGovernance,
  formatMediaAttachmentJson,
  MediaAttachment,
} from '../MediaAttachment';

describe('MediaAttachment governance audit (P159)', () => {
  it('verifies MediaAttachment component and summary formatter readiness', () => {
    const report = auditMediaAttachmentGovernance();
    expect(report.module).toBe('features.chat.MediaAttachment');
    expect(report.phase).toBe('P159');
    expect(report.hasComponent).toBe(true);
    expect(report.hasSummaryFormatter).toBe(true);
    expect(report.healthy).toBe(true);
    expect(typeof MediaAttachment).toBe('function');
  });

  it('serializes JSON audit output for media attachment metadata', () => {
    const raw = formatMediaAttachmentJson('image/png', true);
    expect(JSON.parse(raw)).toBeTruthy();
  });
});
