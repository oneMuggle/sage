// @vitest-environment jsdom
/**
 * MemoryTab 回归钉测试:
 * - "同步到内部服务器" 死开关 (memoryServerSync, 后端已下线) 不得回流 UI。
 * - 不得硬编码展示 %APPDATA%\Sage\memory.db 路径。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MemoryTab, formatMemoryTabAuditJson, formatMemoryTabAuditSnapshot } from '../MemoryTab';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryTab />
    </I18nProvider>,
  );
}

describe('MemoryTab', () => {
  beforeEach(() => {
    invokeMock.mockReset();
    invokeMock.mockResolvedValue(null);
  });

  it('does not render the retired 同步到内部服务器 toggle', () => {
    renderTab();
    expect(screen.queryByText('同步到内部服务器')).toBeNull();
  });

  it('does NOT hardcode the %APPDATA%\\Sage\\memory.db path display', () => {
    const { container } = renderTab();

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

  it('formats memory tab audit snapshot and JSON; copy controls moved to the audit export tab (P3)', () => {
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

    // P3: 页内「复制快照/JSON」按钮已收敛到「审计导出」tab —— MemoryTab 不再渲染这两枚按钮。
  });
});
