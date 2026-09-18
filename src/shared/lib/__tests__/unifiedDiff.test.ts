// src/shared/lib/__tests__/unifiedDiff.test.ts
//
// right-panel R3 批次 A: unified diff 生成器单测 —— 增/删/改/相等/空输入/
// hunk 拆分，输出格式与 splitDiffParser 的输入约定对齐。

import { describe, expect, it } from 'vitest';

import { parseUnifiedDiff } from '../../../widgets/chat/changes/splitDiffParser';
import { unifiedDiff } from '../unifiedDiff';

describe('unifiedDiff', () => {
  it('两文本相同返回空串', () => {
    expect(unifiedDiff('a\nb', 'a\nb')).toBe('');
  });

  it('纯末尾追加：+ 行与正确行号', () => {
    const d = unifiedDiff('a\nb', 'a\nb\nc');
    expect(d).toContain('@@ -1,2 +1,3 @@');
    expect(d).toContain(' a');
    expect(d).toContain('+c');
    // 除文件头（--- 旧版本）外不得有删除行
    expect(d.split('\n').filter((l) => l.startsWith('-'))).toHaveLength(1);
    // 可被 parseUnifiedDiff 消费
    expect(parseUnifiedDiff(d).length).toBeGreaterThan(0);
  });

  it('纯删除：- 行', () => {
    const d = unifiedDiff('a\nb\nc', 'a\nc');
    expect(d).toContain('-b');
    expect(d).toContain('@@ -1,3 +1,2 @@');
  });

  it('修改：成对 -/+（modify 行）', () => {
    const d = unifiedDiff('old line\nkeep', 'new line\nkeep');
    expect(d).toContain('-old line');
    expect(d).toContain('+new line');
    expect(d).toContain(' keep');
  });

  it('空原文本 → @@ -0,0 头', () => {
    const d = unifiedDiff('', 'a\nb');
    expect(d).toContain('@@ -0,0 +1,2 @@');
    expect(d).toContain('+a');
  });

  it('相距较远的两处变更拆成两个 hunk', () => {
    const pad: string[] = [];
    for (let i = 0; i < 20; i++) pad.push(`l${i}`);
    const oldText = ['X1', ...pad, 'X2'].join('\n');
    const newText = ['Y1', ...pad, 'Y2'].join('\n');
    const d = unifiedDiff(oldText, newText);
    const hunkCount = d.split('\n').filter((l) => l.startsWith('@@')).length;
    expect(hunkCount).toBe(2);
  });

  it('parser 兼容：任意 diff 都能被 parseUnifiedDiff 解析出行', () => {
    const d = unifiedDiff('h\nello', 'hello\nworld');
    const rows = parseUnifiedDiff(d);
    expect(rows.length).toBeGreaterThan(0);
  });
});
