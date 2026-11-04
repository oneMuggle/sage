/**
 * P2 (2026-11-04): useGlobalFileDrop —— 页面级整页拖放。
 */
import { act, fireEvent, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { COMPOSER_DROP_EVENT, useGlobalFileDrop } from '../useGlobalFileDrop';

function makeFile(name: string, type = 'text/plain'): File {
  return new File(['x'], name, { type });
}

function fileDragEvent(file: File) {
  return {
    dataTransfer: {
      types: ['Files'],
      files: [file],
    },
  };
}

describe('useGlobalFileDrop', () => {
  it('拖到 composer 外 → 派发 COMPOSER_DROP_EVENT 并带上文件', () => {
    const { result } = renderHook(() =>
      useGlobalFileDrop({ composerSelector: '[data-testid="composer"]' }),
    );
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    const file = makeFile('a.txt');
    act(() => {
      fireEvent.drop(document.body, fileDragEvent(file));
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(onDrop).toHaveBeenCalledTimes(1);
    const detail = (onDrop.mock.calls[0][0] as CustomEvent<{ files: File[] }>).detail;
    expect(detail.files).toEqual([file]);
    expect(result.current.isDragOver).toBe(false);
  });

  it('拖到 composer 内 → 不派发事件（交给 composer 自己的 onDrop）', () => {
    const composer = document.createElement('div');
    composer.setAttribute('data-testid', 'composer');
    document.body.appendChild(composer);
    const { result } = renderHook(() =>
      useGlobalFileDrop({ composerSelector: '[data-testid="composer"]' }),
    );
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    act(() => {
      fireEvent.drop(composer, fileDragEvent(makeFile('b.txt')));
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    document.body.removeChild(composer);
    expect(onDrop).not.toHaveBeenCalled();
    expect(result.current.isDragOver).toBe(false);
  });

  it('dragenter 含文件 → isDragOver=true；dragleave → false', () => {
    const { result } = renderHook(() =>
      useGlobalFileDrop({ composerSelector: '[data-testid="composer"]' }),
    );
    const file = makeFile('c.txt');
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(file));
    });
    expect(result.current.isDragOver).toBe(true);
    act(() => {
      fireEvent.dragLeave(document.body, fileDragEvent(file));
    });
    expect(result.current.isDragOver).toBe(false);
  });

  it('纯文本拖拽（types 不含 Files）→ 不进入拖放态、不派发事件', () => {
    const { result } = renderHook(() =>
      useGlobalFileDrop({ composerSelector: '[data-testid="composer"]' }),
    );
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    act(() => {
      fireEvent.dragEnter(document.body, {
        dataTransfer: { types: ['text/plain'], files: [] },
      });
      fireEvent.drop(document.body, {
        dataTransfer: { types: ['text/plain'], files: [] },
      });
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(result.current.isDragOver).toBe(false);
    expect(onDrop).not.toHaveBeenCalled();
  });

  it('卸载后不再监听', () => {
    const { unmount } = renderHook(() =>
      useGlobalFileDrop({ composerSelector: '[data-testid="composer"]' }),
    );
    unmount();
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    act(() => {
      fireEvent.drop(document.body, fileDragEvent(makeFile('d.txt')));
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(onDrop).not.toHaveBeenCalled();
  });
});
