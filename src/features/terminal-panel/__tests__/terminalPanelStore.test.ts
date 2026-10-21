import { describe, expect, it } from 'vitest';

import {
  DEFAULT_HEIGHT,
  formatTerminalPanelSummary,
  formatTerminalPanelJson,
} from '../terminalPanelStore';

describe('terminalPanelStore audit helpers', () => {
  it('formats terminal panel summary and json snapshot', () => {
    const state = {
      open: true,
      height: 320,
      ptyId: 'pty-42',
      ptyError: null,
    };
    expect(formatTerminalPanelSummary(state)).toBe(
      'panel=open · height=320px · pty=pty-42 · error=false',
    );
    const parsed = JSON.parse(formatTerminalPanelJson(state));
    expect(parsed).toEqual({
      open: true,
      height: 320,
      ptyId: 'pty-42',
      ptyError: null,
    });
  });

  it('handles closed or error states safely', () => {
    expect(formatTerminalPanelSummary({ open: false, ptyError: 'spawn failed' })).toBe(
      `panel=closed · height=${DEFAULT_HEIGHT}px · pty=none · error=true`,
    );
    expect(JSON.parse(formatTerminalPanelJson(null)).height).toBe(DEFAULT_HEIGHT);
  });
});
