/**
 * r112: useFileUpload 单元测试——图片/文件分流、删除、粘贴与拖放。
 */
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CHAT_DOCUMENT_EXTENSIONS,
  MAX_ATTACHMENT_COUNT,
  MAX_ATTACHMENT_SIZE,
  formatFileUploadJson,
  formatFileUploadSummary,
  preflightAttachment,
  useFileUpload,
} from '../useFileUpload';

function makeFile(name: string, type: string, size = 100) {
  return { name, size, type } as File;
}

/** FileReader 在 jsdom 读 data URL 异步且依赖实现——mock 之，同步触发 onload */
function mockFileReader(readAs: 'dataurl' = 'dataurl') {
  const readers: Array<{ onload: (() => void) | null; result: string | null }> = [];
  const OriginalFileReader = global.FileReader;
  class FakeFileReader {
    onload: (() => void) | null = null;
    result: string | null = null;
    readAsDataURL() {
      readers.push(this);
      this.result = 'data:fake';
    }
    readAsText() {
      readers.push(this);
      this.result = 'text';
    }
  }
  vi.stubGlobal('FileReader', FakeFileReader);
  return () => {
    for (const r of readers) r.onload?.();
    void OriginalFileReader;
    void readAs;
  };
}

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('addFile 走 files 通道并带上 dataUrl', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('a.txt', 'text/plain'));
    });
    act(() => {
      flush();
    });
    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].name).toBe('a.txt');
    expect(result.current.files[0].dataUrl).toBe('data:fake');
  });

  it('addImage 走 images 通道', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addImage(makeFile('pic.png', 'image/png'));
    });
    act(() => {
      flush();
    });
    expect(result.current.images).toHaveLength(1);
    expect(result.current.files).toHaveLength(0);
  });

  it('addImage 拒绝非图片类型', () => {
    mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addImage(makeFile('a.txt', 'text/plain'));
    });
    expect(result.current.images).toHaveLength(0);
  });

  it('handleDrop 按类型分流图片与文件', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    const dt = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      dataTransfer: { files: [makeFile('b.png', 'image/png'), makeFile('c.md', 'text/markdown')] },
    } as unknown as React.DragEvent;
    act(() => {
      result.current.handleDrop(dt);
    });
    act(() => {
      flush();
    });
    expect(result.current.images.map((f) => f.name)).toEqual(['b.png']);
    expect(result.current.files.map((f) => f.name)).toEqual(['c.md']);
    expect(dt.preventDefault).toHaveBeenCalled();
  });

  it('handlePaste 同时接收图片与文档文件', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    const imgItem = {
      kind: 'file',
      type: 'image/png',
      getAsFile: () => makeFile('p.png', 'image/png'),
    };
    const docItem = {
      kind: 'file',
      type: 'text/plain',
      getAsFile: () => makeFile('d.txt', 'text/plain'),
    };
    const textItem = { kind: 'string', type: 'text/plain', getAsFile: () => null };
    const clipboardData = { items: [imgItem, docItem, textItem] };
    const evt = { preventDefault: vi.fn(), clipboardData } as unknown as React.ClipboardEvent;
    act(() => {
      result.current.handlePaste(evt);
    });
    act(() => {
      flush();
    });
    expect(result.current.images.map((f) => f.name)).toEqual(['p.png']);
    expect(result.current.files.map((f) => f.name)).toEqual(['d.txt']);
    expect(evt.preventDefault).toHaveBeenCalled();
  });

  it('removeFile / removeImage 按下标删除', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('a.txt', 'text/plain'));
      result.current.addFile(makeFile('b.txt', 'text/plain'));
      result.current.addImage(makeFile('p.png', 'image/png'));
    });
    act(() => {
      flush();
    });
    act(() => {
      result.current.removeFile(0);
      result.current.removeImage(0);
    });
    expect(result.current.files.map((f) => f.name)).toEqual(['b.txt']);
    expect(result.current.images).toHaveLength(0);
  });

  it('clearAll 清空文件与图片', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('a.txt', 'text/plain'));
      result.current.addImage(makeFile('p.png', 'image/png'));
    });
    act(() => {
      flush();
    });
    act(() => {
      result.current.clearAll();
    });
    expect(result.current.files).toHaveLength(0);
    expect(result.current.images).toHaveLength(0);
  });

  it('handleDragOver 置 isDragOver 且不触发默认行为', () => {
    const { result } = renderHook(() => useFileUpload());
    const evt = { preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as React.DragEvent;
    act(() => {
      result.current.handleDragOver(evt);
    });
    expect(result.current.isDragOver).toBe(true);
    expect(evt.preventDefault).toHaveBeenCalled();
  });

  // ── P2 (2026-11-04): 预检 ──────────────────────────────────────────────

  it('addFile 超过大小上限 → status=failed, reason=oversize', () => {
    mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('huge.py', 'text/plain', MAX_ATTACHMENT_SIZE + 1));
    });
    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].status).toBe('failed');
    expect(result.current.files[0].reason).toBe('oversize');
  });

  it('addFile 不支持的扩展名 → status=failed, reason=unsupported', () => {
    mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('evil.exe', 'application/octet-stream'));
    });
    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].status).toBe('failed');
    expect(result.current.files[0].reason).toBe('unsupported');
  });

  it('addFile 超过数量上限 → status=failed, reason=count_exceeded', () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      for (let i = 0; i < MAX_ATTACHMENT_COUNT; i += 1) {
        result.current.addFile(makeFile(`a${i}.txt`, 'text/plain'));
      }
    });
    act(() => {
      flush();
    });
    expect(result.current.files).toHaveLength(MAX_ATTACHMENT_COUNT);
    act(() => {
      result.current.addFile(makeFile('overflow.txt', 'text/plain'));
    });
    expect(result.current.files).toHaveLength(MAX_ATTACHMENT_COUNT + 1);
    const overflow = result.current.files[MAX_ATTACHMENT_COUNT];
    expect(overflow.status).toBe('failed');
    expect(overflow.reason).toBe('count_exceeded');
  });

  it('addFile 同名文件替换旧条目（静默）', () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      result.current.addFile(makeFile('dup.txt', 'text/plain'));
    });
    act(() => {
      flush();
    });
    const firstId = result.current.files[0].id;
    act(() => {
      result.current.addFile(makeFile('dup.txt', 'text/plain'));
    });
    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].id).not.toBe(firstId);
    expect(result.current.files[0].status).not.toBe('failed');
  });

  it('images 和 files 共享计数上限', () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    act(() => {
      // 9 张图片 + 1 个文档 = 10
      for (let i = 0; i < MAX_ATTACHMENT_COUNT - 1; i += 1) {
        result.current.addImage(makeFile(`p${i}.png`, 'image/png'));
      }
      result.current.addFile(makeFile('d.txt', 'text/plain'));
    });
    act(() => {
      flush();
    });
    expect(result.current.images).toHaveLength(MAX_ATTACHMENT_COUNT - 1);
    expect(result.current.files).toHaveLength(1);
    act(() => {
      result.current.addFile(makeFile('extra.txt', 'text/plain'));
    });
    expect(result.current.files).toHaveLength(2);
    expect(result.current.files[1].status).toBe('failed');
    expect(result.current.files[1].reason).toBe('count_exceeded');
  });
});

describe('preflightAttachment', () => {
  it('oversize / unsupported / duplicate / count_exceeded 各返回对应 reason', () => {
    const big = makeFile('big.txt', 'text/plain', MAX_ATTACHMENT_SIZE + 1);
    expect(preflightAttachment(big, [], 'file', 0)).toMatchObject({
      ok: false,
      reason: 'oversize',
    });
    const bad = makeFile('a.exe', 'application/octet-stream');
    expect(preflightAttachment(bad, [], 'file', 0)).toMatchObject({
      ok: false,
      reason: 'unsupported',
    });
    const dup = makeFile('a.txt', 'text/plain');
    expect(preflightAttachment(dup, [{ name: 'a.txt' }], 'file', 0)).toMatchObject({
      ok: false,
      reason: 'duplicate',
    });
    expect(preflightAttachment(dup, [], 'file', MAX_ATTACHMENT_COUNT)).toMatchObject({
      ok: false,
      reason: 'count_exceeded',
    });
    expect(preflightAttachment(dup, [], 'file', 0)).toEqual({ ok: true });
  });
});

describe('CHAT_DOCUMENT_EXTENSIONS', () => {
  it('包含基础文本格式', () => {
    for (const ext of ['txt', 'md', 'csv']) {
      expect(CHAT_DOCUMENT_EXTENSIONS.has(ext)).toBe(true);
    }
  });

  it('包含常见编程语言', () => {
    for (const ext of ['py', 'js', 'ts', 'java', 'go', 'rs', 'cpp']) {
      expect(CHAT_DOCUMENT_EXTENSIONS.has(ext)).toBe(true);
    }
  });

  it('包含二进制文档格式', () => {
    for (const ext of ['pdf', 'docx', 'xlsx']) {
      expect(CHAT_DOCUMENT_EXTENSIONS.has(ext)).toBe(true);
    }
  });

  it('不包含图片格式（图片走 images 通道）', () => {
    for (const ext of ['png', 'jpg', 'gif', 'webp']) {
      expect(CHAT_DOCUMENT_EXTENSIONS.has(ext)).toBe(false);
    }
  });
});

describe('formatFileUploadSummary / formatFileUploadJson', () => {
  it('formats file upload state summary and JSON payload', () => {
    expect(formatFileUploadSummary([], [], false)).toBe('upload: 0 files · 0 images · 0 B · idle');
    const files = [{ name: 'doc.md', size: 120, type: 'text/markdown' }];
    const images = [{ name: 'pic.png', size: 380, type: 'image/png' }];
    expect(formatFileUploadSummary(files, images, true)).toBe(
      'upload: 1 files · 1 images · 500 B · drag-over',
    );
    const payload = JSON.parse(formatFileUploadJson(files, images, true));
    expect(payload).toEqual({
      fileCount: 1,
      imageCount: 1,
      totalBytes: 500,
      isDragOver: true,
      supportedExtensionCount: CHAT_DOCUMENT_EXTENSIONS.size,
    });
  });
});
