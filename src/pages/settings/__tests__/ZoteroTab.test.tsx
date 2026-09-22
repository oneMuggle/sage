/**
 * r98: ZoteroTab UI 测试——状态卡片/路径保存/防抖搜索/详情批注展开。
 *
 * zoteroClient 以 vi.mock 替身注入；i18n 用真实 zh 文案断言
 * （'检测中…' / '已连接' / '未连接' / '保存路径' / '路径已保存'）。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const statusMock = vi.fn();
const listCollectionsMock = vi.fn();
const searchMock = vi.fn();
const getItemMock = vi.fn();
const getAnnotationsMock = vi.fn();
const setPathMock = vi.fn();

vi.mock('../../../shared/api/zoteroClient', () => ({
  zoteroClient: {
    status: (...args: unknown[]) => statusMock(...args),
    listCollections: (...args: unknown[]) => listCollectionsMock(...args),
    search: (...args: unknown[]) => searchMock(...args),
    getItem: (...args: unknown[]) => getItemMock(...args),
    getAnnotations: (...args: unknown[]) => getAnnotationsMock(...args),
    setPath: (...args: unknown[]) => setPathMock(...args),
  },
}));

import { ZoteroTab } from '../ZoteroTab';
import { I18nProvider } from '../../../shared/lib/i18n';

function availableStatus() {
  return {
    available: true,
    db_path: 'C:/zotero/zotero.sqlite',
    error: null,
    stats: { items: 10, collections: 2, tags: 5, attachments: 3 },
  };
}

const COLLECTION = { key: 'CK1', name: 'Root', parent_key: null, item_count: 4, version: 7 };
const SUMMARY = {
  key: 'ITEM1', title: '一篇论文', item_type: 'journalArticle', year: 2024,
  authors: ['作者甲'], abstract: '摘要内容', collections: ['CK1'], tags: ['ml'],
  date_added: null,
};
const DETAIL = {
  ...SUMMARY, date_modified: null, extra: null, doi: null, url: null,
  attachments: [{ key: 'AT1', filename: 'a.pdf', path: '/p/a.pdf', content_type: 'application/pdf' }],
};
const ANNOTATION = { key: 'AN1', type: 'highlight', text: '划线内容', comment: null, color: '#ffd400', page_label: '3', date_added: null };

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <ZoteroTab />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  statusMock.mockResolvedValue(availableStatus());
  listCollectionsMock.mockResolvedValue([COLLECTION]);
  searchMock.mockResolvedValue([SUMMARY]);
  getItemMock.mockResolvedValue(DETAIL);
  getAnnotationsMock.mockResolvedValue([ANNOTATION]);
  setPathMock.mockResolvedValue({ ok: true, db_path: '' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ZoteroTab 状态卡片', () => {
  it('加载中显示检测中', () => {
    renderTab();
    expect(screen.getByText('检测中…')).toBeInTheDocument();
  });

  it('连接成功显示已连接与统计数字', async () => {
    renderTab();
    await waitFor(() => expect(screen.getByText('已连接')).toBeInTheDocument());
    expect(screen.getByText('10')).toBeInTheDocument(); // 条目数
    expect(screen.getByText('条目')).toBeInTheDocument();
    // 分类下拉已填充
    await waitFor(() => expect(screen.getByText(/Root \(4\)/)).toBeInTheDocument());
  });

  it('不可用显示未连接', async () => {
    statusMock.mockResolvedValue({ available: false, db_path: null, error: 'Zotero database not found.', stats: null });
    renderTab();
    await waitFor(() => expect(screen.getByText('未连接')).toBeInTheDocument());
    expect(screen.getByText('Zotero database not found.')).toBeInTheDocument();
    // 未连接时无搜索框
    expect(screen.queryByPlaceholderText('搜索文献（标题/摘要/作者）…')).not.toBeInTheDocument();
  });
});

describe('ZoteroTab 路径保存', () => {
  it('保存调用 setPath 并显示已保存 + 刷新状态', async () => {
    renderTab();
    await waitFor(() => expect(screen.getByText('已连接')).toBeInTheDocument());
    const input = screen.getByLabelText('数据库路径');
    await act(async () => {
      fireEvent.change(input, { target: { value: '  C:/custom/zotero.sqlite  ' } });
    });
    fireEvent.click(screen.getByText('保存路径'));
    await waitFor(() => expect(setPathMock).toHaveBeenCalledWith('C:/custom/zotero.sqlite'));
    await waitFor(() => expect(screen.getByText('路径已保存')).toBeInTheDocument());
    // 保存后重载状态
    expect(statusMock).toHaveBeenCalledTimes(2);
  });
});

describe('ZoteroTab 搜索', () => {
  it('空查询且无筛选时不触发 search', async () => {
    vi.useFakeTimers();
    renderTab();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(searchMock).not.toHaveBeenCalled();
  });

  it('输入经 300ms 防抖后触发 search 并渲染结果', async () => {
    vi.useFakeTimers();
    renderTab();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    const input = screen.getByPlaceholderText('搜索文献（标题/摘要/作者）…');
    fireEvent.change(input, { target: { value: '论文' } });
    expect(searchMock).not.toHaveBeenCalled(); // 防抖窗口内
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    expect(searchMock).toHaveBeenCalledWith({
      q: '论文', collection_key: undefined, tag: undefined, limit: 30,
    });
    expect(screen.getByText('一篇论文')).toBeInTheDocument();
  });

  it('点击结果加载详情与批注', async () => {
    vi.useFakeTimers();
    renderTab();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    const input = screen.getByPlaceholderText('搜索文献（标题/摘要/作者）…');
    fireEvent.change(input, { target: { value: '论文' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });
    fireEvent.click(screen.getByText('一篇论文'));
    // fake timers 下 waitFor 的轮询 interval 不走虚拟时钟，用 microtask 冲刷
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getItemMock).toHaveBeenCalledWith('ITEM1');
    expect(getAnnotationsMock).toHaveBeenCalledWith('ITEM1');
    // 展开区显示摘要与批注标题
    expect(screen.getByText('摘要内容')).toBeInTheDocument();
    expect(screen.getByText(/批注 \(\d\)/)).toBeInTheDocument();
  });
});
