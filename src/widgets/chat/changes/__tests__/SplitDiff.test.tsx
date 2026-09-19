// src/widgets/chat/changes/__tests__/SplitDiff.test.tsx
//
// right-panel R6: 分栏 diff 词级行内高亮测试 —— modify 行应把行内真正
// 变化的片段染深色（strong span），相同上下文与 remove/add 行不受影响。
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SplitDiff } from '../SplitDiff';

const DIFF = [
  'diff --git a/app.ts b/app.ts',
  '--- a/app.ts',
  '+++ b/app.ts',
  '@@ -1,3 +1,3 @@',
  ' const a = 1;',
  '-const name = "alice";',
  '+const name = "bob";',
  '-const removed = true;',
  '+const added = false;',
].join('\n');

/** 按 textContent 精确找 td（词级切分后整行文本分布在多个 span 里） */
function cellWithText(text: string): HTMLElement {
  const cell = screen.getByText(
    (_, el) => el?.tagName === 'TD' && el.textContent === text,
  );
  return cell as HTMLElement;
}

describe('SplitDiff — 词级行内高亮 (right-panel R6)', () => {
  it('modify 行渲染词级变化片段（strong span 嵌在行内）', () => {
    render(<SplitDiff diff={DIFF} />);

    // 整行文本仍完整（分布在 td 的多个 span 上）
    expect(cellWithText('const name = "alice";')).toBeInTheDocument();
    expect(cellWithText('const name = "bob";')).toBeInTheDocument();

    // 行内变化片段被拆出染深色：公共前后缀剥离后 mid = alice/bob
    const alice = screen.getByText('alice');
    expect(alice).toHaveClass('bg-red-300/70');
    const bob = screen.getByText('bob');
    expect(bob).toHaveClass('bg-green-300/70');
  });

  it('第二组 modify 行同样整体渲染（词级切分不影响整行文本匹配）', () => {
    render(<SplitDiff diff={DIFF} />);
    expect(cellWithText('const removed = true;')).toBeInTheDocument();
    expect(cellWithText('const added = false;')).toBeInTheDocument();
  });

  it('context 行两侧文本相同且无强染', () => {
    render(<SplitDiff diff={DIFF} />);
    expect(screen.getAllByText('const a = 1;')).toHaveLength(2);
  });

  it('空 diff 渲染空表格', () => {
    const { container } = render(<SplitDiff diff="" />);
    expect(container.querySelector('tbody')?.children).toHaveLength(0);
  });

  it('P1-6: 大 diff 渐进渲染 —— 首屏 400 行,加载更多按钮追加至全部', () => {
    // 3 行文件头 + 1 行 hunk 头 + 496 行上下文 = 500 行
    const body = Array.from({ length: 496 }, (_, i) => ` line ${i}`).join('\n');
    const big = ['diff --git a/big.ts b/big.ts', '--- a/big.ts', '+++ b/big.ts', '@@ -1,496 +1,496 @@', body].join('\n');
    const { container } = render(<SplitDiff diff={big} />);

    // 首屏 400 行 + 1 行哨兵/按钮
    expect(screen.getByTestId('split-diff-more')).toBeInTheDocument();
    expect(container.querySelectorAll('tbody tr')).toHaveLength(401);
    expect(screen.getByTestId('split-diff-more-button').textContent).toContain('400/500');

    // 点击追加至全部,按钮消失
    fireEvent.click(screen.getByTestId('split-diff-more-button'));
    expect(container.querySelectorAll('tbody tr')).toHaveLength(500);
    expect(screen.queryByTestId('split-diff-more')).not.toBeInTheDocument();
  });

  it('P1-6: 小 diff 不出现加载更多（低于阈值全量渲染）', () => {
    const { container } = render(<SplitDiff diff={DIFF} />);
    expect(screen.queryByTestId('split-diff-more')).not.toBeInTheDocument();
    expect(container.querySelectorAll('tbody tr')).toHaveLength(7);
  });
});
