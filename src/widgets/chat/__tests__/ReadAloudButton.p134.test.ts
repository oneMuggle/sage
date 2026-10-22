import { describe, expect, it } from 'vitest';

import {
  evaluateReadAloudButtonAudit,
  exportReadAloudButtonAuditJson,
} from '../ReadAloudButton';

describe('ReadAloudButton audit diagnostics (Phase P134)', () => {
  it('confirms readiness when speech and voice are available', () => {
    const report = evaluateReadAloudButtonAudit({
      textLength: 180,
      speechSupported: true,
      isSpeaking: false,
      voiceAvailable: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.canSpeak).toBe(true);
  });

  it('flags empty text and missing voice support', () => {
    const parsed = JSON.parse(
      exportReadAloudButtonAuditJson({
        textLength: 0,
        speechSupported: true,
        isSpeaking: false,
        voiceAvailable: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('empty_read_aloud_text');
    expect(parsed.issueCodes).toContain('no_speech_voice_available');
  });
});
