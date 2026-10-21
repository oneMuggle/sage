import { describe, expect, it } from 'vitest';

import {
  confirmDialog,
  resolveConfirm,
  formatConfirmServiceSummary,
  formatConfirmServiceJson,
} from '../confirmService';

describe('confirmService audit helpers', () => {
  it('tracks active confirm dialog and formats summary and json', async () => {
    const p = confirmDialog({ title: 'Delete project?', danger: true });
    expect(formatConfirmServiceSummary()).toBe('pending=true · danger=true · listeners=0');
    const parsed = JSON.parse(formatConfirmServiceJson());
    expect(parsed).toEqual({
      pending: true,
      title: 'Delete project?',
      danger: true,
      listenerCount: 0,
    });
    resolveConfirm(true);
    await expect(p).resolves.toBe(true);
  });

  it('handles idle state and explicit nullish options safely', () => {
    expect(formatConfirmServiceSummary(null)).toBe('pending=false · danger=false · listeners=0');
    expect(JSON.parse(formatConfirmServiceJson(null)).pending).toBe(false);
  });
});
