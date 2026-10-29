import { describe, expect, it } from 'vitest';

import { buildMessageDisplayMeta, extractFileRefs } from '../messageDisplayMeta';

describe('extractFileRefs', () => {
  it('extracts @path tokens containing a slash or extension', () => {
    const refs = extractFileRefs('请参考 @src/App.tsx 和 @README.md，谢谢');
    expect(refs).toEqual([
      { path: 'src/App.tsx', name: 'App.tsx' },
      { path: 'README.md', name: 'README.md' },
    ]);
  });

  it('ignores plain mentions without a slash or extension', () => {
    expect(extractFileRefs('@张三 看一下')).toEqual([]);
  });

  it('dedupes repeated refs and strips trailing punctuation', () => {
    const refs = extractFileRefs('@a/b.py，再看 @a/b.py。');
    expect(refs).toEqual([{ path: 'a/b.py', name: 'b.py' }]);
  });

  it('splits adjacent mentions separated by whitespace', () => {
    const refs = extractFileRefs('@src/a.ts @src/b.ts');
    expect(refs).toEqual([
      { path: 'src/a.ts', name: 'a.ts' },
      { path: 'src/b.ts', name: 'b.ts' },
    ]);
  });

  it('excludes @ from capture so adjacent mentions without space yield only the first', () => {
    // `@src/a@src/b` — the capture class stops at the second `@`, so only `src/a`
    // is captured. The second mention lacks a valid boundary (preceded by `a`)
    // and is not extracted. This is preferable to the old behavior of capturing
    // the entire `src/a@src/b` as one malformed path.
    const refs = extractFileRefs('@src/a@src/b');
    expect(refs).toEqual([{ path: 'src/a', name: 'a' }]);
  });

  it('strips trailing quotes from paths', () => {
    const refs = extractFileRefs('look at "@src/App.tsx" please');
    expect(refs).toEqual([{ path: 'src/App.tsx', name: 'App.tsx' }]);
  });
});

describe('buildMessageDisplayMeta', () => {
  it('returns undefined when the message has no references', () => {
    expect(buildMessageDisplayMeta({ content: '普通消息' })).toBeUndefined();
  });

  it('collects attachments, file refs, office refs and knowledge refs', () => {
    const meta = buildMessageDisplayMeta({
      content: '分析 @reports/q3.pdf',
      attachments: [{ name: 'data.xlsx', size: 2048, type: 'application/vnd.ms-excel' }],
      images: [{ name: 'chart.png', size: 512, type: 'image/png' }],
      officeRefs: [{ docId: 'doc-1', docType: 'pdf', filename: 'q3.pdf' }],
      knowledgeRefs: [{ id: 'k1', title: '写作规范' }],
    });

    expect(meta?.attachments).toEqual([
      { name: 'data.xlsx', size: 2048, type: 'application/vnd.ms-excel' },
    ]);
    expect(meta?.images).toEqual([{ name: 'chart.png', size: 512, type: 'image/png' }]);
    expect(meta?.file_refs).toEqual([{ path: 'reports/q3.pdf', name: 'q3.pdf' }]);
    expect(meta?.office_refs).toEqual([{ doc_id: 'doc-1', doc_type: 'pdf', filename: 'q3.pdf' }]);
    expect(meta?.knowledge_refs).toEqual([{ id: 'k1', title: '写作规范' }]);
  });

  it('strips dataUrl from attachments and images', () => {
    const meta = buildMessageDisplayMeta({
      content: '',
      attachments: [{ name: 'a.pdf', size: 1, type: 'application/pdf', dataUrl: 'data:...' }],
      images: [{ name: 'b.png', size: 1, type: 'image/png', dataUrl: 'data:...' }],
    });
    expect(meta?.attachments?.[0]).not.toHaveProperty('dataUrl');
    expect(meta?.images?.[0]).not.toHaveProperty('dataUrl');
  });
});
