import { describe, expect, it } from 'vitest';

import {
  SPEECH_CHUNK_MAX,
  auditSpeechGovernance,
  buildSpeechAuditJson,
  detectSpeechLang,
} from '../speech';

describe('speech Phase P160 governance audit', () => {
  it('audits speech governance metadata', () => {
    const audit = auditSpeechGovernance('sess-p160', 'voice-interface');
    expect(audit.phase).toBe('P160');
    expect(audit.module).toBe('src/features/chat/speech.ts');
    expect(audit.sessionId).toBe('sess-p160');
    expect(audit.archetype).toBe('voice-interface');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P160 Speech Governance');
  });

  it('preserves language detection and audit JSON helpers', () => {
    expect(SPEECH_CHUNK_MAX).toBeGreaterThan(0);
    expect(detectSpeechLang('Hello world')).toBe('en-US');
    expect(buildSpeechAuditJson('Hello speech')).toContain('en-US');
    const fallback = auditSpeechGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
