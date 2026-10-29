// @vitest-environment jsdom
//
// Phase 1.9：<FeedbackHub> 组件行为测试 —— 空列表提示、会话切换、
// 新建反馈、发送消息、截图体积拦截。

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/feedbackApi', () => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  createConversation: vi.fn(),
  appendMessage: vi.fn(),
  updateConversationStatus: vi.fn(),
  fetchLogTail: vi.fn(),
  searchMessages: vi.fn(),
  syncNow: vi.fn(),
  uploadAttachment: vi.fn(),
}));

import * as feedbackApi from '../../../shared/api/feedbackApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { FeedbackHub } from '../FeedbackHub';
import { useFeedbackStore } from '../feedbackStore';

const mockList = vi.mocked(feedbackApi.listConversations);
const mockGet = vi.mocked(feedbackApi.getConversation);
const mockCreate = vi.mocked(feedbackApi.createConversation);
const mockAppend = vi.mocked(feedbackApi.appendMessage);
const mockSearch = vi.mocked(feedbackApi.searchMessages);
const mockUpload = vi.mocked(feedbackApi.uploadAttachment);

const conversation = {
  id: 'c-0001',
  title: '导出 PDF 乱码',
  status: 'open',
  app_version: '0.4.9',
  os_info: 'Windows 10',
  remote_ticket_id: null,
  remote_ticket_url: null,
  last_activity_at: 1730214000000,
  created_at: 1730214000000,
  updated_at: 1730214000000,
};

const message = {
  id: 'm-0001',
  conversation_id: 'c-0001',
  role: 'user',
  body: '导出后中文变乱码',
  media_ids: [],
  created_at: 1730214000000,
  synced_at: null,
};

const detail = { conversation, messages: [message] };

function renderHub() {
  return render(
    <I18nProvider>
      <FeedbackHub />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useFeedbackStore.getState().reset();
  mockList.mockResolvedValue([]);
  mockSearch.mockResolvedValue([]);
});

describe('FeedbackHub', () => {
  it('空列表显示提示文案', async () => {
    renderHub();
    expect(await screen.findByText('暂无反馈')).toBeInTheDocument();
  });

  it('点击会话后加载并展示消息流', async () => {
    mockList.mockResolvedValue([conversation]);
    mockGet.mockResolvedValue(detail);
    renderHub();

    fireEvent.click(await screen.findByTestId('feedback-conversation-c-0001'));

    expect(await screen.findByText('导出后中文变乱码')).toBeInTheDocument();
    expect(screen.getByText('我')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('c-0001');
  });

  it('新建反馈提交后打开新会话', async () => {
    mockCreate.mockResolvedValue(conversation);
    mockGet.mockResolvedValue(detail);
    renderHub();

    fireEvent.click(screen.getByTestId('feedback-new'));
    fireEvent.change(screen.getByTestId('feedback-new-title'), {
      target: { value: '导出 PDF 乱码' },
    });
    fireEvent.change(screen.getByTestId('feedback-new-body'), {
      target: { value: '导出后中文变乱码' },
    });
    fireEvent.click(screen.getByTestId('feedback-new-submit'));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith(
        expect.objectContaining({ title: '导出 PDF 乱码', body: '导出后中文变乱码' }),
      ),
    );
    expect(await screen.findByTestId('feedback-message-stream')).toBeInTheDocument();
  });

  it('输入框发送消息后追加到消息流', async () => {
    useFeedbackStore.setState({
      conversations: [conversation],
      detailById: { 'c-0001': detail },
      currentId: 'c-0001',
    });
    mockAppend.mockResolvedValue({
      id: 'm-0002',
      conversation_id: 'c-0001',
      created_at: 1730215000000,
      received: true,
    });
    renderHub();

    fireEvent.change(screen.getByTestId('feedback-composer'), {
      target: { value: '补充说明' },
    });
    fireEvent.click(screen.getByTestId('feedback-send'));

    expect(await screen.findByText('补充说明')).toBeInTheDocument();
    expect(mockAppend).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: 'c-0001', body: '补充说明' }),
    );
  });

  it('超过 5MB 的截图被拦截且不上传', async () => {
    useFeedbackStore.setState({
      conversations: [conversation],
      detailById: { 'c-0001': detail },
      currentId: 'c-0001',
    });
    const { container } = renderHub();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const big = new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'big.png', {
      type: 'image/png',
    });
    fireEvent.change(input, { target: { files: [big] } });

    expect(await screen.findByText('截图不能超过 5MB')).toBeInTheDocument();
    expect(mockUpload).not.toHaveBeenCalled();
  });

  it('搜索命中后点击结果打开对应会话', async () => {
    mockList.mockResolvedValue([conversation]);
    mockGet.mockResolvedValue(detail);
    mockSearch.mockResolvedValue([
      {
        conversation_id: 'c-0001',
        conversation_title: '导出 PDF 乱码',
        message_id: 'm-0001',
        role: 'user',
        body: '导出后中文变乱码',
        created_at: 1730214000000,
      },
    ]);
    renderHub();

    fireEvent.change(screen.getByTestId('feedback-search'), { target: { value: '乱码' } });

    fireEvent.click(await screen.findByTestId('feedback-search-hit-m-0001'));

    expect(await screen.findByText('导出后中文变乱码')).toBeInTheDocument();
    expect(mockSearch).toHaveBeenCalledWith('乱码');
    expect(mockGet).toHaveBeenCalledWith('c-0001');
  });

  it('搜索无命中时显示空文案', async () => {
    renderHub();

    fireEvent.change(screen.getByTestId('feedback-search'), { target: { value: '找不到的词' } });

    expect(await screen.findByText('没有匹配的消息')).toBeInTheDocument();
  });
});
