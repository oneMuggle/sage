// src/shared/lib/__tests__/fontScaleGate.test.ts
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('U3 font-scale ratchet gate (check-font-scale.mjs)', () => {
  it('passes with zero regressions and zero slack against font-scale-baseline.json', () => {
    const script = path.resolve(__dirname, '../../../../scripts/check-font-scale.mjs');
    const out = execFileSync(process.execPath, [script, '--max-slack=0'], {
      encoding: 'utf8',
    });
    expect(out).toContain('Font-scale check passed');
  });
});
