/**
 * CssThemeModal 单元测试
 *
 * 验证模态框的：
 * 1. 创建模式（无 initialTheme）
 * 2. 编辑模式（有 initialTheme）
 * 3. 保存/删除/取消按钮行为
 * 4. 名称校验
 * 5. 实时预览注入
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// jsdom 不实现 ResizeObserver，但 @headlessui Dialog 内部使用它
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// Mock CodeMirror 组件（jsdom 不支持 CodeMirror 6）
vi.mock('../CodeMirrorThemeEditor', () => ({
  CodeMirrorThemeEditor: ({
    value,
    onChange,
    error,
  }: {
    value: string;
    onChange: (v: string) => void;
    error?: string;
  }) => (
    <div data-testid="cm-editor-mock">
      <textarea
        data-testid="cm-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="css-editor"
      />
      {error && <span data-testid="cm-error">{error}</span>}
    </div>
  ),
}));

// Mock backgroundInjector
const injectPreviewMock = vi.fn();
vi.mock('../backgroundInjector', () => ({
  injectPreviewCss: (...args: unknown[]) => injectPreviewMock(...args),
  clearPreviewCss: vi.fn(),
  injectPersistedStyle: vi.fn(),
  removePersistedStyle: vi.fn(),
}));

import * as themeCssClientModule from '../../../shared/api/themeCssClient';
import { CssThemeModal } from '../CssThemeModal';
import type { ThemeCssPayload } from '../themeCssTypes';

// crypto.randomUUID shim for jsdom
if (!globalThis.crypto) {
  // @ts-expect-error test shim
  globalThis.crypto = {};
}
if (!globalThis.crypto.randomUUID) {
  globalThis.crypto.randomUUID = () => 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';
}

const VALID_CSS = ':root { --bg-base: #ffffff; --primary: #4f46e5; }';

const SAMPLE_THEME: ThemeCssPayload = {
  id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
  name: 'Existing Theme',
  css: VALID_CSS,
  appearance: 'light',
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let saveSpy: any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let deleteSpy: any;

beforeEach(() => {
  saveSpy = vi
    .spyOn(themeCssClientModule.themeCssClient, 'save')
    .mockResolvedValue({ id: 'test-id' });
  deleteSpy = vi.spyOn(themeCssClientModule.themeCssClient, 'delete').mockResolvedValue(undefined);
  injectPreviewMock.mockReset();
  // jsdom lacks confirm
  window.confirm = vi.fn(() => true);
});

describe('CssThemeModal', () => {
  describe('open=false', () => {
    it('renders nothing when open is false', () => {
      const { container } = render(
        <CssThemeModal open={false} onClose={vi.fn()} onSaved={vi.fn()} />,
      );
      expect(container.innerHTML).toBe('');
    });
  });

  describe('create mode', () => {
    it('renders with title "新建自定义主题"', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      expect(screen.getByText('新建自定义主题')).toBeInTheDocument();
    });

    it('shows name input and save/cancel buttons', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      expect(screen.getByLabelText('主题名称')).toBeInTheDocument();
      expect(screen.getByText('保存')).toBeInTheDocument();
      expect(screen.getByText('取消')).toBeInTheDocument();
    });

    it('does NOT show delete button in create mode', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      expect(screen.queryByText('删除')).not.toBeInTheDocument();
    });

    it('save button is disabled when name is empty', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      expect(screen.getByText('保存')).toBeDisabled();
    });

    it('save button is enabled when name is filled and CSS is valid', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      fireEvent.change(screen.getByLabelText('主题名称'), {
        target: { value: 'My Theme' },
      });
      // Default CSS template is valid (:root { ... })
      expect(screen.getByText('保存')).not.toBeDisabled();
    });

    it('save button is disabled when CSS is invalid', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      fireEvent.change(screen.getByLabelText('主题名称'), {
        target: { value: 'My Theme' },
      });
      // Make CSS invalid
      fireEvent.change(screen.getByLabelText('css-editor'), {
        target: { value: '.evil { --bg-base: red; }' },
      });
      expect(screen.getByText('保存')).toBeDisabled();
    });
  });

  describe('edit mode', () => {
    it('renders with theme name in title', () => {
      render(
        <CssThemeModal
          open={true}
          onClose={vi.fn()}
          initialTheme={SAMPLE_THEME}
          onSaved={vi.fn()}
        />,
      );
      expect(screen.getByText(/编辑主题/)).toBeInTheDocument();
    });

    it('pre-fills name from initialTheme', () => {
      render(
        <CssThemeModal
          open={true}
          onClose={vi.fn()}
          initialTheme={SAMPLE_THEME}
          onSaved={vi.fn()}
        />,
      );
      const nameInput = screen.getByLabelText('主题名称') as HTMLInputElement;
      expect(nameInput.value).toBe('Existing Theme');
    });

    it('shows delete button in edit mode', () => {
      render(
        <CssThemeModal
          open={true}
          onClose={vi.fn()}
          initialTheme={SAMPLE_THEME}
          onSaved={vi.fn()}
        />,
      );
      expect(screen.getByText('删除')).toBeInTheDocument();
    });
  });

  describe('save action', () => {
    it('calls themeCssClient.save when save button clicked', async () => {
      const onSaved = vi.fn();

      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={onSaved} />);

      // 填写名称（默认 CSS 模板已有效）
      const nameInput = screen.getByLabelText('主题名称');
      fireEvent.change(nameInput, { target: { value: 'Test Theme' } });

      // 点击保存
      const saveBtn = screen.getByRole('button', { name: '保存' });
      fireEvent.click(saveBtn);

      // 等待异步操作
      await vi.waitFor(
        () => {
          expect(saveSpy).toHaveBeenCalled();
        },
        { timeout: 2000 },
      );
    });

    it('calls onClose after successful save', async () => {
      const onClose = vi.fn();

      render(<CssThemeModal open={true} onClose={onClose} onSaved={vi.fn()} />);
      fireEvent.change(screen.getByLabelText('主题名称'), {
        target: { value: 'Test' },
      });

      fireEvent.click(screen.getByRole('button', { name: '保存' }));

      await vi.waitFor(
        () => {
          expect(onClose).toHaveBeenCalled();
        },
        { timeout: 2000 },
      );
    });
  });

  describe('cancel action', () => {
    it('calls onClose when cancel clicked', () => {
      const onClose = vi.fn();
      render(<CssThemeModal open={true} onClose={onClose} onSaved={vi.fn()} />);
      fireEvent.click(screen.getByText('取消'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('delete action', () => {
    it('calls themeCssClient.delete when delete button clicked', async () => {
      const onClose = vi.fn();

      render(
        <CssThemeModal
          open={true}
          onClose={onClose}
          initialTheme={SAMPLE_THEME}
          onSaved={vi.fn()}
        />,
      );

      // 点击删除
      fireEvent.click(screen.getByRole('button', { name: '删除' }));

      // 等待异步操作
      await vi.waitFor(
        () => {
          expect(deleteSpy).toHaveBeenCalled();
        },
        { timeout: 2000 },
      );
    });
  });

  describe('real-time preview', () => {
    it('calls injectPreviewCss when CSS changes', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      // Initial render should trigger preview injection
      // (default template is valid)
      fireEvent.change(screen.getByLabelText('css-editor'), {
        target: { value: ':root { --bg-base: #ff0000; }' },
      });
      expect(injectPreviewMock).toHaveBeenCalledWith(':root { --bg-base: #ff0000; }');
    });
  });

  describe('cover image upload', () => {
    it('shows cover upload input', () => {
      render(<CssThemeModal open={true} onClose={vi.fn()} onSaved={vi.fn()} />);
      expect(screen.getByLabelText(/封面图/)).toBeInTheDocument();
    });
  });
});
