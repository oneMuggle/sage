/**
 * 2026-11-15：useGlobalFileDrop 成为文件拖放的唯一入口。
 *
 * 不再按 composer 内/外分流：所有含文件的 drop 统一派发 COMPOSER_DROP_EVENT。
 * 旧实现"卡外拦截 + stopPropagation、卡内交给 React onDrop"的双轨判定，
 * 在 drop 目标是输入卡内覆盖层时会让 composer 的 onDrop 永不执行，
 * 导致"拖放文件到此处"遮罩卡死 —— 本测试集锁定修复后的单轨语义。
 */
import { act, fireEvent, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { COMPOSER_DROP_EVENT, useGlobalFileDrop } from '../useGlobalFileDrop';

function makeFile(name: string, type = 'text/plain'): File {
  return new File(['x'], name, { type });
}

function fileDragEvent(file: File) {
  return { dataTransfer: { types: ['Files'], files: [file] } };
}

describe('useGlobalFileDrop', () => {
  it('drop（任意位置，含 composer 内）→ 派发 COMPOSER_DROP_EVENT 并复位遮罩', () => {
    const { result } = renderHook(() => useGlobalFileDrop());
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    const file = makeFile('a.txt');
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(file));
    });
    expect(result.current.isDragOver).toBe(true);
    act(() => {
      fireEvent.drop(document.body, fileDragEvent(file));
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(onDrop).toHaveBeenCalledTimes(1);
    const detail = (onDrop.mock.calls[0][0] as CustomEvent<{ files: File[] }>).detail;
    expect(detail.files).toEqual([file]);
    expect(result.current.isDragOver).toBe(false);
  });

  it('含文件的 drop 必须 preventDefault（避免 Electron 导航到本地文件）', () => {
    renderHook(() => useGlobalFileDrop());
    // fireEvent 返回"事件是否未被取消"—— false 表示 preventDefault 已生效。
    const notPrevented = fireEvent.drop(document.body, fileDragEvent(makeFile('b.txt')));
    expect(notPrevented).toBe(false);
  });

  it('dragenter 后 dragend（取消拖拽、未 drop）→ 遮罩复位', () => {
    const { result } = renderHook(() => useGlobalFileDrop());
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(makeFile('c.txt')));
    });
    expect(result.current.isDragOver).toBe(true);
    act(() => {
      fireEvent.dragEnd(document.body);
    });
    expect(result.current.isDragOver).toBe(false);
  });

  it('拖出窗口（dragleave 且 relatedTarget 为 null）→ 遮罩复位', () => {
    const { result } = renderHook(() => useGlobalFileDrop());
    act(() => {
      fireEvent.dragEnter(document.body, fileDragEvent(makeFile('d.txt')));
    });
    expect(result.current.isDragOver).toBe(true);
    act(() => {
      fireEvent.dragLeave(document.body, { relatedTarget: null });
    });
    expect(result.current.isDragOver).toBe(false);
  });

  it('纯文本拖拽（types 不含 Files）→ 不进入拖放态、不派发事件、不拦截', () => {
    const { result } = renderHook(() => useGlobalFileDrop());
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    let notPrevented = false;
    act(() => {
      fireEvent.dragEnter(document.body, {
        dataTransfer: { types: ['text/plain'], files: [] },
      });
      notPrevented = fireEvent.drop(document.body, {
        dataTransfer: { types: ['text/plain'], files: [] },
      });
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(result.current.isDragOver).toBe(false);
    expect(onDrop).not.toHaveBeenCalled();
    expect(notPrevented).toBe(true);
  });

  it('卸载后不再监听', () => {
    const { unmount } = renderHook(() => useGlobalFileDrop());
    unmount();
    const onDrop = vi.fn();
    window.addEventListener(COMPOSER_DROP_EVENT, onDrop);
    act(() => {
      fireEvent.drop(document.body, fileDragEvent(makeFile('e.txt')));
    });
    window.removeEventListener(COMPOSER_DROP_EVENT, onDrop);
    expect(onDrop).not.toHaveBeenCalled();
  });
});
