// src/features/chat/__tests__/useConfirmedFilePaths.test.ts
// 文本兜底识别（feat/file-reference-preview M5）：候选提取、remark 插件转换、
// 批量确认 hook（workspaceApi mock）。
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkspaceResolveResult } from '../../../shared/api/workspaceApi';
import {
  __clearFileRefResolutionCache,
  extractFileRefCandidates,
  looksLikeFilePath,
  remarkFileRefLinks,
  useConfirmedFilePaths,
} from '../useConfirmedFilePaths';

const mockResolveFiles =
  vi.fn<(sessionId: string, paths: string[]) => Promise<WorkspaceResolveResult>>();

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    resolveFiles: (sessionId: string, paths: string[]) => mockResolveFiles(sessionId, paths),
  },
}));

beforeEach(() => {
  mockResolveFiles.mockReset();
  __clearFileRefResolutionCache();
});

describe('extractFileRefCandidates', () => {
  it('提取带分隔符的路径与已知扩展名裸文件名', () => {
    const text = '已写入 src/App.tsx 和 docs/report.md，另见 report.md。';
    expect(extractFileRefCandidates(text)).toEqual(['src/App.tsx', 'docs/report.md', 'report.md']);
  });

  it('忽略 URL、纯单词与未知扩展名', () => {
    const text = '访问 https://example.com/a.md 或 v1.2 版本，见 foo.xyz';
    expect(extractFileRefCandidates(text)).toEqual([]);
  });

  it('Windows 路径可识别', () => {
    expect(looksLikeFilePath('C:\\work\\a\\b.md')).toBe(true);
    expect(looksLikeFilePath('src\\utils\\x.ts')).toBe(true);
  });

  it('去重且上限 50', () => {
    const text = Array.from({ length: 60 }, (_, i) => `f${i}.md`).join(' ');
    expect(extractFileRefCandidates(text)).toHaveLength(50);
  });
});

describe('remarkFileRefLinks', () => {
  it('仅把已确认路径的 text 节点替换为 link', () => {
    const tree = {
      type: 'root',
      children: [
        {
          type: 'paragraph',
          children: [{ type: 'text', value: '已写入 src/App.tsx 与 missing.ts，完成。' }],
        },
        {
          type: 'code',
          value: 'src/App.tsx',
        },
      ],
    };

    remarkFileRefLinks(new Set(['src/App.tsx']))()(tree);

    const paragraph = tree.children[0] as { children: Array<Record<string, unknown>> };
    const link = paragraph.children.find((n) => n.type === 'link');
    expect(link).toBeDefined();
    expect(link?.url).toBe('src/App.tsx');
    const plainText = paragraph.children
      .filter((n) => n.type === 'text')
      .map((n) => n.value)
      .join('');
    expect(plainText).toContain('missing.ts');
    // code 节点不处理
    expect((tree.children[1] as Record<string, unknown>).value).toBe('src/App.tsx');
  });
});

describe('useConfirmedFilePaths', () => {
  it('批量确认后只返回存在的路径', async () => {
    mockResolveFiles.mockResolvedValue({
      results: [
        { path: 'src/App.tsx', exists: true, kind: 'code' },
        { path: 'missing.ts', exists: false, kind: null },
      ],
    });

    const { result } = renderHook(() =>
      useConfirmedFilePaths('见 src/App.tsx 与 missing.ts', 's1', true),
    );

    await waitFor(() => expect(result.current.has('src/App.tsx')).toBe(true));
    expect(result.current.has('missing.ts')).toBe(false);
    expect(mockResolveFiles).toHaveBeenCalledWith('s1', ['src/App.tsx', 'missing.ts']);
  });

  it('流式期间（enabled=false）不发请求', () => {
    const { result } = renderHook(() => useConfirmedFilePaths('见 src/App.tsx', 's1', false));
    expect(result.current.size).toBe(0);
    expect(mockResolveFiles).not.toHaveBeenCalled();
  });
});
