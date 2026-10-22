// @vitest-environment jsdom
/**
 * MemoryTab 回归钉测试:
 * - "同步到内部服务器" 死开关 (memoryServerSync, 后端已下线) 不得回流 UI。
 * - 不得硬编码展示 %APPDATA%\Sage\memory.db 路径。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MemoryTab,
  formatMemoryTabAuditJson,
  formatMemoryTabAuditSnapshot,
} from '../MemoryTab';

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

  it('formats and copies memory tab audit snapshot and JSON', () => {
    expect(
      formatMemoryTabAuditSnapshot({
        embedderType: 'onnx',
        semantic: true,
        modelReady: true,
        backupCount: 4,
      }),
    ).toBe('记忆管理 · onnx · 语义匹配 · 模型就绪 · 备份4份');
    expect(
      JSON.parse(
        formatMemoryTabAuditJson({
          embedderType: null,
          semantic: false,
          modelReady: false,
          backupCount: 0,
        }),
      ),
    ).toEqual({
      embedderType: null,
      semantic: false,
      modelReady: false,
      backupCount: 0,
    });

    render(<MemoryTab />);
    const summaryBtn = screen.getByTestId('memory-tab-copy-summary');
    const jsonBtn = screen.getByTestId('memory-tab-copy-json');
    fireEvent.click(summaryBtn);
    expect(summaryBtn.textContent).toBe('已复制');
    fireEvent.click(jsonBtn);
    expect(jsonBtn.textContent).toBe('已复制');
  });
});
