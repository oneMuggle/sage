/**
 * R27-A: Prompt 模板斜杠联动测试
 *
 * - mergePromptTemplates: 模板映射为 tpl-* 命令追加、空内容跳过
 * - 选中模板命令 → 填充输入框（不发送）
 * - /prompt-save → promptApi.create 调用链
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HelpCircle } from 'lucide-react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';
import { mergePromptTemplates } from '../slashCommands';

describe('mergePromptTemplates — R27-A 纯函数', () => {
  const base = [
    {
      name: 'help',
      label: '/help',
      description: '帮助',
      icon: HelpCircle,
      mode: 'help' as const,
    },
  ];

  it('模板映射为 tpl-* 命令追加在尾部', () => {
    const merged = mergePromptTemplates(base, [
      { name: '周报', content: '写周报：{{内容}}', description: '周报模板' },
    ]);
    expect(merged).toHaveLength(2);
    const tpl = merged[1];
    expect(tpl.name).toBe('tpl-周报');
    expect(tpl.mode).toBe('template');
    expect(tpl.content).toBe('写周报：{{内容}}');
  });

  it('空内容模板跳过', () => {
    const merged = mergePromptTemplates(base, [
      { name: 'a', content: '' },
      { name: 'b', content: 'ok' },
    ]);
    expect(merged.map((c) => c.name)).toEqual(['help', 'tpl-b']);
  });
});

const listMock = vi.fn();
const createMock = vi.fn();

vi.mock('../../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api')>(
    '../../../shared/api',
  );
  return {
    ...actual,
    promptApi: {
      list: (...args: unknown[]) => listMock(...args),
      create: (...args: unknown[]) => createMock(...args),
      update: vi.fn(),
      remove: vi.fn(),
    },
  };
});

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — R27-A 模板联动', () => {
  beforeEach(() => {
    listMock.mockReset();
    createMock.mockReset();
    createMock.mockResolvedValue({ id: 'pt-1', name: 'x', content: 'x' });
  });

  it('选中模板命令填充输入框且不发送', async () => {
    listMock.mockResolvedValue([{ name: '周报模板', content: '写周报：{{内容}}' }]);
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/tpl-周报模板' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /tpl-周报模板/ }));

    const input = screen.getByPlaceholderText(/输入消息/) as HTMLInputElement;
    expect(input.value).toBe('写周报：{{内容}}');
    expect(onSend).not.toHaveBeenCalled();
  });

  it('/prompt-save 把剩余文本存为模板', async () => {
    listMock.mockResolvedValue([]);
    const onSend = vi.fn();
    renderWithI18n(<ChatInput onSend={onSend} />);

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    fireEvent.change(screen.getByPlaceholderText(/输入消息/), {
      target: { value: '/prompt-save 帮我写一份测试用例覆盖登录流程' },
    });
    fireEvent.mouseDown(screen.getByRole('button', { name: /prompt-save/ }));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith(
        '帮我写一份测试用例覆盖登录流程'.slice(0, 24),
        '帮我写一份测试用例覆盖登录流程',
      ),
    );
    expect(onSend).not.toHaveBeenCalled();
  });
});
