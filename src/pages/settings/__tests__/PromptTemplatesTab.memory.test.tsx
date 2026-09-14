/**
 * R38: 模板管理面板变量记忆区块测试
 *
 * - 有记忆值时展示"记忆 N 项"与清除按钮
 * - 清除后 localStorage 键被移除、区块消失
 * - 无记忆时不展示区块
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { PromptTemplatesTab } from '../PromptTemplatesTab';

const listMock = vi.fn();

vi.mock('../../../shared/api/promptApi', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/promptApi')>(
    '../../../shared/api/promptApi',
  );
  return {
    ...actual,
    promptApi: {
      ...actual.promptApi,
      list: () => listMock(),
    },
  };
});

import { tplStorageKey } from '../../../widgets/chat/TemplateFillDialog';

const TPL = {
  id: 'pt-1',
  name: '周报模板',
  description: '',
  content: '写周报：{{内容}} 截止 {{截止日}}',
  created_at: 1,
  updated_at: 1,
};

const renderTab = () => render(<I18nProvider defaultLocale="zh"><PromptTemplatesTab /></I18nProvider>);

describe('PromptTemplatesTab — R38 变量记忆管理', () => {
  beforeEach(() => {
    listMock.mockReset().mockResolvedValue([TPL]);
    Object.keys(localStorage)
      .filter((k) => k.startsWith('sage:tplfill:'))
      .forEach((k) => localStorage.removeItem(k));
  });

  it('有记忆值时展示记忆区块与清除按钮', async () => {
    localStorage.setItem(tplStorageKey(TPL.content), JSON.stringify({ 内容: '进展A' }));
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-memory-pt-1')).toHaveTextContent('记忆 1 项'));
    expect(screen.getByTestId('prompts-memory-clear-pt-1')).toBeInTheDocument();
  });

  it('点击清除后 localStorage 键被移除且区块消失', async () => {
    localStorage.setItem(tplStorageKey(TPL.content), JSON.stringify({ 内容: '进展A' }));
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-memory-clear-pt-1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('prompts-memory-clear-pt-1'));
    await waitFor(() => expect(screen.queryByTestId('prompts-memory-pt-1')).not.toBeInTheDocument());
    expect(localStorage.getItem(tplStorageKey(TPL.content))).toBeNull();
  });

  it('无记忆时不展示记忆区块', async () => {
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-item')).toBeInTheDocument());
    expect(screen.queryByTestId('prompts-memory-pt-1')).not.toBeInTheDocument();
  });
});
