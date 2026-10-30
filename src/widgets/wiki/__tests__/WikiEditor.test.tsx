import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useResearchStore } from '../../../entities/wiki/research-store';
import { useWikiStore } from '../../../entities/wiki/store';
import { I18nProvider } from '../../../shared/lib/i18n';
import { CommunityColoredGraph } from '../CommunityColoredGraph';
import { LeftPanel } from '../LeftPanel';
import { RightPanel } from '../RightPanel';
import { SourcesView } from '../SourcesView';
import { WikiEditor } from '../WikiEditor';
import { WikiGraphView } from '../WikiGraphView';
import { WikiIngestProgress } from '../WikiIngestProgress';
import { WikiResearchPanel } from '../WikiResearchPanel';
import { WikiToolbar } from '../WikiToolbar';

function I18nWrapper({ children }: { children: React.ReactNode }) {
  return <I18nProvider defaultLocale="zh">{children}</I18nProvider>;
}

const renderWithI18n = (ui: React.ReactElement, options?: Parameters<typeof render>[1]) =>
  render(ui, { wrapper: I18nWrapper, ...options });

const mockStartWikiResearch = vi.fn();
const mockWikiIngestStream = vi.fn();
const mockWikiWriteFile = vi.fn();
const mockWikiListDirectory = vi.fn();
const mockGetWikiCommunities = vi.fn();

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-react-flow">{children}</div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom' },
  useNodesState: (initial: unknown[]) => [initial, vi.fn(), vi.fn()],
  useEdgesState: (initial: unknown[]) => [initial, vi.fn(), vi.fn()],
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  startWikiResearch: (...a: unknown[]) => mockStartWikiResearch(...a),
  wikiIngestStream: (...a: unknown[]) => mockWikiIngestStream(...a),
  wikiWriteFile: (...a: unknown[]) => mockWikiWriteFile(...a),
  wikiListDirectory: (...a: unknown[]) => mockWikiListDirectory(...a),
  getWikiCommunities: (...a: unknown[]) => mockGetWikiCommunities(...a),
  wikiReadFile: vi.fn(),
  wikiDeleteFile: vi.fn(),
  getWikiGraph: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

// `editContent` and `isEditing` live as local useState inside WikiEditor
// (not in the store). The brief's original spy-on-store approach cannot
// observe them, so this test verifies the same behavioral contract —
// "editContent re-syncs when fileContent changes" — by inspecting the
// rendered textarea / preview after a file switch.

describe('WikiEditor', () => {
  it('re-syncs editContent when fileContent changes', () => {
    useWikiStore.setState({
      selectedFile: 'wiki/foo.md',
      fileContent: 'first',
      isLoading: false,
    });
    const { rerender } = renderWithI18n(<WikiEditor />);

    // Enter edit mode — the 编辑 button copies fileContent into local
    // editContent, so the textarea starts showing 'first'.
    fireEvent.click(screen.getByText(/^编辑$/));
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('first');

    // Switch to a different file. With the bug (useState initializer
    // runs only once), editContent would remain 'first' on rerender
    // and isEditing would stay true, so the textarea would still show
    // stale 'first'. With the fix (useEffect on [fileContent]),
    // editContent resets to 'second' and isEditing flips back to
    // false, so the textarea is unmounted.
    act(() => {
      useWikiStore.setState({ fileContent: 'second' });
    });
    rerender(<WikiEditor />);

    expect(screen.queryByRole('textbox')).toBeNull();
    // After the useEffect runs, MarkdownPreview re-renders with the
    // new fileContent — sanity check that we are showing the new file.
    expect(screen.getByText('second')).toBeInTheDocument();
  });

  it('handles empty/loading/save states in WikiEditor', async () => {
    useWikiStore.setState({ selectedFile: null, fileContent: '', isLoading: false });
    const { rerender } = renderWithI18n(<WikiEditor />);
    expect(screen.getByText('选择一个文件以查看或编辑')).toBeInTheDocument();

    act(() => {
      useWikiStore.setState({ selectedFile: 'wiki/bar.md', fileContent: '', isLoading: true });
    });
    rerender(<WikiEditor />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();

    act(() => {
      useWikiStore.setState({
        project: { id: 'p1', name: 'Demo Wiki', path: '/tmp/wiki' },
        selectedFile: 'wiki/bar.md',
        fileContent: '# Bar Content',
        isLoading: false,
      });
    });
    rerender(<WikiEditor />);
    fireEvent.click(screen.getByText(/^预览$/));
    fireEvent.click(screen.getByText(/^编辑$/));
    mockWikiWriteFile.mockResolvedValue({});
    mockWikiListDirectory.mockResolvedValue([]);
    fireEvent.click(screen.getByText(/^保存$/));
  });

  it('renders WikiToolbar and switches views', () => {
    useWikiStore.setState({ project: null, selectedFile: null });
    const { rerender } = renderWithI18n(<WikiToolbar />);

    act(() => {
      useWikiStore.setState({
        project: { id: 'p1', name: 'Demo Wiki', path: '/tmp/wiki' },
        activeView: 'browser',
        selectedFile: 'wiki/guide.md',
      });
    });
    rerender(<WikiToolbar />);
    expect(screen.getByText('Demo Wiki')).toBeInTheDocument();
    expect(screen.getByText('guide.md')).toBeInTheDocument();
    fireEvent.click(screen.getByText('搜索'));
    expect(useWikiStore.getState().activeView).toBe('search');
  });

  it('renders WikiResearchPanel and runs research', async () => {
    mockStartWikiResearch.mockResolvedValue({
      status: 'done',
      queries: ['ai agents 2026'],
      web_results_count: 1,
      saved_path: 'wiki/research/ai-agents.md',
      synthesis: '# AI Agents Synthesis',
      web_results: [
        {
          title: 'Agent Trends',
          url: 'https://example.com/agents',
          snippet: 'Key trends in multi-agent systems',
        },
      ],
    });
    render(
      <WikiResearchPanel
        projectPath="/tmp/wiki"
        llmBaseUrl="http://localhost:11434"
        llmApiKey="sk-test"
        llmModel="gpt-4"
      />,
    );
    const textarea = screen.getByPlaceholderText(/AI 代理/);
    fireEvent.change(textarea, { target: { value: 'AI Agents 2026' } });
    fireEvent.click(screen.getByLabelText(/自动 Ingest/));
    fireEvent.click(screen.getByText('开始研究'));
    await waitFor(() => expect(screen.getByText('# AI Agents Synthesis')).toBeInTheDocument());
    fireEvent.click(screen.getByText('新研究'));
    expect(screen.getByText('开始研究')).toBeInTheDocument();

    mockStartWikiResearch.mockRejectedValueOnce(new Error('Search API unavailable'));
    fireEvent.change(screen.getByPlaceholderText(/AI 代理/), { target: { value: 'Error Topic' } });
    fireEvent.click(screen.getByText('开始研究'));
    await waitFor(() => expect(screen.getByText(/Search API unavailable/)).toBeInTheDocument());
  });

  it('renders SourcesView and selects files', () => {
    useWikiStore.setState({
      project: { id: 'p1', name: 'Demo Wiki', path: '/tmp/wiki' },
    });
    renderWithI18n(<SourcesView />);
    fireEvent.click(screen.getByText('sources'));
    fireEvent.click(screen.getByText('architecture.docx'));
    expect(screen.getByText('文件信息')).toBeInTheDocument();
  });

  it('renders LeftPanel, RightPanel, and WikiIngestProgress', () => {
    useWikiStore.setState({
      fileTree: [
        {
          name: 'wiki',
          path: 'wiki',
          is_dir: true,
          children: [{ name: 'intro.md', path: 'wiki/intro.md', is_dir: false }],
        },
      ],
      selectedFile: 'wiki/intro.md',
      fileContent: '# Intro',
    });
    mockWikiListDirectory.mockResolvedValue([
      {
        name: 'wiki',
        path: 'wiki',
        is_dir: true,
        children: [{ name: 'intro.md', path: 'wiki/intro.md', is_dir: false }],
      },
    ]);
    renderWithI18n(<LeftPanel />);
    fireEvent.click(screen.getByText('活动'));
    expect(screen.getByText(/活动面板内容/)).toBeInTheDocument();

    useResearchStore.setState({ panelOpen: true });
    renderWithI18n(<RightPanel />);
    const closeResearchBtn = screen.getByText('深度研究').parentElement?.querySelector('button');
    if (closeResearchBtn) fireEvent.click(closeResearchBtn);
    useWikiStore.setState({ selectedFile: null });
    useResearchStore.setState({ panelOpen: false });
    renderWithI18n(<RightPanel />);

    const { rerender } = render(
      <WikiIngestProgress
        progress={{ stage: 'step1_analyze', percent: 45, message: 'Analyzing docs' }}
        done={false}
        error={null}
      />,
    );
    expect(screen.getByText('LLM 分析(Step 1)')).toBeInTheDocument();

    rerender(
      <WikiIngestProgress
        progress={{ stage: 'custom_stage' as never, percent: 80 }}
        done={false}
        error={null}
      />,
    );
    rerender(<WikiIngestProgress progress={null} done={false} error={null} />);

    rerender(<WikiIngestProgress progress={null} done={true} error={null} />);
    expect(screen.getByText('导入完成')).toBeInTheDocument();

    rerender(<WikiIngestProgress progress={null} done={false} error="Disk full" />);
    expect(screen.getByText('导入失败: Disk full')).toBeInTheDocument();
  });

  it('renders CommunityColoredGraph and WikiGraphView', async () => {
    mockGetWikiCommunities.mockResolvedValue({
      communities: [{ community_id: 1, size: 2, cohesion: 0.85, members: ['a', 'b'] }],
    });
    const graphData = {
      nodes: [
        { id: 'a', label: 'Node A', page_type: 'entity', sources: ['s1.pdf'], wikilinks: ['b'] },
        { id: 'b', label: 'Node B', page_type: 'concept', sources: [], wikilinks: ['a'] },
      ],
      edges: [{ source: 'a', target: 'b', signal: 'DirectLink' as const, weight: 1.0 }],
    };
    renderWithI18n(<CommunityColoredGraph data={graphData} projectPath="/tmp/wiki" query="Node" />);
    await waitFor(() => expect(screen.getByText(/社区 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/社区 1/));
    fireEvent.click(screen.getByText('清除'));

    renderWithI18n(<WikiGraphView data={{ nodes: [], edges: [] }} />);
    expect(screen.getByText(/暂无 wiki 页面/)).toBeInTheDocument();
    renderWithI18n(<CommunityColoredGraph data={graphData} />);
  });
});
