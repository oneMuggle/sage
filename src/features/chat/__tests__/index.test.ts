import { describe, expect, it } from 'vitest';

import {
  formatChatFeatureBarrelJson,
  formatChatFeatureBarrelSummary,
} from '../index';

describe('chat feature barrel audit helpers', () => {
  it('formats chat feature barrel summary', () => {
    expect(formatChatFeatureBarrelSummary()).toBe(
      'module=features/chat · exports=8 · includes=AtFileMenu,AtEntityMenu,BtwOverlay',
    );
  });

  it('exports chat feature barrel JSON snapshot', () => {
    const parsed = JSON.parse(formatChatFeatureBarrelJson());
    expect(parsed.module).toBe('features/chat');
    expect(parsed.exportCount).toBe(8);
  });
});

