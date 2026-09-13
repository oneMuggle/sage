/**
 * P3: wiki MarkdownPreview 补 remark-gfm —— GFM 表格语法应渲染为 table。
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MarkdownPreview } from '../MarkdownPreview';

describe('MarkdownPreview GFM (P3)', () => {
  it('renders GFM tables', () => {
    const { container } = render(
      <MarkdownPreview content={'| a | b |\n| --- | --- |\n| 1 | 2 |'} />,
    );
    expect(container.querySelector('table')).not.toBeNull();
    expect(container.querySelector('td')?.textContent).toBe('1');
  });

  it('renders strikethrough via GFM', () => {
    const { container } = render(<MarkdownPreview content="~~废弃~~" />);
    expect(container.querySelector('del')).not.toBeNull();
  });
});
