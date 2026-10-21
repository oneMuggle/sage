import { describe, expect, it } from 'vitest';

import {
  formatResizablePanelSummary,
  formatResizablePanelJson,
} from '../useResizablePanel';

describe('useResizablePanel audit helpers', () => {
  it('clamps width and formats resizable panel summary and json', () => {
    expect(formatResizablePanelSummary(360, 280, 600, 'right', false)).toBe(
      'width=360px · range=[280,600] · anchor=right · dragging=false',
    );
    const parsed = JSON.parse(formatResizablePanelJson(750, 280, 600, 'left', true));
    expect(parsed).toEqual({
      width: 600,
      minWidth: 280,
      maxWidth: 600,
      anchor: 'left',
      isDragging: true,
    });
  });

  it('falls back to minWidth when width is nullish', () => {
    expect(formatResizablePanelSummary(null, 240, 500)).toBe(
      'width=240px · range=[240,500] · anchor=right · dragging=false',
    );
    expect(JSON.parse(formatResizablePanelJson(undefined, 240, 500)).width).toBe(240);
  });
});
