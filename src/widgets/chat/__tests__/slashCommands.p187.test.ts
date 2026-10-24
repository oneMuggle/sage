import { describe, expect, it } from 'vitest';

import { auditSlashCommandsGovernance } from '../slashCommands';

describe('auditSlashCommandsGovernance (Phase P187)', () => {
  it('returns deterministic P187 governance audit payload', () => {
    const payload = JSON.parse(auditSlashCommandsGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('slash-commands');
    expect(payload.phase).toBe('P187');
    expect(payload.audited).toBe(true);
  });
});
