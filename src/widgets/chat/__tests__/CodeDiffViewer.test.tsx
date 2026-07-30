import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { CodeDiff } from '../../../shared/lib/store';
import { CodeDiffViewer } from '../CodeDiffViewer';

function makeDiff(overrides: Partial<CodeDiff> = {}): CodeDiff {
  return {
    path: '/workspace/src/app.py',
    is_new_file: false,
    unified_diff: [
      '--- a/workspace/src/app.py',
      '+++ b/workspace/src/app.py',
      '@@ -1,2 +1,2 @@',
      ' keep = True',
      '-old_line = 1',
      '+new_line = 2',
    ].join('\n'),
    additions: 1,
    deletions: 1,
    old_content: 'keep = True\nold_line = 1\n',
    new_content: 'keep = True\nnew_line = 2\n',
    ...overrides,
  };
}

describe('CodeDiffViewer', () => {
  it('renders file name and change badges in header', () => {
    render(<CodeDiffViewer diff={makeDiff()} />);
    expect(screen.getByText('app.py')).toBeInTheDocument();
    expect(screen.getByText('+1')).toBeInTheDocument();
    expect(screen.getByText('-1')).toBeInTheDocument();
  });

  it('renders new-file badge when is_new_file', () => {
    render(<CodeDiffViewer diff={makeDiff({ is_new_file: true })} />);
    expect(screen.getByText('new')).toBeInTheDocument();
  });

  it('renders react-diff-viewer when full content is available', async () => {
    const { container } = render(<CodeDiffViewer diff={makeDiff()} />);
    // react-diff-viewer 输出 <table> 结构;v4 行渲染是异步的,waitFor 等待
    expect(container.querySelector('table')).not.toBeNull();
    await waitFor(() => {
      expect(container.textContent).toContain('new_line');
      expect(container.textContent).toContain('old_line');
    });
  });

  it('falls back to colored unified view when full content missing', () => {
    const diff = makeDiff();
    delete diff.old_content;
    delete diff.new_content;
    render(<CodeDiffViewer diff={diff} />);
    const pre = screen.getByTestId('code-diff-unified');
    expect(pre.textContent).toContain('-old_line = 1');
    expect(pre.textContent).toContain('+new_line = 2');
    expect(pre.textContent).toContain('@@ -1,2 +1,2 @@');
  });

  it('shows skipped note when capture was skipped', () => {
    render(
      <CodeDiffViewer diff={{ path: '/big.bin', skipped: 'file_too_large' }} />,
    );
    expect(screen.getByText(/file_too_large/)).toBeInTheDocument();
  });

  it('shows truncation notice when diff_truncated', () => {
    render(<CodeDiffViewer diff={makeDiff({ diff_truncated: true })} />);
    expect(screen.getByText(/已截断/)).toBeInTheDocument();
  });

  it('collapses body on header click', () => {
    const { container } = render(<CodeDiffViewer diff={makeDiff()} />);
    const button = screen.getByRole("button", { name: "toggle-diff" });
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(container.querySelector('table')).not.toBeNull();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('table')).toBeNull();
  });

  it('respects defaultExpanded=false', () => {
    const { container } = render(
      <CodeDiffViewer diff={makeDiff()} defaultExpanded={false} />,
    );
    expect(container.querySelector('table')).toBeNull();
    expect(screen.getByRole("button", { name: "toggle-diff" })).toHaveAttribute('aria-expanded', 'false');
  });
});
