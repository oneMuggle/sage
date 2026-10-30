/**
 * M5: ZoteroSyncPanel 状态机测试。
 *
 * 覆盖：状态加载占位/状态行、embedding 未配置引导、增量同步、完整重建、
 * 项目路径解析（活跃项目 / 最近项目 / 无项目提示）、同步失败、skipped、
 * wiki 标签保存、未连接禁用、时间格式化。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const syncStatusMock = vi.fn();
const syncMock = vi.fn();
const getWikiTagMock = vi.fn();
const setWikiTagMock = vi.fn();
const getWikiProjectPathMock = vi.fn();
const setWikiProjectPathMock = vi.fn();
const recentProjectsMock = vi.fn();
const toastSuccess = vi.fn();
const toastWarning = vi.fn();
const toastError = vi.fn();

const wikiState = vi.hoisted(() => ({ project: null as { path: string } | null }));

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    warning: (...args: unknown[]) => toastWarning(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock('../../../shared/api/zoteroClient', () => ({
  DEFAULT_WIKI_TAG: 'sage:wiki',
  zoteroClient: {
    syncStatus: (...args: unknown[]) => syncStatusMock(...args),
    sync: (...args: unknown[]) => syncMock(...args),
    getWikiTag: (...args: unknown[]) => getWikiTagMock(...args),
    setWikiTag: (...args: unknown[]) => setWikiTagMock(...args),
    getWikiProjectPath: (...args: unknown[]) => getWikiProjectPathMock(...args),
    setWikiProjectPath: (...args: unknown[]) => setWikiProjectPathMock(...args),
  },
}));

vi.mock('../../../entities/wiki/store', () => ({
  useWikiStore: { getState: () => wikiState },
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  getRecentWikiProjects: (...args: unknown[]) => recentProjectsMock(...args),
}));

import { I18nProvider } from '../../../shared/lib/i18n';
import { formatZoteroSyncTime, ZoteroSyncPanel } from '../zotero/ZoteroSyncPanel';

function makeStatus(overrides: Record<string, unknown> = {}) {
  return {
    last_sync_ts: null,
    last_sync_at: null,
    item_count: 0,
    wiki_page_count: 0,
    embedding_configured: true,
    vector_dim: null,
    sync_in_progress: false,
    errors: [] as string[],
    ...overrides,
  };
}

function makeResult(overrides: Record<string, unknown> = {}) {
  return {
    items: 5,
    chunks: 5,
    dim: 1024,
    last_sync_ts: 'ts',
    skipped: false,
    elapsed_ms: 1200,
    errors: [] as string[],
    ...overrides,
  };
}

function renderPanel(connected = true) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ZoteroSyncPanel connected={connected} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  wikiState.project = null;
  syncStatusMock.mockResolvedValue(
    makeStatus({
      item_count: 12,
      wiki_page_count: 3,
      last_sync_at: '2026-10-27T03:05:00Z',
    }),
  );
  getWikiTagMock.mockResolvedValue('sage:wiki');
  setWikiTagMock.mockResolvedValue(undefined);
  getWikiProjectPathMock.mockResolvedValue('');
  setWikiProjectPathMock.mockResolvedValue(undefined);
  recentProjectsMock.mockResolvedValue([]);
});

describe('ZoteroSyncPanel 状态', () => {
  it('状态未返回时显示占位且不渲染状态行', () => {
    syncStatusMock.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText('索引与同步')).toBeInTheDocument();
    expect(screen.queryByTestId('zotero-sync-status-line')).not.toBeInTheDocument();
    expect(screen.getByTestId('zotero-sync-now')).toBeEnabled();
  });

  it('状态行展示已索引数、wiki 页面数与上次同步时间', async () => {
    renderPanel();
    const line = await screen.findByTestId('zotero-sync-status-line');
    expect(line).toHaveTextContent('已索引文献');
    expect(line).toHaveTextContent('12');
    expect(line).toHaveTextContent('wiki 页面');
    expect(line).toHaveTextContent('3');
    expect(line).toHaveTextContent('上次同步');
    expect(line).toHaveTextContent(/2026-10-\d{2} \d{2}:\d{2}/);
  });

  it('未同步过时显示尚未同步', async () => {
    syncStatusMock.mockResolvedValue(makeStatus());
    renderPanel();
    const line = await screen.findByTestId('zotero-sync-status-line');
    expect(line).toHaveTextContent('尚未同步');
  });

  it('embedding 未配置时给出设置引导', async () => {
    syncStatusMock.mockResolvedValue(makeStatus({ embedding_configured: false }));
    renderPanel();
    const hint = await screen.findByTestId('zotero-sync-embedding-hint');
    expect(hint).toHaveTextContent('请先在 设置 → 模型 配置 embedding 模型');
  });

  it('未连接时禁用两个同步按钮', () => {
    renderPanel(false);
    expect(screen.getByTestId('zotero-sync-now')).toBeDisabled();
    expect(screen.getByTestId('zotero-sync-rebuild')).toBeDisabled();
  });
});

describe('ZoteroSyncPanel 同步动作', () => {
  it('立即同步走增量并展示结果与 wiki 沉淀统计', async () => {
    syncMock.mockResolvedValue(
      makeResult({ wiki: { items_exported: 2, authors_exported: 1, errors: [] } }),
    );
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));

    await waitFor(() =>
      expect(syncMock).toHaveBeenCalledWith({ force: false, projectPath: null }),
    );
    const result = await screen.findByTestId('zotero-sync-result');
    expect(result).toHaveTextContent('同步完成');
    expect(result).toHaveTextContent('已索引文献: 5');
    expect(result).toHaveTextContent('1.2s');
    expect(result).toHaveTextContent('wiki 沉淀');
    // 作者页计数用「作者页」标注，不是「批注」
    expect(result).toHaveTextContent('1 作者页');
    expect(result).not.toHaveTextContent('批注');
    expect(screen.queryByTestId('zotero-sync-project-hint')).not.toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith('同步完成');
  });

  it('完整重建传 force=true', async () => {
    syncMock.mockResolvedValue(makeResult());
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-rebuild'));
    await waitFor(() =>
      expect(syncMock).toHaveBeenCalledWith({ force: true, projectPath: null }),
    );
  });

  it('优先使用已打开的 wiki 项目', async () => {
    wikiState.project = { path: '/active/proj' };
    syncMock.mockResolvedValue(makeResult());
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));
    await waitFor(() =>
      expect(syncMock).toHaveBeenCalledWith({ force: false, projectPath: '/active/proj' }),
    );
    expect(recentProjectsMock).not.toHaveBeenCalled();
  });

  it('优先使用持久化的项目绑定（高于当前打开项目）', async () => {
    wikiState.project = { path: '/active/proj' };
    getWikiProjectPathMock.mockResolvedValue('/bound/proj');
    syncMock.mockResolvedValue(makeResult());
    renderPanel();
    await screen.findByTestId('zotero-sync-status-line');
    await waitFor(() =>
      expect(screen.getByTestId('zotero-wiki-project-input')).toHaveValue('/bound/proj'),
    );
    fireEvent.click(screen.getByTestId('zotero-sync-now'));
    await waitFor(() =>
      expect(syncMock).toHaveBeenCalledWith({ force: false, projectPath: '/bound/proj' }),
    );
  });

  it('无活跃项目时回退到最近打开的项目', async () => {
    recentProjectsMock.mockResolvedValue([
      { path: '/recent/proj', name: 'P', opened_at: 1, intent: 'open' },
    ]);
    syncMock.mockResolvedValue(
      makeResult({ wiki: { items_exported: 1, authors_exported: 0, errors: [] } }),
    );
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));
    await waitFor(() =>
      expect(syncMock).toHaveBeenCalledWith({ force: false, projectPath: '/recent/proj' }),
    );
  });

  it('无可用项目时提示 wiki 沉淀需先打开项目', async () => {
    syncMock.mockResolvedValue(makeResult());
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));
    const hint = await screen.findByTestId('zotero-sync-project-hint');
    expect(hint).toHaveTextContent('未打开知识库项目');
  });

  it('同步失败展示错误并弹错误提示', async () => {
    syncMock.mockRejectedValueOnce(new Error('boom'));
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));

    const error = await screen.findByTestId('zotero-sync-error');
    expect(error).toHaveTextContent('boom');
    expect(toastError).toHaveBeenCalledWith('同步失败: boom');
    expect(screen.queryByTestId('zotero-sync-result')).not.toBeInTheDocument();
  });

  it('skipped 结果提示 embedding 未配置并弹 warning', async () => {
    syncMock.mockResolvedValue(makeResult({ skipped: true, items: 0 }));
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));

    const result = await screen.findByTestId('zotero-sync-result');
    expect(result).toHaveTextContent('同步已跳过');
    expect(toastWarning).toHaveBeenCalledWith('同步已跳过：embedding 模型未配置');
  });

  it('同步时并发（409）显示"已有同步正在进行"而不是裸后端 detail', async () => {
    syncMock.mockRejectedValue(
      Object.assign(new Error('zotero sync already running'), { status_code: 409 }),
    );
    renderPanel();
    fireEvent.click(screen.getByTestId('zotero-sync-now'));

    const error = await screen.findByTestId('zotero-sync-error');
    expect(error).toHaveTextContent('已有同步正在进行，请稍后再试');
    expect(error).not.toHaveTextContent('zotero sync already running');
    expect(toastError).toHaveBeenCalledWith('同步失败: 已有同步正在进行，请稍后再试');
  });

  it('状态加载失败展示错误', async () => {
    syncStatusMock.mockRejectedValue(new Error('status boom'));
    renderPanel();

    const error = await screen.findByTestId('zotero-sync-error');
    expect(error).toHaveTextContent('status boom');
  });
});

describe('ZoteroSyncPanel wiki 标签', () => {
  it('加载已配置标签并可保存（保存后去空格）', async () => {
    getWikiTagMock.mockResolvedValue('custom:tag');
    renderPanel();
    const input = screen.getByLabelText('Wiki 沉淀标签');
    await waitFor(() => expect(input).toHaveValue('custom:tag'));

    fireEvent.change(input, { target: { value: '  mine:wiki  ' } });
    fireEvent.click(screen.getByText('保存标签'));

    await waitFor(() => expect(setWikiTagMock).toHaveBeenCalledWith('  mine:wiki  '));
    await waitFor(() => expect(input).toHaveValue('mine:wiki'));
    expect(screen.getByText('标签已保存')).toBeInTheDocument();
  });

  it('保存标签失败展示错误且不显示"标签已保存"', async () => {
    setWikiTagMock.mockRejectedValue(new Error('save boom'));
    renderPanel();
    fireEvent.click(screen.getByText('保存标签'));

    const error = await screen.findByTestId('zotero-sync-error');
    expect(error).toHaveTextContent('save boom');
    expect(screen.queryByText('标签已保存')).not.toBeInTheDocument();
  });
});

describe('formatZoteroSyncTime', () => {
  it('处理空值、非法值与 ISO-8601', () => {
    expect(formatZoteroSyncTime(null)).toBeNull();
    expect(formatZoteroSyncTime('not-a-date')).toBe('not-a-date');
    expect(formatZoteroSyncTime('2026-10-27T03:05:00Z')).toMatch(
      /^2026-10-\d{2} \d{2}:\d{2}$/,
    );
  });
});
