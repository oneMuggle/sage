// @vitest-environment jsdom
/**
 * MemoryTab 回归钉测试:
 * - "同步到内部服务器" 死开关 (memoryServerSync, 后端已下线) 不得回流 UI。
 * - 不得硬编码展示 %APPDATA%\Sage\memory.db 路径。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MemoryTab } from '../MemoryTab';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

describe('MemoryTab', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    invokeMock.mockResolvedValue(null);
  });

  it('does not render the retired 同步到内部服务器 toggle', () => {
    render(<MemoryTab />);
    expect(screen.queryByText('同步到内部服务器')).toBeNull();
  });

  it('does NOT hardcode the %APPDATA%\\Sage\\memory.db path display', () => {
    const { container } = render(<MemoryTab />);

    expect(container.textContent).not.toContain('%APPDATA%');
    expect(container.textContent).not.toContain('Sage\\memory.db');

    const inputs = container.querySelectorAll('input');
    for (const input of inputs) {
      // R21: file input（导入记忆）没有 value 属性 —— null 视为通过
      const value = input.getAttribute('value');
      if (value !== null) {
        expect(value).not.toContain('%APPDATA%');
      }
    }
  });
});
