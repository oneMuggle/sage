import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useWikiStore } from '../../../entities/wiki/store';
import { ActivityPanel } from '../ActivityPanel';
import { LintItemCard } from '../LintItemCard';
import { ReviewItemCard } from '../ReviewItemCard';
import { WikiInsightsPanel } from '../WikiInsightsPanel';
import { WikiLintView } from '../WikiLintView';
import { WikiProjectPicker } from '../WikiProjectPicker';
import { WikiQueuePanel } from '../WikiQueuePanel';
import { WikiReviewView } from '../WikiReviewView';
import { WikiSearch } from '../WikiSearch';

const mockSelectDirectory = vi.fn();
const mockCheckWikiProject = vi.fn();
const mockGetRecent = vi.fn();
const mockRecordRecent = vi.fn();
const mockCreate = vi.fn();
const mockOpen = vi.fn();
const mockListDir = vi.fn();
const mockWikiLintRun = vi.fn();
const mockWikiReviewRun = vi.fn();
const mockGetWikiInsights = vi.fn();
const mockQueueGetStatus = vi.fn();
const mockQueueListTasks = vi.fn();
const mockQueueClearTasks = vi.fn();
const mockQueueCancelTask = vi.fn();
const mockQueueRetryTask = vi.fn();
const mockWikiSearch = vi.fn();
const mockWikiReadFile = vi.fn();

vi.mock('../../../shared/api-client/wiki', () => ({
  checkWikiProject: (...a: unknown[]) => mockCheckWikiProject(...a),
  getRecentWikiProjects: () => mockGetRecent(),
  recordRecentWikiProject: (...a: unknown[]) => mockRecordRecent(...a),
  createWikiProject: (...a: unknown[]) => mockCreate(...a),
  openWikiProject: (...a: unknown[]) => mockOpen(...a),
  wikiListDirectory: (...a: unknown[]) => mockListDir(...a),
  wikiLintRun: (...a: unknown[]) => mockWikiLintRun(...a),
  wikiReviewRun: (...a: unknown[]) => mockWikiReviewRun(...a),
  getWikiInsights: (...a: unknown[]) => mockGetWikiInsights(...a),
  queueGetStatus: (...a: unknown[]) => mockQueueGetStatus(...a),
  queueListTasks: (...a: unknown[]) => mockQueueListTasks(...a),
  queueClearTasks: (...a: unknown[]) => mockQueueClearTasks(...a),
  queueCancelTask: (...a: unknown[]) => mockQueueCancelTask(...a),
  queueRetryTask: (...a: unknown[]) => mockQueueRetryTask(...a),
  wikiSearch: (...a: unknown[]) => mockWikiSearch(...a),
  wikiReadFile: (...a: unknown[]) => mockWikiReadFile(...a),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { window: { electronAPI: unknown } }).window.electronAPI = {
    selectDirectory: mockSelectDirectory,
  };
});

// Helper: enter create mode (the existing component starts at 'menu' state).
async function enterCreateMode() {
  const createMenuBtn = await screen.findByRole('button', { name: /创建新项目/ });
  fireEvent.click(createMenuBtn);
}

describe('WikiProjectPicker — recent projects default', () => {
  it('fetches recent projects on mount', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await waitFor(() => expect(mockGetRecent).toHaveBeenCalled());
  });

  it('uses parent of most recent project as defaultPath', async () => {
    mockGetRecent.mockResolvedValue([
      { path: '/tmp/projects/foo/wiki', name: 'foo', opened_at: 1, intent: 'open' },
    ]);
    render(<WikiProjectPicker />);
    const recentSection = await screen.findByTestId('wiki-recent-projects-section');
    expect(recentSection).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wiki-recent-copy-md-btn'));
    expect(screen.getByTestId('wiki-recent-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-recent-copy-json-btn'));
    expect(screen.getByTestId('wiki-recent-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByTestId('wiki-recent-copy-path-0'));
    expect(screen.getByTestId('wiki-recent-copy-path-0')).toHaveTextContent('已复制');
    await enterCreateMode();
    mockSelectDirectory.mockResolvedValue('/tmp/projects/foo/wiki');
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      expect(mockSelectDirectory).toHaveBeenCalledWith(
        expect.objectContaining({ defaultPath: expect.stringContaining('projects') }),
      );
    });
  });

  it('passes undefined defaultPath when no recent projects', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      const call = mockSelectDirectory.mock.calls[0]?.[0];
      expect(call?.defaultPath).toBeUndefined();
    });
  });
});

describe('WikiProjectPicker — debounced check', () => {
  it('debounces check calls to 300ms', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    // The path input is the second text input in create mode (after the name input).
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    // The storage-path input is the one whose placeholder contains "wiki-projects" (the brief's hint).
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    expect(pathInput).toBeTruthy();
    fireEvent.change(pathInput, { target: { value: '/tmp/a' } });
    fireEvent.change(pathInput, { target: { value: '/tmp/ab' } });
    fireEvent.change(pathInput, { target: { value: '/tmp/abc' } });
    expect(mockCheckWikiProject).not.toHaveBeenCalled();
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalledTimes(1), { timeout: 1500 });
    expect(mockCheckWikiProject).toHaveBeenCalledWith('/tmp/abc', expect.any(String));
  });
});

describe('WikiProjectPicker — submit guard', () => {
  it('disables create button when checkStatus is error', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: false,
      warning: null,
      error: '父目录不可写',
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/x' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    // The submit button is the primary one in the form; the existing component
    // uses "创建项目" / "打开项目" as labels. Match by the wider regex the brief
    // specified.
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    await waitFor(() => expect(createBtn).toBeDisabled());
  });

  it('enables create button when checkStatus is ok and path is non-empty', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/new' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    await waitFor(() => expect(createBtn).not.toBeDisabled());
  });
});

describe('WikiProjectPicker — Browse button', () => {
  it('calls selectDirectory and fills input on non-null result; preserves on null', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });

    mockSelectDirectory.mockResolvedValueOnce(null);
    fireEvent.click(browseBtn);
    await waitFor(() => expect(mockSelectDirectory).toHaveBeenCalled());
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    expect(pathInput.value).toBe('');

    mockSelectDirectory.mockResolvedValueOnce('/tmp/picked');
    fireEvent.click(browseBtn);
    await waitFor(() => expect(pathInput.value).toBe('/tmp/picked'));
  });
});

describe('WikiProjectPicker — record on success', () => {
  it('records recent project after successful create', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    mockCreate.mockResolvedValue({
      id: 'p1',
      name: 'demo',
      path: '/tmp/demo',
      created_at: 1,
      has_content: false,
    });
    mockListDir.mockResolvedValue({ entries: [] });
    mockRecordRecent.mockResolvedValue(undefined);

    render(<WikiProjectPicker />);
    await enterCreateMode();
    // Fill the name input first (existing component requires it).
    const nameInput = (await screen.findByPlaceholderText(/我的|名称|name/i)) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'demo' } });
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/demo' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    fireEvent.click(createBtn);
    await waitFor(() =>
      expect(mockRecordRecent).toHaveBeenCalledWith(
        expect.objectContaining({ path: '/tmp/demo', intent: 'create' }),
      ),
    );
  });
});

describe('WikiProjectPicker — status badge states', () => {
  it('renders green check for ok status and red X for error', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;

    // Use mockImplementation so the response can be controlled per-path
    // (mockResolvedValueOnce is fragile here because the first call may not
    // happen if the debounce timer is canceled by a quick re-input).
    mockCheckWikiProject.mockImplementation(async (p: string) => {
      if (p === '/tmp/ok') {
        return {
          exists: false,
          writable: false,
          is_project: false,
          parent_writable: true,
          warning: null,
          error: null,
        };
      }
      return {
        exists: false,
        writable: false,
        is_project: false,
        parent_writable: false,
        warning: null,
        error: '父目录不可写',
      };
    });

    fireEvent.change(pathInput, { target: { value: '/tmp/ok' } });
    await waitFor(() => expect(screen.queryByText(/可创建|有效的|valid/i)).toBeTruthy());
    fireEvent.click(screen.getByTestId('wiki-check-copy-json-btn'));
    expect(screen.getByTestId('wiki-check-copy-json-btn')).toHaveTextContent('已复制检查JSON');

    fireEvent.change(pathInput, { target: { value: '/tmp/bad' } });
    await waitFor(() => expect(screen.queryByText(/父目录不可写/i)).toBeTruthy());
  });
});

describe('Phase P81 Wiki governance panels — Lint, Review, Insights & Queue exports', () => {
  it('renders WikiLintView, filters severities, and exports MD & JSON', async () => {
    mockWikiLintRun.mockResolvedValue({
      issues: [
        {
          code: 'broken-link',
          severity: 'error',
          file: 'docs/intro.md',
          message: 'Broken link to setup.md',
          suggestion: 'Create setup.md',
        },
        {
          code: 'orphan',
          severity: 'warning',
          file: 'docs/orphan.md',
          message: 'Orphan page',
        },
      ],
    });
    render(<WikiLintView projectPath="/tmp/wiki-proj" />);
    await waitFor(() => expect(screen.getByTestId('wiki-lint-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-lint-copy-md-btn'));
    expect(screen.getByTestId('wiki-lint-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-lint-copy-json-btn'));
    expect(screen.getByTestId('wiki-lint-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('错误'));
    fireEvent.click(screen.getByText('提示'));
    fireEvent.click(screen.getByText('全部'));
    fireEvent.click(screen.getByText('运行检查'));
  });

  it('renders WikiReviewView, resolves items, and exports MD & JSON', async () => {
    mockWikiReviewRun.mockResolvedValue({
      items: [
        {
          id: 'rev-1',
          type: 'contradiction',
          title: 'Conflicting dates',
          description: 'Page A and Page B disagree on release date',
          affected_pages: ['docs/a.md', 'docs/b.md'],
        },
      ],
    });
    render(<WikiReviewView projectPath="/tmp/wiki-proj" />);
    await waitFor(() => expect(screen.getByTestId('wiki-review-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-review-copy-md-btn'));
    expect(screen.getByTestId('wiki-review-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-review-copy-json-btn'));
    expect(screen.getByTestId('wiki-review-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getAllByText('矛盾')[0]);
    fireEvent.click(screen.getByText('缺页'));
    fireEvent.click(screen.getByText('全部'));
    fireEvent.click(screen.getByTitle('忽略此项'));
    fireEvent.click(screen.getByText('运行审核'));
  });

  it('renders WikiInsightsPanel and exports MD & JSON', async () => {
    const onNodeClick = vi.fn();
    mockGetWikiInsights.mockResolvedValue({
      stats: {
        total_nodes: 12,
        total_edges: 24,
        total_communities: 3,
        surprising_connections: 1,
      },
      surprising_connections: [
        {
          source_id: 'a.md',
          source_label: 'Architecture',
          target_id: 'b.md',
          target_label: 'Billing',
          strength: 0.85,
          reason: 'Shared domain model',
        },
      ],
      knowledge_gaps: [
        {
          node_id: 'c.md',
          node_label: 'Legacy Module',
          gap_type: 'isolated_node',
          severity: 'high',
          description: 'No incoming links',
          suggestion: 'Link from index.md',
        },
        {
          node_id: 'community_1',
          node_label: 'Sparse Cluster',
          gap_type: 'sparse_community',
          severity: 'medium',
          description: 'Sparse cluster',
          suggestion: 'Add cross-links',
        },
      ],
    });
    render(<WikiInsightsPanel projectPath="/tmp/wiki-proj" onNodeClick={onNodeClick} />);
    await waitFor(() => expect(screen.getByTestId('wiki-insights-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-insights-copy-md-btn'));
    expect(screen.getByTestId('wiki-insights-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-insights-copy-json-btn'));
    expect(screen.getByTestId('wiki-insights-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('Architecture'));
    fireEvent.click(screen.getByText('Billing'));
    fireEvent.click(screen.getByText('Legacy Module'));
    expect(onNodeClick).toHaveBeenCalledTimes(3);
  });

  it('renders WikiQueuePanel and exports MD & JSON', async () => {
    mockQueueGetStatus.mockResolvedValue({
      pending: 1,
      processing: 0,
      completed: 1,
      failed: 1,
      cancelled: 0,
    });
    mockQueueListTasks.mockResolvedValue({
      tasks: [
        {
          task_id: 't1',
          source_path: '/tmp/doc1.pdf',
          status: 'failed',
          created_at: new Date().toISOString(),
          retry_count: 1,
          max_retries: 3,
          error_message: 'Parse error',
        },
      ],
    });
    render(<WikiQueuePanel projectPath="/tmp/wiki-proj" />);
    await waitFor(() => expect(screen.getByTestId('wiki-queue-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-queue-copy-md-btn'));
    expect(screen.getByTestId('wiki-queue-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-queue-copy-json-btn'));
    expect(screen.getByTestId('wiki-queue-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('重试'));
    fireEvent.click(screen.getByText('取消'));
    fireEvent.click(screen.getByText('等待'));
    fireEvent.click(screen.getByText('全部'));
  });

  it('renders ActivityPanel, LintItemCard, ReviewItemCard, and WikiSearch with MD & JSON exports', async () => {
    render(<ActivityPanel />);
    fireEvent.click(screen.getByText('加载'));
    expect(screen.getByTestId('wiki-activity-copy-md-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wiki-activity-copy-md-btn'));
    expect(screen.getByTestId('wiki-activity-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-activity-copy-json-btn'));
    expect(screen.getByTestId('wiki-activity-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('活动'));

    const onFix = vi.fn();
    const onDismiss = vi.fn();
    render(
      <LintItemCard
        item={{
          id: 'lint-card-1',
          type: 'broken-link',
          severity: 'error',
          page: 'docs/intro.md',
          message: 'Broken link to setup.md',
          suggestion: 'Create setup.md',
        }}
        onFix={onFix}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId('wiki-lint-item-copy-json-lint-card-1'));
    expect(screen.getByTestId('wiki-lint-item-copy-json-lint-card-1')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('修复'));
    fireEvent.click(screen.getByText('忽略'));
    expect(onFix).toHaveBeenCalledWith('lint-card-1');
    expect(onDismiss).toHaveBeenCalledWith('lint-card-1');

    const onAction = vi.fn();
    render(
      <ReviewItemCard
        item={{
          id: 'rev-card-1',
          type: 'contradiction',
          title: 'Conflicting dates',
          description: 'Page A and Page B disagree',
          affectedPages: ['docs/a.md'],
          resolved: false,
          actions: [{ id: 'ignore', label: '忽略', type: 'dismiss' }],
        }}
        onAction={onAction}
      />,
    );
    fireEvent.click(screen.getByTestId('wiki-review-item-copy-json-rev-card-1'));
    expect(screen.getByTestId('wiki-review-item-copy-json-rev-card-1')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getAllByText('忽略').slice(-1)[0]);
    expect(onAction).toHaveBeenCalledWith('rev-card-1', 'ignore');

    useWikiStore.getState().setProject(null);
    const { unmount: unmountNoProj } = render(<WikiSearch />);
    expect(screen.getByText('请先打开一个 wiki 项目')).toBeInTheDocument();
    unmountNoProj();

    useWikiStore.getState().setProject({
      id: 'wp-1',
      name: 'Wiki Project',
      path: '/tmp/wiki-proj',
    });
    mockWikiSearch.mockResolvedValueOnce({ results: [] });
    render(<WikiSearch />);
    const searchInput = screen.getByPlaceholderText(/搜索 wiki 页面/);
    fireEvent.change(searchInput, { target: { value: 'none' } });
    fireEvent.keyDown(searchInput, { key: 'Enter' });
    await waitFor(() => expect(screen.getByText(/未找到匹配/)).toBeInTheDocument());

    mockWikiSearch.mockResolvedValue({
      results: [
        {
          title: 'Architecture Guide',
          path: 'docs/arch.md',
          snippet: 'System architecture overview',
          score: 0.95,
        },
      ],
    });
    mockWikiReadFile.mockResolvedValue('# Architecture');
    fireEvent.change(searchInput, { target: { value: 'architecture' } });
    fireEvent.keyDown(searchInput, { key: 'Enter' });
    await waitFor(() => expect(screen.getByTestId('wiki-search-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-search-copy-md-btn'));
    expect(screen.getByTestId('wiki-search-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-search-copy-json-btn'));
    expect(screen.getByTestId('wiki-search-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('Architecture Guide'));
  });
});
