/**
 * UX-IA Round 2：ContextMeter 弹层中的「本轮注入的上下文」列表。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ContextSourceList } from '../ContextMeter';

describe('ContextSourceList', () => {
  it('renders nothing for old records without sources', () => {
    const { container } = render(<ContextSourceList sources={undefined} />);
    expect(container).toBeEmptyDOMElement();
    render(<ContextSourceList sources={[]} />);
    expect(screen.queryByTestId('context-meter-sources')).toBeNull();
  });

  it('lists each source with a Chinese label and formatted size, in backend order', () => {
    render(
      <ContextSourceList
        sources={[
          { key: 'sage_md', tokens: 1234, count: 1 },
          { key: 'memory', tokens: 300, count: 1 },
          { key: 'future_key', tokens: 5, count: 0 },
        ]}
      />,
    );
    const rows = screen.getAllByTestId(/^context-source-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual([
      'context-source-sage_md',
      'context-source-memory',
      'context-source-future_key',
    ]);
    expect(rows[0]).toHaveTextContent('项目指令 (SAGE.md)');
    expect(rows[0]).toHaveTextContent('1.2k');
    expect(rows[1]).toHaveTextContent('记忆召回');
    // 未知 key 回退显示原始 key，前端不因后端新增来源而崩
    expect(rows[2]).toHaveTextContent('future_key');
    expect(screen.queryByTestId('context-meter-trimmed-notice')).toBeNull();
    expect(screen.queryByTestId(/^context-source-trimmed-/)).toBeNull();
  });

  it('flags sources truncated by the injection budget', () => {
    render(
      <ContextSourceList
        sources={[
          { key: 'sage_md', tokens: 900, count: 1 },
          { key: 'project_materials', tokens: 400, count: 1, trimmed: 2500 },
          { key: 'memory', tokens: 200, count: 1, trimmed: 300 },
        ]}
      />,
    );
    expect(screen.getByTestId('context-meter-trimmed-notice')).toHaveTextContent('2.8k');
    expect(screen.getByTestId('context-source-trimmed-project_materials')).toHaveTextContent(
      '已截断 2.5k',
    );
    expect(screen.getByTestId('context-source-trimmed-memory')).toHaveTextContent('已截断 300');
    expect(screen.queryByTestId('context-source-trimmed-sage_md')).toBeNull();
  });
});
