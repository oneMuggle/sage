// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectType } from '../../shared/api';

import {
  GovernanceRulesPanel,
  formatGovernanceRulesJson,
  formatGovernanceRulesMarkdown,
} from './GovernanceRulesPanel';

/* ── Mock child components ───────────────────────────────────────── */

vi.mock('./ConstraintManager', () => ({
  ConstraintManager: (props: { projectId: string; projectType: string }) => (
    <div
      data-testid="constraint-manager"
      data-project-id={props.projectId}
      data-project-type={props.projectType}
    />
  ),
}));

vi.mock('./StudioMaterialsAndProfilePanels', () => ({
  StudioAllowedPathsTabPanel: (props: {
    projectPath: string;
    allowedPaths: string[];
    newAllowedPath: string;
    savingPaths: boolean;
  }) => (
    <div
      data-testid="allowed-paths-panel"
      data-project-path={props.projectPath}
      data-paths-count={String(props.allowedPaths.length)}
      data-draft={props.newAllowedPath}
      data-saving={String(props.savingPaths)}
    />
  ),
}));

/* ── Helpers ──────────────────────────────────────────────────────── */

const defaultProps = {
  projectId: 'proj-1',
  projectPath: '/home/user/project',
  projectType: 'coding' as ProjectType,
  allowedPaths: ['/etc/shared', '/var/data'],
  newAllowedPath: '',
  onNewAllowedPathChange: vi.fn(),
  savingPaths: false,
  onAddAllowedPath: vi.fn(),
  onQuickAddPresetPath: vi.fn(),
  onRemoveAllowedPath: vi.fn(),
};

const renderPanel = (overrides: Partial<typeof defaultProps> = {}) =>
  render(<GovernanceRulesPanel {...defaultProps} {...overrides} />);

/* ── Tests ────────────────────────────────────────────────────────── */

describe('GovernanceRulesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders both sections with section numbers', () => {
    renderPanel();
    expect(screen.getByTestId('governance-rules-panel')).toBeInTheDocument();
    expect(screen.getByText('AI 行为约束规则')).toBeInTheDocument();
    expect(screen.getByText('跨目录只读白名单')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders ConstraintManager with projectId and projectType', () => {
    renderPanel({ projectId: 'p-42', projectType: 'business' });
    const cm = screen.getByTestId('constraint-manager');
    expect(cm).toBeInTheDocument();
    expect(cm).toHaveAttribute('data-project-id', 'p-42');
    expect(cm).toHaveAttribute('data-project-type', 'business');
  });

  it('renders StudioAllowedPathsTabPanel with allowed paths', () => {
    renderPanel({
      projectPath: '/work/my-proj',
      allowedPaths: ['/a', '/b', '/c'],
    });
    const panel = screen.getByTestId('allowed-paths-panel');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute('data-project-path', '/work/my-proj');
    expect(panel).toHaveAttribute('data-paths-count', '3');
  });

  it('renders a visual separator between the two sections', () => {
    const { container } = renderPanel();
    const separator = container.querySelector('.border-t.border-border');
    expect(separator).toBeInTheDocument();
  });

  it('passes newAllowedPath and savingPaths through to the paths panel', () => {
    renderPanel({ newAllowedPath: '/new/path', savingPaths: true });
    const panel = screen.getByTestId('allowed-paths-panel');
    expect(panel).toHaveAttribute('data-draft', '/new/path');
    expect(panel).toHaveAttribute('data-saving', 'true');
  });

  it('formats and copies governance rules summary as Markdown and JSON', () => {
    const md = formatGovernanceRulesMarkdown({
      projectId: 'proj-1',
      projectPath: '/ws/proj-1',
      projectType: 'research',
      allowedPaths: ['/data/ref'],
    });
    expect(md).toContain('# 项目治理规则摘要 (Governance Rules Summary)');
    expect(md).toContain('/data/ref');
    expect(
      formatGovernanceRulesMarkdown({
        projectId: 'proj-1',
        projectPath: '/ws/proj-1',
        projectType: 'coding',
        allowedPaths: [],
      }),
    ).toContain('_暂无跨目录只读白名单_');

    const parsed = JSON.parse(
      formatGovernanceRulesJson({
        projectId: 'proj-1',
        projectPath: '/ws/proj-1',
        projectType: 'research',
        allowedPaths: ['/data/ref'],
      }),
    );
    expect(parsed.projectId).toBe('proj-1');

    renderPanel();
    fireEvent.click(screen.getByTestId('governance-rules-copy-md'));
    expect(screen.getByTestId('governance-rules-copy-md').textContent).toContain('已复制 MD');
    fireEvent.click(screen.getByTestId('governance-rules-copy-json'));
    expect(screen.getByTestId('governance-rules-copy-json').textContent).toContain('已复制 JSON');
  });
});
