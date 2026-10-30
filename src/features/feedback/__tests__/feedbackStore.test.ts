// src/features/feedback/__tests__/feedbackStore.test.ts
//
// Phase 1.10：反馈 store 的列表拉取、详情缓存、发起会话、追加消息、
// 状态更新、手动同步与错误落盘。

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../shared/api/feedbackApi', () => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  createConversation: vi.fn(),
  appendMessage: vi.fn(),
  updateConversationStatus: vi.fn(),
  fetchLogTail: vi.fn(),
  syncNow: vi.fn(),
}));

import * as feedbackApi from '../../../shared/api/feedbackApi';
import { buildFeedbackStoreAuditSnapshot, useFeedbackStore } from '../feedbackStore';

const mockList = vi.mocked(feedbackApi.listConversations);
const mockGet = vi.mocked(feedbackApi.getConversation);
const mockCreate = vi.mocked(feedbackApi.createConversation);
const mockAppend = vi.mocked(feedbackApi.appendMessage);
const mockSetStatus = vi.mocked(feedbackApi.updateConversationStatus);
const mockLogTail = vi.mocked(feedbackApi.fetchLogTail);
const mockSync = vi.mocked(feedbackApi.syncNow);

const conversation = {
  id: 'c-0001',
  title: '导出 PDF 乱码',
  status: 'open',
  tag: 'other',
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

beforeEach(() => {
  vi.clearAllMocks();
  useFeedbackStore.getState().reset();
});

describe('feedbackStore.refreshList', () => {
  it('拉取会话列表并写入 state', async () => {
    mockList.mockResolvedValue([conversation]);
    await useFeedbackStore.getState().refreshList();
    expect(mockList).toHaveBeenCalledWith(50);
    expect(useFeedbackStore.getState().conversations).toHaveLength(1);
    expect(useFeedbackStore.getState().errors.list).toBeNull();
  });

  it('加载中重复调用只发一次请求', async () => {
    mockList.mockImplementation(
      () => new Promise((res) => setTimeout(() => res([conversation]), 10)),
    );
    await Promise.all([
      useFeedbackStore.getState().refreshList(),
      useFeedbackStore.getState().refreshList(),
    ]);
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('失败写入 errors.list', async () => {
    mockList.mockRejectedValue(new Error('network down'));
    await useFeedbackStore.getState().refreshList();
    expect(useFeedbackStore.getState().errors.list).toBe('network down');
    expect(useFeedbackStore.getState().loading.list).toBe(false);
  });
});

describe('feedbackStore.openConversation', () => {
  it('首次打开拉详情并缓存', async () => {
    mockGet.mockResolvedValue(detail);
    await useFeedbackStore.getState().openConversation('c-0001');
    expect(mockGet).toHaveBeenCalledWith('c-0001');
    expect(useFeedbackStore.getState().currentId).toBe('c-0001');
    expect(useFeedbackStore.getState().detailById['c-0001']).toEqual(detail);
  });

  it('二次打开命中缓存不重拉', async () => {
    useFeedbackStore.setState({
      detailById: { 'c-0001': detail },
      currentId: null,
    });
    await useFeedbackStore.getState().openConversation('c-0001');
    expect(mockGet).not.toHaveBeenCalled();
    expect(useFeedbackStore.getState().currentId).toBe('c-0001');
  });
});

describe('feedbackStore.createAndOpen', () => {
  it('创建后插入列表头部并自动打开', async () => {
    mockCreate.mockResolvedValue(conversation);
    mockGet.mockResolvedValue(detail);
    const id = await useFeedbackStore.getState().createAndOpen({
      title: '导出 PDF 乱码',
      body: '导出后中文变乱码',
    });
    expect(id).toBe('c-0001');
    expect(useFeedbackStore.getState().conversations[0].id).toBe('c-0001');
    expect(useFeedbackStore.getState().currentId).toBe('c-0001');
  });

  it('创建失败返回 null 并写 submit 错误', async () => {
    mockCreate.mockRejectedValue(new Error('backend 500'));
    const id = await useFeedbackStore.getState().createAndOpen({
      title: 't',
      body: 'b',
    });
    expect(id).toBeNull();
    expect(useFeedbackStore.getState().errors.submit).toBe('backend 500');
  });
});

describe('feedbackStore.sendMessage', () => {
  it('追加到已缓存详情并推进 last_activity_at', async () => {
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
    const ok = await useFeedbackStore.getState().sendMessage({ body: '补充说明' });
    expect(ok).toBe(true);
    const messages = useFeedbackStore.getState().detailById['c-0001'].messages;
    expect(messages).toHaveLength(2);
    expect(messages[1].body).toBe('补充说明');
    expect(messages[1].created_at).toBe(1730215000000);
    expect(useFeedbackStore.getState().conversations[0].last_activity_at).toBe(1730215000000);
  });

  it('无当前会话时直接返回 false', async () => {
    const ok = await useFeedbackStore.getState().sendMessage({ body: 'x' });
    expect(ok).toBe(false);
    expect(mockAppend).not.toHaveBeenCalled();
  });

  it('发送失败写入 submit 错误', async () => {
    useFeedbackStore.setState({
      detailById: { 'c-0001': detail },
      currentId: 'c-0001',
    });
    mockAppend.mockRejectedValue(new Error('offline'));
    const ok = await useFeedbackStore.getState().sendMessage({ body: 'x' });
    expect(ok).toBe(false);
    expect(useFeedbackStore.getState().errors.submit).toBe('offline');
    expect(useFeedbackStore.getState().loading.send).toBe(false);
  });
});

describe('feedbackStore.setStatus', () => {
  it('同步更新列表与详情中的 status', async () => {
    useFeedbackStore.setState({
      conversations: [conversation],
      detailById: { 'c-0001': detail },
    });
    mockSetStatus.mockResolvedValue();
    const ok = await useFeedbackStore.getState().setStatus('c-0001', 'resolved');
    expect(ok).toBe(true);
    expect(useFeedbackStore.getState().conversations[0].status).toBe('resolved');
    expect(useFeedbackStore.getState().detailById['c-0001'].conversation.status).toBe('resolved');
  });
});

describe('feedbackStore.triggerSync', () => {
  it('记录同步统计并刷新列表', async () => {
    useFeedbackStore.setState({ currentId: null });
    mockSync.mockResolvedValue({ submitted: 1, received: 2, errors: 0 });
    mockList.mockResolvedValue([conversation]);
    await useFeedbackStore.getState().triggerSync();
    expect(useFeedbackStore.getState().syncStats).toEqual({
      submitted: 1,
      received: 2,
      errors: 0,
    });
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(useFeedbackStore.getState().loading.sync).toBe(false);
  });
});

describe('feedbackStore.refreshLogTail', () => {
  it('写入日志尾部文本', async () => {
    mockLogTail.mockResolvedValue({ text: 'line-1\nline-2', lines: ['line-1', 'line-2'] });
    await useFeedbackStore.getState().refreshLogTail();
    expect(useFeedbackStore.getState().logTail).toBe('line-1\nline-2');
  });
});

describe('feedbackStore 审计快照', () => {
  it('统计会话 / 详情缓存 / 错误数', () => {
    const snap = buildFeedbackStoreAuditSnapshot({
      conversations: [conversation],
      detailById: { 'c-0001': detail },
      currentId: 'c-0001',
    });
    expect(snap.conversationCount).toBe(1);
    expect(snap.cachedDetailCount).toBe(1);
    expect(snap.currentId).toBe('c-0001');
    expect(snap.errorCount).toBe(0);
    expect(snap.signature).toBe('1|1|c-0001|false|0|0');
  });
});
