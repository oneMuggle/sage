// @vitest-environment jsdom
/**
 * P3 §4.4：显式保存卡片补 dirty 提示。
 *
 * 三处保留「保存」按钮的卡片（附件检索 / 端点 / 全局规则）中，前两处原本
 * 按钮永远可点、改动与否毫无提示 —— 用户既不知道自己有没有改过，也不知道
 * 切走会不会丢草稿。本文件锁住两条行为：保存按钮跟着 dirty 走，切走前提示。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type AppSettings } from '../../../entities/setting/types';
import { ATTACHMENT_RAG_STORAGE_KEY } from '../../../shared/api/attachmentRagConfig';
import { I18nProvider } from '../../../shared/lib/i18n';
import { AttachmentRagCard } from '../AttachmentRagCard';
import { EndpointsTab } from '../EndpointsTab';
import type { EndpointsTabProps } from '../components';

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn(async () => ({
    success: true,
    message: 'mocked',
    latency: 0,
    discoveredModels: [],
  })),
  probeModel: vi.fn(async () => ({ status: 'ok', adapter: 'unknown', data: null })),
}));

beforeEach(() => {
  localStorage.clear();
});

describe('AttachmentRagCard dirty 提示', () => {
  function renderCard() {
    return render(
      <I18nProvider defaultLocale="zh">
        <AttachmentRagCard />
      </I18nProvider>,
    );
  }

  it('未改动时「保存」不可点、不显示未保存提示', () => {
    renderCard();
    expect(screen.getByTestId('attachment-rag-save')).toBeDisabled();
    expect(screen.queryByTestId('attachment-rag-unsaved')).toBeNull();
  });

  it('改动后显示未保存提示并放开保存；保存后回到干净状态', () => {
    renderCard();
    fireEvent.click(screen.getByRole('switch'));
    const save = screen.getByTestId('attachment-rag-save');
    expect(save).toBeEnabled();
    expect(screen.getByTestId('attachment-rag-unsaved')).toBeInTheDocument();

    fireEvent.click(save);
    expect(screen.queryByTestId('attachment-rag-unsaved')).toBeNull();
    expect(screen.getByTestId('attachment-rag-saved')).toBeInTheDocument();
    expect(screen.getByTestId('attachment-rag-save')).toBeDisabled();
    // 落盘后 localStorage 应持有新值，而不是渲染期的初始值。
    expect(JSON.parse(localStorage.getItem(ATTACHMENT_RAG_STORAGE_KEY) ?? '{}')).toMatchObject({
      enabled: true,
    });
  });

  it('改回原值时 dirty 自动消失 —— 不需要用户先保存一次才能清提示', () => {
    renderCard();
    const toggle = screen.getByRole('switch');
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(screen.queryByTestId('attachment-rag-unsaved')).toBeNull();
    expect(screen.getByTestId('attachment-rag-save')).toBeDisabled();
  });
});

describe('EndpointsTab dirty 提示', () => {
  function makeProps(): EndpointsTabProps {
    const settings: AppSettings = {
      ...DEFAULT_SETTINGS,
      endpoints: [
        {
          id: 'ep1',
          name: 'LM Studio',
          baseUrl: 'http://127.0.0.1:1234/v1',
          apiKey: '',
          protocol: 'openai-compatible',
          modelId: 'qwen2.5-7b-instruct',
          localModelPath: '',
          discoveredModels: [],
          lastDiscoveredAt: 0,
        },
        {
          id: 'ep2',
          name: 'Backup',
          baseUrl: 'https://api.example.com/v1',
          apiKey: 'sk-test',
          protocol: 'openai-compatible',
          modelId: 'gpt-4o-mini',
          localModelPath: '',
          discoveredModels: [],
          lastDiscoveredAt: 0,
        },
      ],
    };
    return { settings, updateSettings: vi.fn() } as EndpointsTabProps;
  }

  function renderTab(props: EndpointsTabProps) {
    return render(
      <I18nProvider defaultLocale="zh">
        <EndpointsTab {...props} />
      </I18nProvider>,
    );
  }

  it('刚打开编辑器时「保存」不可点，改动后出现未保存提示', () => {
    renderTab(makeProps());
    fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0]);
    const save = screen.getByRole('button', { name: '保存' });
    expect(save).toBeDisabled();
    expect(screen.queryByTestId('endpoint-unsaved-ep1')).toBeNull();

    fireEvent.change(screen.getByDisplayValue('LM Studio'), { target: { value: 'LM Studio 2' } });
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled();
    expect(screen.getByTestId('endpoint-unsaved-ep1')).toBeInTheDocument();
  });

  it('草稿未保存时切到另一个端点会先确认；取消则留在原编辑器', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    try {
      renderTab(makeProps());
      fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0]);
      fireEvent.change(screen.getByDisplayValue('LM Studio'), { target: { value: 'LM Studio 2' } });

      fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0]);
      expect(confirmSpy).toHaveBeenCalled();
      // 拒绝放弃 → 草稿保留在原编辑器中
      expect(screen.getByDisplayValue('LM Studio 2')).toBeInTheDocument();
      expect(screen.queryByDisplayValue('Backup')).toBeNull();
    } finally {
      confirmSpy.mockRestore();
    }
  });

  it('无改动时切换编辑器不会打扰用户', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    try {
      renderTab(makeProps());
      fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0]);
      // 未改动 → 第二行仍是「编辑」，点它应直接切过去，不弹确认
      fireEvent.click(screen.getAllByRole('button', { name: '编辑' })[0]);
      expect(confirmSpy).not.toHaveBeenCalled();
      expect(screen.getByDisplayValue('Backup')).toBeInTheDocument();
    } finally {
      confirmSpy.mockRestore();
    }
  });
});
