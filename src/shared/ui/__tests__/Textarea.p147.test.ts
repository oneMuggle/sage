import { describe, expect, it } from 'vitest';

import { auditTextareaGovernance } from '../Textarea';

describe('Textarea P147 governance audit', () => {
  it('returns healthy defaults for Textarea governance', () => {
    const res = auditTextareaGovernance();
    expect(res.module).toBe('src/shared/ui/Textarea.tsx');
    expect(res.phase).toBe('P147');
    expect(res.rows).toBe(3);
    expect(res.disabled).toBe(false);
    expect(res.healthy).toBe(true);
  });

  it('clamps rows and normalizes disabled flag', () => {
    const res = auditTextareaGovernance({
      rows: 99,
      disabled: true,
    });
    expect(res.rows).toBe(40);
    expect(res.disabled).toBe(true);
    expect(res.healthy).toBe(true);
  });
});
