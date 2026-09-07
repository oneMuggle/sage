// src/widgets/chat/changes/__tests__/diffHunks.test.ts
// U19: 前端 hunk 切分与后端 workspace_revert.split_hunks 同构性测试。
import { describe, it, expect } from 'vitest';

import { splitDiffHunks } from '../diffHunks';

const TWO_HUNK_DIFF = [
  'diff --git a/app.py b/app.py',
  'index 1111111..2222222 100644',
  '--- a/app.py',
  '+++ b/app.py',
  '@@ -1,4 +1,5 @@',
  ' line1',
  '+line1-added',
  ' line2',
  ' line3',
  ' line4',
  '@@ -10,4 +11,5 @@',
  ' line10',
  '+line11-added',
  ' line12',
  ' line13',
  '',
].join('\n');

describe('splitDiffHunks', () => {
  it('切出两个 hunk 且都带文件头', () => {
    const hunks = splitDiffHunks(TWO_HUNK_DIFF);
    expect(hunks).toHaveLength(2);
    for (const hunk of hunks) {
      expect(hunk.header).toContain('diff --git a/app.py');
      expect(hunk.summary.startsWith('@@')).toBe(true);
    }
    expect(hunks[0].summary).toBe('@@ -1,4 +1,5 @@');
    expect(hunks[1].summary).toBe('@@ -10,4 +11,5 @@');
  });

  it('header + body 拼回等于原文 hunk 段', () => {
    const hunks = splitDiffHunks(TWO_HUNK_DIFF);
    for (const hunk of hunks) {
      expect(hunk.header + hunk.body).toContain('@@');
      expect((hunk.header + hunk.body).split('\n').length).toBeGreaterThan(3);
    }
    expect(hunks[0].body).toContain('+line1-added');
    expect(hunks[1].body).toContain('+line11-added');
    expect(hunks[0].body).not.toContain('line11-added');
    // header + body 与后端 split_hunks 输出同构（含 @@ 行）
    expect(hunks[0].header + hunks[0].body).toBe(
      'diff --git a/app.py b/app.py\nindex 1111111..2222222 100644\n--- a/app.py\n+++ b/app.py\n@@ -1,4 +1,5 @@\n line1\n+line1-added\n line2\n line3\n line4\n',
    );
  });

  it('空 diff / 无 hunk 返回空数组', () => {
    expect(splitDiffHunks('')).toEqual([]);
    expect(splitDiffHunks('diff --git a/f b/f\nindex 111..222 100644\n')).toEqual([]);
  });

  it('无 diff --git 头的裸 hunk 也能切出', () => {
    const hunks = splitDiffHunks('@@ -1,1 +1,1 @@\n-a\n+b\n');
    expect(hunks).toHaveLength(1);
    expect(hunks[0].summary).toBe('@@ -1,1 +1,1 @@');
    expect(hunks[0].body).toBe('@@ -1,1 +1,1 @@\n-a\n+b\n');
  });
});
