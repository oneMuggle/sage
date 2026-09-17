/**
 * R38: 模板管理面板变量记忆区块测试
 *
 * - 有记忆值时展示"记忆 N 项"与清除按钮
 * - 清除后 localStorage 键被移除、区块消失
 * - 无记忆时不展示区块
 * r56: 失联条目管理 —— 模板已改/删后残留键的展示与清理
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { listTplMemoryEntries, tplStorageKey } from '../../../widgets/chat/TemplateFillDialog';
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

  // ==== r56: 失联条目管理 ====

  it('失联键进失联区块，绑定键不进；单条删除只删失联键', async () => {
    const orphanKey = tplStorageKey('已被编辑掉的旧内容');
    localStorage.setItem(tplStorageKey(TPL.content), JSON.stringify({ 内容: '绑定值' }));
    localStorage.setItem(orphanKey, JSON.stringify({ 内容: '失联值' }));

    renderTab();
    await waitFor(() => expect(screen.getByTestId('tplmem-orphans')).toBeInTheDocument());
    // 只列失联键（短哈希 # 开头），绑定键不出现在失联区块
    const orphanHash = orphanKey.slice('sage:tplfill:'.length);
    expect(screen.getByTestId(`tplmem-orphan-remove-${orphanHash}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`tplmem-orphan-remove-${tplStorageKey(TPL.content).slice('sage:tplfill:'.length)}`)).not.toBeInTheDocument();
    expect(screen.getByText(/失联值/)).toBeInTheDocument();

    // 单条删除：失联键消失，绑定键保留，区块随之消失
    fireEvent.click(screen.getByTestId(`tplmem-orphan-remove-${orphanHash}`));
    await waitFor(() =>
      expect(screen.queryByTestId('tplmem-orphans')).not.toBeInTheDocument(),
    );
    expect(localStorage.getItem(orphanKey)).toBeNull();
    expect(localStorage.getItem(tplStorageKey(TPL.content))).not.toBeNull();
  });

  it('全部清除：失联键全清，绑定键保留', async () => {
    localStorage.setItem(tplStorageKey(TPL.content), JSON.stringify({ 内容: '绑定值' }));
    localStorage.setItem(tplStorageKey('旧内容A'), JSON.stringify({ a: '1' }));
    localStorage.setItem(tplStorageKey('旧内容B'), JSON.stringify({ b: '2' }));

    renderTab();
    await waitFor(() => expect(screen.getByTestId('tplmem-orphan-clear-all')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('tplmem-orphan-clear-all'));

    await waitFor(() =>
      expect(screen.queryByTestId('tplmem-orphans')).not.toBeInTheDocument(),
    );
    expect(localStorage.getItem(tplStorageKey('旧内容A'))).toBeNull();
    expect(localStorage.getItem(tplStorageKey('旧内容B'))).toBeNull();
    expect(localStorage.getItem(tplStorageKey(TPL.content))).not.toBeNull();
  });

  it('无失联条目时不渲染失联区块；扫描辅助函数与键口径一致', async () => {
    localStorage.setItem(tplStorageKey(TPL.content), JSON.stringify({ 内容: '绑定值' }));
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-item')).toBeInTheDocument());
    expect(screen.queryByTestId('tplmem-orphans')).not.toBeInTheDocument();

    // 扫描辅助函数：只收 sage:tplfill: 前缀，且能读出结构化值
    const entries = listTplMemoryEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].values).toEqual({ 内容: '绑定值' });
    expect(localStorage.getItem(entries[0].key)).not.toBeNull();
  });
});
