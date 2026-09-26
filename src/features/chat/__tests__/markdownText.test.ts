// 对话阅读体验第二轮：Markdown → 可读纯文本（B1 朗读与 B4 会话内查找共用）。
import { describe, expect, it } from 'vitest';

import { markdownToPlainText } from '../markdownText';

describe('markdownToPlainText', () => {
  it('strips inline and block markup but keeps the visible text', () => {
    const md = [
      '## 标题 **加粗**',
      '> 引用一行',
      '- [x] 已完成任务',
      '1. 第一步：见 [文档](https://example.com/doc)',
      '![示意图](a.png) 与 <https://sage.dev>',
      '~~删除~~ 与 *强调* 以及 _斜体_',
      '---',
    ].join('\n');
    expect(markdownToPlainText(md)).toBe(
      [
        '标题 加粗',
        '引用一行',
        '已完成任务',
        '第一步：见 文档',
        '示意图 与 https://sage.dev',
        '删除 与 强调 以及 斜体',
      ].join('\n'),
    );
  });

  it('protects code from markup stripping and keeps snake_case identifiers', () => {
    const md =
      '调用 `fn(**kwargs)` 时 my_var_name 不变\n\n```python\ndef f(*args, **kw):\n    return a_b or c\n```';
    expect(markdownToPlainText(md)).toBe(
      '调用 fn(**kwargs) 时 my_var_name 不变\n\ndef f(*args, **kw):\n    return a_b or c',
    );
  });

  it('replaces fenced code blocks when a replacement is given (read aloud)', () => {
    const md = '前文\n```js\nconsole.log(1)\n```\n后文';
    expect(markdownToPlainText(md, { codeBlockReplacement: '此处代码已略过。' })).toBe(
      '前文\n\n此处代码已略过。\n\n后文',
    );
  });

  it('treats an unclosed fence (still streaming) as code until the end', () => {
    const md = '说明\n```ts\nconst a = **b**;';
    expect(markdownToPlainText(md, { codeBlockReplacement: '[code]' })).toBe('说明\n\n[code]');
    expect(markdownToPlainText(md)).toBe('说明\n\nconst a = **b**;');
  });

  it('flattens tables into space-separated cells', () => {
    const md = '| 名称 | 说明 |\n| --- | :---: |\n| `a|b` | **粗** |';
    expect(markdownToPlainText(md)).toBe('名称 说明\n\na|b 粗');
  });
});
