// src/widgets/chat/preview/__tests__/HtmlPreviewHost.test.tsx
//
// HTML 预览统一宿主测试 —— 覆盖工具条、停止/重跑、错误桥过滤、全屏、
// 复制/下载，以及 srcDoc 回退路径（jsdom 下无 window.electronAPI.preview）。
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { PREVIEW_BRIDGE_CHANNEL } from '../../../../shared/lib/htmlPreviewBridge';
import { HtmlPreviewHost } from '../HtmlPreviewHost';

function getFrame(): HTMLIFrameElement {
  const frame = document.querySelector('iframe');
  if (!frame) throw new Error('iframe not rendered');
  return frame as HTMLIFrameElement;
}

describe('HtmlPreviewHost', () => {
  beforeEach(() => {
    // jsdom 无 navigator.clipboard / URL.createObjectURL —— 补桩
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = vi.fn(() => 'blob:mock-url');
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('渲染工具条与预览 iframe', () => {
    render(<HtmlPreviewHost html="<p>hi</p>" name="demo.html" />);
    expect(screen.getByTestId('html-preview-host')).toBeInTheDocument();
    expect(screen.getByTestId('html-preview-rerun')).toBeInTheDocument();
    expect(screen.getByTestId('html-preview-stop')).toBeInTheDocument();
    expect(screen.getByTestId('html-preview-fullscreen-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('html-preview-copy')).toBeInTheDocument();
    expect(screen.getByTestId('html-preview-download')).toBeInTheDocument();
    const frame = getFrame();
    expect(frame.getAttribute('data-testid')).toBe('html-preview-frame');
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
  });

  it('无 Electron 桥时退回 srcDoc 内联预览', () => {
    render(<HtmlPreviewHost html="<p>inline</p>" name="demo.html" />);
    const frame = getFrame();
    expect(frame.getAttribute('src')).toBeNull();
    expect(frame.getAttribute('srcdoc')).toContain('inline');
    // 桥接脚本已注入渲染副本
    expect(frame.getAttribute('srcdoc')).toContain(PREVIEW_BRIDGE_CHANNEL);
  });

  it('自定义 frameTestId 透传到 iframe', () => {
    render(<HtmlPreviewHost html="<p>x</p>" name="a.html" frameTestId="html-artifact-preview" />);
    expect(screen.getByTestId('html-artifact-preview')).toBeInTheDocument();
  });

  it('reloadKey 变化时重挂载 iframe（srcDoc 同值也要刷新）', () => {
    const { rerender } = render(<HtmlPreviewHost html="<p>same</p>" name="a.html" reloadKey={0} />);
    const before = getFrame();
    rerender(<HtmlPreviewHost html="<p>same</p>" name="a.html" reloadKey={1} />);
    const after = getFrame();
    expect(after).not.toBe(before);
  });

  it('停止后卸载 iframe 并显示占位，重新执行后恢复', () => {
    render(<HtmlPreviewHost html="<p>x</p>" name="a.html" />);
    fireEvent.click(screen.getByTestId('html-preview-stop'));
    expect(screen.getByTestId('html-preview-stopped')).toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();

    fireEvent.click(screen.getByTestId('html-preview-rerun'));
    expect(screen.queryByTestId('html-preview-stopped')).toBeNull();
    expect(document.querySelector('iframe')).not.toBeNull();
  });

  it('错误桥消息命中时展示错误横幅并可清除', async () => {
    render(<HtmlPreviewHost html="<p>x</p>" name="a.html" />);
    const frame = getFrame();
    const win = frame.contentWindow;
    expect(win).toBeTruthy();

    fireEvent(
      window,
      new MessageEvent('message', {
        data: { channel: PREVIEW_BRIDGE_CHANNEL, kind: 'error', message: 'boom', detail: 'a.js:1' },
        source: win,
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('html-preview-errors')).toBeInTheDocument();
    });
    expect(screen.getByText('boom')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('html-preview-errors-clear'));
    expect(screen.queryByTestId('html-preview-errors')).toBeNull();
  });

  it('忽略来源不匹配的 postMessage 与非本通道消息', async () => {
    render(<HtmlPreviewHost html="<p>x</p>" name="a.html" />);
    // 通道不匹配
    fireEvent(
      window,
      new MessageEvent('message', {
        data: { channel: 'other-channel', kind: 'error', message: 'nope' },
        source: getFrame().contentWindow,
      }),
    );
    // 来源不匹配（伪造的 window）
    fireEvent(
      window,
      new MessageEvent('message', {
        data: { channel: PREVIEW_BRIDGE_CHANNEL, kind: 'error', message: 'nope2' },
        source: window,
      }),
    );
    expect(screen.queryByTestId('html-preview-errors')).toBeNull();
  });

  it('全屏切换通过 portal 渲染覆盖层', () => {
    render(<HtmlPreviewHost html="<p>x</p>" name="a.html" />);
    expect(screen.queryByTestId('html-preview-fullscreen')).toBeNull();
    fireEvent.click(screen.getByTestId('html-preview-fullscreen-toggle'));
    expect(screen.getByTestId('html-preview-fullscreen')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('html-preview-fullscreen-toggle'));
    expect(screen.queryByTestId('html-preview-fullscreen')).toBeNull();
  });

  it('复制按钮写入的是用户原文（不含桥接脚本）', () => {
    render(<HtmlPreviewHost html="<p>copy-me</p>" name="a.html" />);
    fireEvent.click(screen.getByTestId('html-preview-copy'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('<p>copy-me</p>');
  });

  it('下载按钮生成 blob URL 并指定文件名', () => {
    render(<HtmlPreviewHost html="<p>dl</p>" name="report" />);
    fireEvent.click(screen.getByTestId('html-preview-download'));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
  });
});
