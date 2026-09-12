// src/widgets/chat/__tests__/splitDiffParser.test.ts
//
// P1-3.8: 验证 unified diff → 分栏行的纯函数解析器。
// 覆盖: 空输入 / 单 hunk 上下文 / 修改配对 / 纯增纯删 / 多 hunk / 文件头。
import { describe, expect, it } from 'vitest';

import { parseUnifiedDiff } from '../changes/splitDiffParser';

describe('parseUnifiedDiff', () => {
  it('returns [] for empty input', () => {
    expect(parseUnifiedDiff('')).toEqual([]);
    expect(parseUnifiedDiff(undefined as unknown as string)).toEqual([]);
  });

  it('parses context lines with incrementing line numbers on both sides', () => {
    const diff = [
      'diff --git a/x.ts b/x.ts',
      '@@ -1,3 +1,3 @@',
      ' first',
      ' second',
      ' third',
    ].join('\n');
    const rows = parseUnifiedDiff(diff);
    const contexts = rows.filter((r) => r.kind === 'context');
    expect(contexts).toHaveLength(3);
    expect(contexts[0]).toMatchObject({
      oldLine: 1,
      newLine: 1,
      oldText: 'first',
      newText: 'first',
    });
    expect(contexts[2]).toMatchObject({
      oldLine: 3,
      newLine: 3,
      oldText: 'third',
      newText: 'third',
    });
  });

  it('pairs one-to-one -/+ changes as modify rows', () => {
    const diff = ['@@ -1,2 +1,2 @@', ' ctx', '-old line', '+new line', ' ctx2'].join('\n');
    const rows = parseUnifiedDiff(diff);
    const modify = rows.find((r) => r.kind === 'modify');
    // ctx consumes old=1/new=1, so modify lands on old=2/new=2
    expect(modify).toMatchObject({
      kind: 'modify',
      oldLine: 2,
      newLine: 2,
      oldText: 'old line',
      newText: 'new line',
    });
  });

  it('emits unpaired removes as remove and unpaired adds as add', () => {
    const diff = ['@@ -1,3 +1,2 @@', '-removed A', '-removed B', '+added only one', ' ctx'].join(
      '\n',
    );
    const rows = parseUnifiedDiff(diff);
    const removes = rows.filter((r) => r.kind === 'remove');
    const adds = rows.filter((r) => r.kind === 'add');
    const modifies = rows.filter((r) => r.kind === 'modify');
    // One pair + one leftover remove
    expect(modifies).toHaveLength(1);
    expect(modifies[0]).toMatchObject({ oldText: 'removed A', newText: 'added only one' });
    expect(removes).toHaveLength(1);
    expect(removes[0]).toMatchObject({ kind: 'remove', oldText: 'removed B', newText: '' });
    expect(adds).toHaveLength(0);
  });

  it('emits pure add (no paired remove) correctly', () => {
    const diff = ['@@ -1 +1,2 @@', ' ctx', '+only added'].join('\n');
    const rows = parseUnifiedDiff(diff);
    const adds = rows.filter((r) => r.kind === 'add');
    expect(adds).toHaveLength(1);
    expect(adds[0]).toMatchObject({ oldLine: null, oldText: '', newText: 'only added' });
    expect(typeof adds[0].newLine).toBe('number');
  });

  it('emits file-header lines as header kind', () => {
    const diff = [
      'diff --git a/x.ts b/x.ts',
      'index abc..def 100644',
      '--- a/x.ts',
      '+++ b/x.ts',
      '@@ -1 +1 @@',
      '-old',
      '+new',
    ].join('\n');
    const rows = parseUnifiedDiff(diff);
    const headers = rows.filter((r) => r.kind === 'header');
    // 4 file headers + 1 hunk header
    expect(headers).toHaveLength(5);
    expect(headers[0].oldText).toContain('diff --git');
    expect(headers[4].oldText).toMatch(/^@@/);
  });

  it('handles multiple hunks with independent line numbering', () => {
    const diff = [
      '@@ -1,2 +1,2 @@',
      '-a',
      '+A',
      ' ctx1',
      '@@ -10,2 +10,2 @@',
      '-b',
      '+B',
      ' ctx2',
    ].join('\n');
    const rows = parseUnifiedDiff(diff);
    const modifies = rows.filter((r) => r.kind === 'modify');
    expect(modifies).toHaveLength(2);
    // Second hunk starts at line 10 on both sides
    expect(modifies[1]).toMatchObject({ oldLine: 10, newLine: 10, oldText: 'b', newText: 'B' });
  });

  it('parses hunk header with no trailing comma (single-line count omitted)', () => {
    // git emits "@@ -L +L @@" when N=1, omitting the ,1
    const diff = '@@ -5 +7 @@\n-old\n+new\n';
    const rows = parseUnifiedDiff(diff);
    const modify = rows.find((r) => r.kind === 'modify');
    expect(modify).toMatchObject({ oldLine: 5, newLine: 7 });
  });
});
