// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { BootstrapPreviewResult } from '../../../shared/api/projectApi';
import { ProjectBootstrapPanel } from '../ProjectBootstrapPanel';

const scanMock = vi.fn();
const suggestMock = vi.fn();
const applyMock = vi.fn();

vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: {
    bootstrapScan: (...args: unknown[]) => scanMock(...args),
    bootstrapSuggest: (...args: unknown[]) => suggestMock(...args),
    bootstrapApply: (...args: unknown[]) => applyMock(...args),
  },
}));

const preview: BootstrapPreviewResult = {
  project: {
    id: 'p1',
    path: '/work/demo',
    name: 'demo',
    createdAt: 1,
    lastOpenedAt: 1,
    allowedPaths: [],
    sessionCount: 0,
    lastSessionId: null,
  },
  scan: {
    level1Type: 'coding',
    subType: 'python_backend',
    techStack: ['python', 'fastapi'],
    sourceFiles: [{ language: 'python', count: 12 }],
    git: {
      isRepo: false,
      currentBranch: null,
      commitCount: 0,
      dirtyFiles: 0,
      gitAvailable: true,
    },
    existing: { sageMd: false, rulesCount: 0, milestonesCount: 0, materialsCount: 0 },
  },
  suggestions: {
    sageMd: { content: '# Demo SAGE', rationale: 'FastAPI project', exists: false },
    rules: [
      {
        key: 'python_default',
        label: 'Python 规范',
        content: 'Use black',
        reason: '检测到 Python',
        category: 'coding_style',
        priority: 8,
        triggerPattern: 'always',
        source: 'template',
      },
    ],
    milestones: [
      {
        title: 'MVP',
        description: 'first milestone',
        stage: 'development',
        estimatedDays: null,
      },
    ],
    allowedPaths: [],
    gitInit: { recommended: true, reason: '尚未纳入 Git', blockers: [] },
    wiki: { recommended: true, estimatedPages: 3 },
    firstPrompt: '请先了解项目',
  },
  llmAvailable: true,
};

describe('ProjectBootstrapPanel', () => {
  beforeEach(() => {
    scanMock.mockReset();
    suggestMock.mockReset();
    applyMock.mockReset();
    scanMock.mockResolvedValue({ project: preview.project, scan: preview.scan });
    suggestMock.mockResolvedValue({
      suggestions: preview.suggestions,
      llmAvailable: true,
      llmError: null,
      ruleSource: 'ai',
    });
    applyMock.mockResolvedValue({
      project: preview.project,
      applied: ['sage_md', 'git_init'],
      skipped: [],
      appliedItems: [
        { item: 'sage_md', label: '项目说明（SAGE.md）', location: '/work/demo/SAGE.md' },
        { item: 'git_init', label: 'Git 版本控制', location: '/work/demo' },
      ],
      skippedItems: [],
      verification: { sageMdExists: true, rulesCountAfter: 1, milestonesCountAfter: 0 },
      errors: [],
      git: null,
    });
  });

  it('renders scan summary and suggestions', async () => {
    render(<ProjectBootstrapPanel projectId="p1" autoStart />);

    expect(await screen.findByTestId('project-bootstrap-panel')).toBeInTheDocument();
    expect(screen.getByText(/技术栈：python、fastapi/)).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-rules')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-milestones')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-git-init')).toBeChecked();
    expect(suggestMock).toHaveBeenCalledWith('p1', true);
  });

  it('renders an idle state when autoStart is false and triggers scan on button click', async () => {
    render(<ProjectBootstrapPanel projectId="p1" />);

    expect(await screen.findByTestId('project-bootstrap-idle')).toBeInTheDocument();
    expect(scanMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('bootstrap-start-ai'));
    expect(await screen.findByTestId('project-bootstrap-panel')).toBeInTheDocument();
    expect(suggestMock).toHaveBeenCalledWith('p1', true);
  });

  it('applies selected suggestions including git init', async () => {
    const onApplied = vi.fn();
    render(<ProjectBootstrapPanel projectId="p1" autoStart onApplied={onApplied} />);

    await screen.findByTestId('project-bootstrap-panel');
    fireEvent.click(screen.getByText('应用选中的建议'));

    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    const [projectId, payload] = applyMock.mock.calls[0];
    expect(projectId).toBe('p1');
    expect(payload.gitInit).toBe(true);
    expect(payload.sageMd).toBe(true);
    expect(payload.sageMdContent).toBe('# Demo SAGE');
    expect(payload.rules).toHaveLength(1);
    expect(payload.milestones).toHaveLength(1);
    expect(onApplied).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId('bootstrap-result')).toHaveTextContent('已应用 2 项');
    expect(screen.getByTestId('bootstrap-verification')).toHaveTextContent(
      '项目规则 1 条 · 里程碑 0 项',
    );
    expect(screen.getByTestId('bootstrap-result-details')).toHaveTextContent('项目说明（SAGE.md）');
    // Applying refreshes the deterministic scan (existing counts).
    expect(scanMock).toHaveBeenCalledTimes(2);
  });

  it('shows local-template badge and fallback notice when LLM is unavailable', async () => {
    suggestMock.mockResolvedValue({
      suggestions: preview.suggestions,
      llmAvailable: false,
      llmError: 'LLM 未配置或请求失败，已改用本地推荐模板',
      ruleSource: 'template',
    });
    render(<ProjectBootstrapPanel projectId="p1" autoStart />);

    await screen.findByTestId('project-bootstrap-panel');
    expect(screen.getByText('本地推荐模板')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-llm-fallback')).toHaveTextContent('已改用本地推荐模板');
  });

  it('shows an error and retry action when scan fails', async () => {
    scanMock.mockRejectedValueOnce(new Error('backend down'));
    render(<ProjectBootstrapPanel projectId="p1" autoStart />);

    expect(await screen.findByTestId('project-bootstrap-error')).toHaveTextContent('backend down');
    fireEvent.click(screen.getByText('仅扫描（不调用 AI）'));
    await waitFor(() => expect(scanMock).toHaveBeenCalledTimes(2));
    expect(suggestMock).toHaveBeenCalledWith('p1', false);
  });
});
