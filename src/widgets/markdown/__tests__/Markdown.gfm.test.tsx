/**
 * GFM 扩展渲染测试。
 *
 * 覆盖：
 * - 表格（<table> 渲染 + sticky 容器）
 * - 任务列表（checkbox 渲染）
 * - 删除线（~~text~~）
 * - 自动链接（autolinks）
 * - tableToTsv 工具函数
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Markdown, tableToTsv } from '../index';

describe('Markdown GFM — tables', () => {
  it('renders a table', () => {
    const src = `| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |`;
    const { container } = render(<Markdown content={src} />);
    const table = container.querySelector('table');
    expect(table).toBeTruthy();
    const rows = table!.querySelectorAll('tr');
    // header + 2 body rows
    expect(rows.length).toBe(3);
    const headerCells = rows[0].querySelectorAll('th');
    expect(headerCells.length).toBe(2);
    expect(headerCells[0].textContent).toBe('A');
    expect(headerCells[1].textContent).toBe('B');
  });

  it('wraps table in .md-table-wrap with clampable height', () => {
    const src = `| X |
|---|
| 1 |`;
    const { container } = render(<Markdown content={src} tableMaxHeight="10rem" />);
    const wrap = container.querySelector('.md-table-wrap');
    expect(wrap).toBeTruthy();
  });

  it('adds copy button with data-testid', () => {
    const src = `| A |
|---|
| 1 |`;
    render(<Markdown content={src} />);
    const btn = screen.getByTestId('markdown-table-copy');
    expect(btn).toBeTruthy();
  });
});

describe('Markdown GFM — task lists', () => {
  it('renders checked and unchecked checkboxes', () => {
    const src = `- [ ] todo
- [x] done
- normal item`;
    const { container } = render(<Markdown content={src} />);
    const checkboxes = container.querySelectorAll('input[type="checkbox"]');
    expect(checkboxes.length).toBe(2);
    expect(checkboxes[0].getAttribute('checked')).toBeNull();
    expect(checkboxes[1].getAttribute('checked')).toBe('');
  });
});

describe('Markdown GFM — strikethrough', () => {
  it('renders <del> for ~~text~~', () => {
    const src = 'This is ~~deleted~~ text';
    const { container } = render(<Markdown content={src} />);
    const del = container.querySelector('del');
    expect(del).toBeTruthy();
    expect(del!.textContent).toBe('deleted');
  });
});

describe('Markdown GFM — autolinks', () => {
  it('renders bare URLs as links', () => {
    const src = 'Visit https://example.com today';
    const { container } = render(<Markdown content={src} />);
    const links = container.querySelectorAll('a');
    // remark-gfm auto-links the URL
    const hrefs = Array.from(links).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.com');
  });
});

describe('tableToTsv', () => {
  it('converts a simple table element to TSV', () => {
    const table = document.createElement('table');
    table.innerHTML = `
      <thead><tr><th>A</th><th>B</th></tr></thead>
      <tbody><tr><td>1</td><td>2</td></tr></tbody>
    `;
    document.body.appendChild(table);
    try {
      const result = tableToTsv(table);
      expect(result).toBe('A\tB\n1\t2');
    } finally {
      document.body.removeChild(table);
    }
  });

  it('strips leading/trailing whitespace in cells', () => {
    const table = document.createElement('table');
    table.innerHTML = '<tbody><tr><td>  hello  </td><td>world</td></tr></tbody>';
    document.body.appendChild(table);
    try {
      const result = tableToTsv(table);
      expect(result).toBe('hello\tworld');
    } finally {
      document.body.removeChild(table);
    }
  });
});
