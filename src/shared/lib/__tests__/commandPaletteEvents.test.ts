import { describe, expect, it, vi } from 'vitest';

import {
  OPEN_COMMAND_PALETTE_EVENT,
  formatCommandPaletteEventJson,
  formatCommandPaletteEventSummary,
  requestOpenCommandPalette,
} from '../commandPaletteEvents';

describe('commandPaletteEvents audit diagnostics', () => {
  it('dispatches open event and formats summary', () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_COMMAND_PALETTE_EVENT, listener);
    requestOpenCommandPalette();
    window.removeEventListener(OPEN_COMMAND_PALETTE_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(formatCommandPaletteEventSummary(true)).toBe(
      'event=sage:command-palette:open · targetReady=true',
    );
    expect(formatCommandPaletteEventSummary(false)).toBe(
      'event=sage:command-palette:open · targetReady=false',
    );
  });

  it('serializes command palette event audit JSON', () => {
    const parsed = JSON.parse(formatCommandPaletteEventJson(true));
    expect(parsed).toEqual({
      eventName: 'sage:command-palette:open',
      targetReady: true,
    });
  });
});
