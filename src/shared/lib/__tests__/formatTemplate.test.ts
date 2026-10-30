import { describe, expect, it, vi } from 'vitest';

import { fillTemplate } from '../formatTemplate';

describe('fillTemplate', () => {
  it('replaces every occurrence of a placeholder', () => {
    expect(fillTemplate('{a}-{a}-{b}', { a: 'x', b: 2 })).toBe('x-x-2');
  });

  it('leaves unknown placeholders untouched', () => {
    expect(fillTemplate('hello {name}', {})).toBe('hello {name}');
  });

  // onSelect 类型允许 Promise —— 占位断言避免未使用参数告警
  it('tolerates extra vars', () => {
    expect(fillTemplate('x', { unused: vi.fn() as unknown as string })).toBe('x');
  });
});
