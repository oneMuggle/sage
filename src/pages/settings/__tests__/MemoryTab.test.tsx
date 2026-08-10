// @vitest-environment jsdom
/**
 * MemoryTab — fix/security-perf-quickwins §1.3b f (2026-08-09)
 *
 * Bug history:
 * - "同步到内部服务器" toggle was wrongly bound to `settings.autoMemory`
 *   (which is actually the GeneralTab "自动记忆提取" toggle — same field,
 *   two different semantics).
 * - Storage path was hardcoded as `%APPDATA%\Sage\memory.db` even though
 *   the actual path depends on SAGE_DB_PATH / run mode.
 *
 * These tests pin both regressions so they don't silently come back.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type AppSettings } from '../../../entities/setting/types';
import { MemoryTab } from '../MemoryTab';
import type { EndpointsTabProps } from '../components';

function makeProps(overrides: Partial<AppSettings> = {}): EndpointsTabProps & {
  updateSettings: ReturnType<typeof vi.fn>;
} {
  const updateSettings = vi.fn();
  const settings: AppSettings = { ...DEFAULT_SETTINGS, ...overrides };
  return { settings, updateSettings } as EndpointsTabProps & {
    updateSettings: ReturnType<typeof vi.fn>;
  };
}

describe('MemoryTab (fix/security-perf-quickwins §1.3b f)', () => {
  it('renders the 同步到内部服务器 toggle bound to memoryServerSync, NOT autoMemory', () => {
    const props = makeProps({ autoMemory: true, memoryServerSync: false });
    render(<MemoryTab {...props} />);

    // SettingRow renders as: <div container><div label-container>{label}{desc}</div><div control-container>{children}</div></div>
    // Walk two levels up from the label to reach the SettingRow container,
    // then find the toggle button in the sibling control container.
    const labelEl = screen.getByText('同步到内部服务器');
    const settingRow = labelEl.parentElement!.parentElement!;
    const toggle = settingRow.querySelector('button');
    expect(toggle).not.toBeNull();

    // autoMemory=true (GeneralTab semantics) but the sync toggle is OFF.
    // Pre-fix this was wrongly tied to autoMemory, so the toggle would
    // render in the ON state here.
    expect(toggle!.className).toContain('bg-border');

    // Clicking it should update memoryServerSync, NOT autoMemory.
    fireEvent.click(toggle!);
    expect(props.updateSettings).toHaveBeenCalledWith({ memoryServerSync: true });
    const calls = props.updateSettings.mock.calls;
    for (const call of calls) {
      expect(call[0]).not.toHaveProperty('autoMemory');
    }
  });

  it('reflects the memoryServerSync value when already true (independent of autoMemory)', () => {
    const props = makeProps({ autoMemory: false, memoryServerSync: true });
    render(<MemoryTab {...props} />);

    const labelEl = screen.getByText('同步到内部服务器');
    const settingRow = labelEl.parentElement!.parentElement!;
    const toggle = settingRow.querySelector('button');
    // ON state — driven by memoryServerSync=true, despite autoMemory=false.
    expect(toggle!.className).toContain('bg-primary');
  });

  it('does NOT hardcode the %APPDATA%\\Sage\\memory.db path display', () => {
    const props = makeProps();
    const { container } = render(<MemoryTab {...props} />);

    // Old bug: there was a readOnly <input value="%APPDATA%\\Sage\\memory.db">.
    // New behavior: only a generic descriptive span. No string match for the
    // hardcoded path anywhere in the rendered tree.
    expect(container.textContent).not.toContain('%APPDATA%');
    expect(container.textContent).not.toContain('Sage\\memory.db');

    const inputs = container.querySelectorAll('input');
    for (const input of inputs) {
      expect(input.getAttribute('value')).not.toContain('%APPDATA%');
    }
  });
});