import { describe, expect, it } from 'vitest';

import { auditWelcomeHeroGovernance } from '../WelcomeHero';

describe('auditWelcomeHeroGovernance (Phase P191)', () => {
  it('returns deterministic P191 governance audit payload', () => {
    const payload = JSON.parse(auditWelcomeHeroGovernance()) as Record<string, unknown>;
    expect(payload.module).toBe('welcome-hero');
    expect(payload.phase).toBe('P191');
    expect(payload.audited).toBe(true);
  });
});
