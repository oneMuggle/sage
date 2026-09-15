import { describe, expect, it } from 'vitest';

import { hasUnclosedFence, MIN_CHUNKED_LENGTH, splitStableChunks } from '../markdownChunks';

describe('splitStableChunks', () => {
  it('returns no stable chunks for short content', () => {
    const r = splitStableChunks('a\n\nb');
    expect(r.stable).toEqual([]);
    expect(r.live).toBe('a\n\nb');
  });

  it('splits at blank lines for long content, preserving everything', () => {
    const para = '这是一段足够长的段落。'.repeat(60); // > MIN_CHUNKED_LENGTH
    const content = `${para}\n\n${para}\n\n${para}`;
    const r = splitStableChunks(content);
    expect(r.stable.length).toBeGreaterThan(0);
    // 切分无损: 稳定块 + live 尾块拼回原文
    expect(r.stable.join('') + r.live).toBe(content);
  });

  it('does not split inside a code fence', () => {
    const para = '段落文本。'.repeat(120);
    const content = `${para}\n\n\`\`\`python\nx = 1\n\ny = 2\n\`\`\`\n\n尾段。${para}`;
    const r = splitStableChunks(content);
    const rejoined = r.stable.join('') + r.live;
    expect(rejoined).toBe(content);
    // 围栏内的空行绝不能成为切分点 → 含 ``` 的块必须完整
    const fenceChunk = [...r.stable, r.live].find((c) => c.includes('```python'));
    expect(fenceChunk).toBeDefined();
    expect(fenceChunk).toContain('y = 2');
  });

  it('does not split right before a list item (GFM 松散列表保护)', () => {
    const para = '普通段落文本。'.repeat(120);
    const content = `${para}\n\n- 第一项\n\n- 第二项\n\n尾段。${para}`;
    const r = splitStableChunks(content);
    const rejoined = r.stable.join('') + r.live;
    expect(rejoined).toBe(content);
    // 列表起点前不切 → 至少 "- 第一项" 与其所属上下文同块
    const listChunk = [...r.stable, r.live].find((c) => c.includes('- 第一项'));
    expect(listChunk).toBeDefined();
    expect(listChunk!.startsWith('普通段落')).toBe(true);
  });

  it('keeps MIN_CHUNKED_LENGTH contract', () => {
    expect(MIN_CHUNKED_LENGTH).toBeGreaterThan(0);
  });
});

describe('hasUnclosedFence', () => {
  it('detects a single unclosed fence', () => {
    expect(hasUnclosedFence('前置\n```python\nprint(1')).toBe(true);
  });

  it('passes with paired fences', () => {
    expect(hasUnclosedFence('```python\nprint(1)\n```\n后置')).toBe(false);
  });

  it('passes with no fences', () => {
    expect(hasUnclosedFence('普通文本，没有代码。')).toBe(false);
  });
});
