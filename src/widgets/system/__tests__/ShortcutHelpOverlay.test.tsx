// src/widgets/system/__tests__/ShortcutHelpOverlay.test.tsx
// U18 快捷键帮助覆盖层: open 门控 + Esc 关闭 + 注册表渲染。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { SHORTCUT_GROUPS } from '../../../shared/lib/shortcuts';
import { formatShortcutHelpJson, formatShortcutHelpMarkdown, ShortcutHelpOverlay } from '../ShortcutHelpOverlay';

describe('ShortcutHelpOverlay', () => {
  it('open=false 时不渲染', () => {
    render(<ShortcutHelpOverlay open={false} onClose={() => undefined} />);
    expect(screen.queryByTestId('shortcut-help-overlay')).toBeNull();
  });

  it('open=true 渲染注册表全部分组与条目', () => {
    render(<ShortcutHelpOverlay open onClose={() => undefined} />);
    expect(screen.getByTestId('shortcut-help-overlay')).toBeInTheDocument();
    for (const group of SHORTCUT_GROUPS) {
      expect(screen.getByText(group.group)).toBeInTheDocument();
      for (const item of group.items) {
        expect(screen.getByText(item.description)).toBeInTheDocument();
      }
    }
  });

  it('Esc 与背景点击触发 onClose;内容区点击不关闭', () => {
    const onClose = vi.fn();
    render(<ShortcutHelpOverlay open onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('shortcut-help-overlay'));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('dialog', { name: '快捷键帮助' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('exports Markdown and JSON and copies via buttons (Phase P91)', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ShortcutHelpOverlay open onClose={() => undefined} />);

    const md = formatShortcutHelpMarkdown(SHORTCUT_GROUPS);
    expect(md).toContain('# 键盘快捷键列表');
    const json = JSON.parse(formatShortcutHelpJson(SHORTCUT_GROUPS));
    expect(json.groupCount).toBe(SHORTCUT_GROUPS.length);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(md));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  });
});
