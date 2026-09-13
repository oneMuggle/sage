/**
 * R27-B: Prompt 模板管理面板测试（mock promptApi）
 *
 * - 列表渲染 / 空态
 * - 新建：表单填写 → create 调用形态
 * - 编辑：回填 → update 调用
 * - 删除：remove 调用
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PromptTemplatesTab } from '../PromptTemplatesTab';

const listMock = vi.fn();
const createMock = vi.fn();
const updateMock = vi.fn();
const removeMock = vi.fn();

vi.mock('../../../shared/api/promptApi', () => ({
  promptApi: {
    list: () => listMock(),
    create: (...args: unknown[]) => createMock(...args),
    update: (...args: unknown[]) => updateMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
  },
}));

const renderTab = () => render(<PromptTemplatesTab />);

describe('PromptTemplatesTab — R27-B', () => {
  beforeEach(() => {
    listMock.mockReset().mockResolvedValue([]);
    createMock.mockReset().mockResolvedValue({ id: 'pt-1' });
    updateMock.mockReset().mockResolvedValue({ id: 'pt-1' });
    removeMock.mockReset().mockResolvedValue(undefined);
  });

  it('空态提示', async () => {
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-empty')).toBeInTheDocument());
  });

  it('列表渲染模板卡片', async () => {
    listMock.mockResolvedValue([
      {
        id: 'pt-1',
        name: '周报模板',
        description: '写周报',
        content: '写周报：{{内容}}',
        created_at: 1,
        updated_at: 1,
      },
    ]);
    renderTab();
    await waitFor(() => expect(screen.getAllByTestId('prompts-item')).toHaveLength(1));
    expect(screen.getByText('周报模板')).toBeInTheDocument();
    expect(screen.getByText(/写周报：/)).toBeInTheDocument();
  });

  it('新建：填写表单 → create 调用形态正确', async () => {
    renderTab();
    fireEvent.click(screen.getByTestId('prompts-new'));
    fireEvent.change(screen.getByTestId('prompts-form-name'), { target: { value: '新模板' } });
    fireEvent.change(screen.getByTestId('prompts-form-desc'), { target: { value: '描述' } });
    fireEvent.change(screen.getByTestId('prompts-form-content'), {
      target: { value: '内容 {{变量}}' },
    });
    fireEvent.click(screen.getByTestId('prompts-form-save'));

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith('新模板', '内容 {{变量}}', '描述'),
    );
  });

  it('编辑：回填表单 → update 调用', async () => {
    listMock.mockResolvedValue([
      {
        id: 'pt-9',
        name: '旧名',
        description: '',
        content: '旧内容',
        created_at: 1,
        updated_at: 1,
      },
    ]);
    renderTab();
    await waitFor(() => expect(screen.getAllByTestId('prompts-item')).toHaveLength(1));

    fireEvent.click(screen.getByTestId('prompts-edit-pt-9'));
    const nameInput = screen.getByTestId('prompts-form-name') as HTMLInputElement;
    expect(nameInput.value).toBe('旧名');

    fireEvent.change(nameInput, { target: { value: '新名' } });
    fireEvent.click(screen.getByTestId('prompts-form-save'));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith('pt-9', {
        name: '新名',
        description: '',
        content: '旧内容',
      }),
    );
  });

  it('删除：remove 调用并刷新列表', async () => {
    listMock
      .mockResolvedValueOnce([
        {
          id: 'pt-1',
          name: '临时',
          description: '',
          content: 'c',
          created_at: 1,
          updated_at: 1,
        },
      ])
      .mockResolvedValue([]);
    renderTab();
    await waitFor(() => expect(screen.getAllByTestId('prompts-item')).toHaveLength(1));

    fireEvent.click(screen.getByTestId('prompts-delete-pt-1'));
    await waitFor(() => {
      expect(removeMock).toHaveBeenCalledWith('pt-1');
      expect(listMock).toHaveBeenCalledTimes(2);
    });
  });

  it('加载失败展示错误条', async () => {
    listMock.mockRejectedValue(new Error('后端未起'));
    renderTab();
    await waitFor(() => expect(screen.getByTestId('prompts-error')).toHaveTextContent('后端未起'));
  });
});
