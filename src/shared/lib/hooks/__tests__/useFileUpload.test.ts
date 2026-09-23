/**
 * r112: useFileUpload 单元测试——图片/文件分流、删除、粘贴与拖放。
 */
import { act, fireEvent, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useFileUpload } from '../useFileUpload';

function makeFile(name: string, type: string) {
  return { name, size: 100, type } as File;
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

  it('handlePaste 只取剪贴板中的图片项', async () => {
    const flush = mockFileReader();
    const { result } = renderHook(() => useFileUpload());
    const imgItem = { kind: 'file', type: 'image/png', getAsFile: () => makeFile('p.png', 'image/png') };
    const textItem = { kind: 'string', type: 'text/plain', getAsFile: () => null };
    const clipboardData = { items: [imgItem, textItem] };
    const evt = { preventDefault: vi.fn(), clipboardData } as unknown as React.ClipboardEvent;
    act(() => {
      result.current.handlePaste(evt);
    });
    act(() => {
      flush();
    });
    expect(result.current.images.map((f) => f.name)).toEqual(['p.png']);
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
});
