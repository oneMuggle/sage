import { describe, expect, it } from 'vitest';

import {
  formatResizableSidebarSummary,
  formatResizableSidebarJson,
} from '../useResizableSidebar';

describe('useResizableSidebar audit helpers', () => {
  it('formats resizable sidebar summary and json', () => {
    expect(formatResizableSidebarSummary(280, false)).toBe(
      'sidebar=280px · range=[260,480] · dragging=false',
    );
    const parsed = JSON.parse(formatResizableSidebarJson(600, true));
    expect(parsed).toEqual({
      width: 480,
      minWidth: 260,
      maxWidth: 480,
      defaultWidth: 300,
      isDragging: true,
    });
  });

  it('falls back to default width when nullish', () => {
    expect(formatResizableSidebarSummary(null)).toBe(
      'sidebar=300px · range=[260,480] · dragging=false',
    );
    expect(JSON.parse(formatResizableSidebarJson(undefined)).width).toBe(300);
  });
});
