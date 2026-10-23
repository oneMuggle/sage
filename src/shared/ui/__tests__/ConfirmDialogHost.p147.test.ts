import { describe, expect, it } from 'vitest';

import { auditConfirmDialogHostGovernance } from '../ConfirmDialog/ConfirmDialogHost';

describe('ConfirmDialogHost P147 governance audit', () => {
  it('returns healthy defaults for ConfirmDialogHost governance', () => {
    const res = auditConfirmDialogHostGovernance();
    expect(res.module).toBe('src/shared/ui/ConfirmDialog/ConfirmDialogHost.tsx');
    expect(res.phase).toBe('P147');
    expect(res.open).toBe(false);
    expect(res.variant).toBe('default');
    expect(res.healthy).toBe(true);
  });

  it('normalizes open flag and danger variant', () => {
    const res = auditConfirmDialogHostGovernance({
      open: true,
      variant: 'danger',
    });
    expect(res.open).toBe(true);
    expect(res.variant).toBe('danger');
    expect(res.healthy).toBe(true);
  });
});
