import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useResearchStore } from '../../../entities/wiki/research-store';
import { useWikiStore } from '../../../entities/wiki/store';
import { CommunityColoredGraph } from '../CommunityColoredGraph';
import { LeftPanel } from '../LeftPanel';
import { RightPanel } from '../RightPanel';
import { SourcesView } from '../SourcesView';
import { WikiEditor } from '../WikiEditor';
import { WikiGraphView } from '../WikiGraphView';
import { WikiIngestProgress } from '../WikiIngestProgress';
import { WikiResearchPanel } from '../WikiResearchPanel';
import { WikiToolbar } from '../WikiToolbar';

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
    const { rerender } = render(<WikiEditor />);

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

  it('exports MD & JSON and handles empty/loading/save states in WikiEditor', async () => {
    useWikiStore.setState({ selectedFile: null, fileContent: '', isLoading: false });
    const { rerender } = render(<WikiEditor />);
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
    fireEvent.click(screen.getByTestId('wiki-editor-copy-md-btn'));
    expect(screen.getByTestId('wiki-editor-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-editor-copy-json-btn'));
    expect(screen.getByTestId('wiki-editor-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText(/^预览$/));
    fireEvent.click(screen.getByText(/^编辑$/));
    mockWikiWriteFile.mockResolvedValue({});
    mockWikiListDirectory.mockResolvedValue([]);
    fireEvent.click(screen.getByText(/^保存$/));
  });

  it('renders WikiToolbar, switches views, and exports project JSON', () => {
    useWikiStore.setState({ project: null, selectedFile: null });
    const { rerender } = render(<WikiToolbar />);
    expect(screen.queryByTestId('wiki-toolbar-copy-json-btn')).toBeNull();

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
    fireEvent.click(screen.getByTestId('wiki-toolbar-copy-json-btn'));
    expect(screen.getByTestId('wiki-toolbar-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('搜索'));
    expect(useWikiStore.getState().activeView).toBe('search');
  });

  it('renders WikiResearchPanel, runs research, and exports MD, JSON, and source JSON', async () => {
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
    await waitFor(() => expect(screen.getByTestId('wiki-research-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-research-copy-md-btn'));
    expect(screen.getByTestId('wiki-research-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-research-copy-json-btn'));
    expect(screen.getByTestId('wiki-research-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByTestId('wiki-research-source-copy-json-1'));
    expect(screen.getByTestId('wiki-research-source-copy-json-1')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('新研究'));
    expect(screen.getByText('开始研究')).toBeInTheDocument();

    mockStartWikiResearch.mockRejectedValueOnce(new Error('Search API unavailable'));
    fireEvent.change(screen.getByPlaceholderText(/AI 代理/), { target: { value: 'Error Topic' } });
    fireEvent.click(screen.getByText('开始研究'));
    await waitFor(() => expect(screen.getByText(/Search API unavailable/)).toBeInTheDocument());
  });

  it('renders SourcesView and exports sources MD, JSON, and selected file JSON', () => {
    useWikiStore.setState({
      project: { id: 'p1', name: 'Demo Wiki', path: '/tmp/wiki' },
    });
    render(<SourcesView />);
    fireEvent.click(screen.getByTestId('wiki-sources-copy-md-btn'));
    expect(screen.getByTestId('wiki-sources-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-sources-copy-json-btn'));
    expect(screen.getByTestId('wiki-sources-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('sources'));
    fireEvent.click(screen.getByText('architecture.docx'));
    expect(screen.getByTestId('wiki-sources-file-copy-json-btn')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wiki-sources-file-copy-json-btn'));
    expect(screen.getByTestId('wiki-sources-file-copy-json-btn')).toHaveTextContent('已复制JSON');
  });

  it('renders LeftPanel, RightPanel, and WikiIngestProgress and exports MD & JSON snapshots', () => {
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
    render(<LeftPanel />);
    fireEvent.click(screen.getByTestId('wiki-file-tree-copy-md-btn'));
    expect(screen.getByTestId('wiki-file-tree-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-file-tree-copy-json-btn'));
    expect(screen.getByTestId('wiki-file-tree-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByText('活动'));
    expect(screen.getByText(/活动面板内容/)).toBeInTheDocument();

    useResearchStore.setState({ panelOpen: true });
    render(<RightPanel />);
    fireEvent.click(screen.getByTestId('wiki-right-preview-copy-md-btn'));
    expect(screen.getByTestId('wiki-right-preview-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-right-preview-copy-json-btn'));
    expect(screen.getByTestId('wiki-right-preview-copy-json-btn')).toHaveTextContent('已复制JSON');
    const closeResearchBtn = screen.getByText('深度研究').parentElement?.querySelector('button');
    if (closeResearchBtn) fireEvent.click(closeResearchBtn);
    useWikiStore.setState({ selectedFile: null });
    useResearchStore.setState({ panelOpen: false });
    render(<RightPanel />);

    const { rerender } = render(
      <WikiIngestProgress
        progress={{ stage: 'step1_analyze', percent: 45, message: 'Analyzing docs' }}
        done={false}
        error={null}
      />,
    );
    fireEvent.click(screen.getByTestId('wiki-ingest-copy-json-btn'));
    expect(screen.getByTestId('wiki-ingest-copy-json-btn')).toHaveTextContent('已复制JSON');

    rerender(
      <WikiIngestProgress
        progress={{ stage: 'custom_stage' as never, percent: 80 }}
        done={false}
        error={null}
      />,
    );
    rerender(<WikiIngestProgress progress={null} done={false} error={null} />);

    rerender(<WikiIngestProgress progress={null} done={true} error={null} />);
    fireEvent.click(screen.getByTestId('wiki-ingest-copy-json-btn'));
    expect(screen.getByTestId('wiki-ingest-copy-json-btn')).toHaveTextContent('已复制JSON');

    rerender(<WikiIngestProgress progress={null} done={false} error="Disk full" />);
    fireEvent.click(screen.getByTestId('wiki-ingest-copy-json-btn'));
    expect(screen.getByTestId('wiki-ingest-copy-json-btn')).toHaveTextContent('已复制JSON');
  });

  it('renders CommunityColoredGraph and WikiGraphView and exports graph & community MD/JSON', async () => {
    mockGetWikiCommunities.mockResolvedValue({
      communities: [
        { community_id: 1, size: 2, cohesion: 0.85, members: ['a', 'b'] },
      ],
    });
    const graphData = {
      nodes: [
        { id: 'a', label: 'Node A', page_type: 'entity', sources: ['s1.pdf'], wikilinks: ['b'] },
        { id: 'b', label: 'Node B', page_type: 'concept', sources: [], wikilinks: ['a'] },
      ],
      edges: [{ source: 'a', target: 'b', signal: 'DirectLink' as const, weight: 1.0 }],
    };
    render(<CommunityColoredGraph data={graphData} projectPath="/tmp/wiki" query="Node" />);
    await waitFor(() => expect(screen.getByTestId('wiki-community-copy-md-btn')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('wiki-community-copy-md-btn'));
    expect(screen.getByTestId('wiki-community-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-community-copy-json-btn'));
    expect(screen.getByTestId('wiki-community-copy-json-btn')).toHaveTextContent('已复制JSON');
    fireEvent.click(screen.getByTestId('wiki-community-item-copy-json-1'));
    expect(screen.getByTestId('wiki-community-item-copy-json-1')).toHaveTextContent('已复制');
    fireEvent.click(screen.getByText(/社区 1/));
    fireEvent.click(screen.getByText('清除'));
    fireEvent.click(screen.getByTestId('wiki-graph-copy-md-btn'));
    expect(screen.getByTestId('wiki-graph-copy-md-btn')).toHaveTextContent('已复制MD');
    fireEvent.click(screen.getByTestId('wiki-graph-copy-json-btn'));
    expect(screen.getByTestId('wiki-graph-copy-json-btn')).toHaveTextContent('已复制JSON');

    render(<WikiGraphView data={{ nodes: [], edges: [] }} />);
    expect(screen.getByText(/暂无 wiki 页面/)).toBeInTheDocument();
    render(<CommunityColoredGraph data={graphData} />);
  });
});
