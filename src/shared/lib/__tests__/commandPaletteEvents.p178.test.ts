import { describe, expect, it } from 'vitest';

import {
  auditCommandPaletteEventsGovernance,
  formatCommandPaletteEventJson,
  formatCommandPaletteEventSummary,
  OPEN_COMMAND_PALETTE_EVENT,
} from '../commandPaletteEvents';

describe('commandPaletteEvents P178 governance audit', () => {
  it('audits commandPaletteEvents governance contract and event formatters', () => {
    const raw = auditCommandPaletteEventsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.command_palette_events.governance.v1');
    expect(parsed.phase).toBe('P178');
    expect(parsed.eventName).toBe(OPEN_COMMAND_PALETTE_EVENT);
    expect(formatCommandPaletteEventSummary(true)).toContain('targetReady=true');
    expect(JSON.parse(formatCommandPaletteEventJson(true)).targetReady).toBe(true);
  });
});
