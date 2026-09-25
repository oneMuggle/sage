// src/widgets/chat/TerminalPanel.tsx
//
// Phase 3 (2026-09-25): ZCode 启发的底部终端面板（VS Code 风格）。
// 在 Chat 页底部展示一个可拖拽调整高度的终端面板，内嵌 @xterm/xterm 渲染，
// 经 window.electronAPI.pty IPC 桥与主进程 node-pty 子进程通信。
//
// 生命周期：
// - 面板打开 + 组件挂载 → 调用 pty.create() 启动 shell
// - pty.data 事件 → terminal.write(data) 渲染到屏幕
// - xterm onData → pty.write({ id, data }) 发送用户输入
// - 面板关闭 / 组件卸载 → pty.destroy() 终止子进程
//
// Web 端降级：window.electronAPI.pty 不存在时显示"仅桌面端可用"提示。

import '@xterm/xterm/css/xterm.css';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import { ChevronDown, ChevronUp, X } from 'lucide-react';
import { memo, useCallback, useEffect, useRef } from 'react';

import {
  useTerminalPanelStore,
  MIN_HEIGHT,
  MAX_HEIGHT,
} from '../../features/terminal-panel/terminalPanelStore';

function TerminalPanelInner() {
  const open = useTerminalPanelStore((s) => s.open);
  const height = useTerminalPanelStore((s) => s.height);
  const setHeight = useTerminalPanelStore((s) => s.setHeight);
  const setOpen = useTerminalPanelStore((s) => s.setOpen);
  const ptyId = useTerminalPanelStore((s) => s.ptyId);
  const setPtyId = useTerminalPanelStore((s) => s.setPtyId);
  const setPtyError = useTerminalPanelStore((s) => s.setPtyError);
  const clearPty = useTerminalPanelStore((s) => s.clearPty);
  const ptyError = useTerminalPanelStore((s) => s.ptyError);

  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const isDraggingRef = useRef(false);
  const startYRef = useRef(0);
  const startHeightRef = useRef(0);

  // 创建/销毁 PTY 会话
  useEffect(() => {
    if (!open) return;
    const bridge = typeof window !== 'undefined' ? window.electronAPI?.pty : undefined;
    if (!bridge) {
      setPtyError('终端面板仅桌面端可用');
      return;
    }

    let cancelled = false;

    const init = async () => {
      // 初始化 xterm（仅一次）
      if (!termRef.current && containerRef.current) {
        const term = new Terminal({
          cursorBlink: true,
          fontSize: 13,
          fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
          theme: {
            background: 'transparent',
          },
        });
        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);
        termRef.current = term;
        fitAddonRef.current = fitAddon;
        term.open(containerRef.current);
        // 延迟 fit 一帧让容器布局稳定
        requestAnimationFrame(() => {
          try {
            fitAddon.fit();
          } catch {
            // 容器尺寸为零时 fit 可能失败，忽略
          }
        });
      }

      if (ptyId) return; // 已有活跃会话，跳过重建
      const result = await bridge.create({
        cols: fitAddonRef.current ? undefined : 80,
        rows: fitAddonRef.current ? undefined : 24,
      });
      if (cancelled) {
        // 组件已卸载，立即销毁刚创建的 PTY
        if ('id' in result) await bridge.destroy({ id: result.id });
        return;
      }
      if ('error' in result) {
        setPtyError(result.error);
        return;
      }
      setPtyId(result.id);
    };

    void init();

    return () => {
      cancelled = true;
    };
    // 只在 open 从 false → true 时触发；ptyId 变化不应重建
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 监听 PTY 输出 → 写入 xterm
  useEffect(() => {
    if (!ptyId) return;
    const bridge = typeof window !== 'undefined' ? window.electronAPI?.pty : undefined;
    if (!bridge) return;

    const unsubData = bridge.onData(({ id, data }) => {
      if (id === ptyId && termRef.current) {
        termRef.current.write(data);
      }
    });
    const unsubExit = bridge.onExit(({ id }) => {
      if (id === ptyId) {
        termRef.current?.write('\r\n[进程已退出]\r\n');
        clearPty();
      }
    });

    return () => {
      unsubData();
      unsubExit();
    };
  }, [ptyId, clearPty]);

  // xterm 用户输入 → PTY
  useEffect(() => {
    if (!ptyId || !termRef.current) return;
    const bridge = typeof window !== 'undefined' ? window.electronAPI?.pty : undefined;
    if (!bridge) return;

    const disposable = termRef.current.onData((data) => {
      void bridge.write({ id: ptyId, data });
    });
    return () => disposable.dispose();
  }, [ptyId]);

  // 面板尺寸变化时 fit + resize PTY
  useEffect(() => {
    if (!open || !termRef.current || !fitAddonRef.current || !containerRef.current) return;
    const raf = requestAnimationFrame(() => {
      try {
        fitAddonRef.current!.fit();
        const cols = termRef.current!.cols;
        const rows = termRef.current!.rows;
        if (ptyId) {
          window.electronAPI?.pty?.resize({ id: ptyId, cols, rows });
        }
      } catch {
        // fit 偶发失败不影响功能
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [open, height, ptyId]);

  // 组件卸载时销毁 PTY 进程 + xterm 实例
  useEffect(() => {
    return () => {
      if (ptyId) {
        window.electronAPI?.pty?.destroy({ id: ptyId }).catch(() => {});
      }
      termRef.current?.dispose();
      termRef.current = null;
      fitAddonRef.current = null;
    };
    // 只在卸载时执行；ptyId 变化时不需要重新销毁旧的（由 onExit 清掉）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 拖拽调整高度
  const onMouseDownResize = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDraggingRef.current = true;
      startYRef.current = e.clientY;
      startHeightRef.current = height;

      const onMouseMove = (ev: MouseEvent) => {
        if (!isDraggingRef.current) return;
        // 面板在底部，拖拽向上 = 增大高度（deltaY 为负）
        const delta = startYRef.current - ev.clientY;
        setHeight(startHeightRef.current + delta);
      };
      const onMouseUp = () => {
        isDraggingRef.current = false;
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      };
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    },
    [height, setHeight],
  );

  const handleClose = useCallback(() => {
    setOpen(false);
  }, [setOpen]);

  if (!open) return null;

  return (
    <div
      className="flex-shrink-0 border-t border-border bg-surface flex flex-col"
      style={{ height }}
      data-testid="terminal-panel"
    >
      {/* 顶部拖拽手柄 */}
      <div
        className="h-1.5 cursor-row-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
        onMouseDown={onMouseDownResize}
        role="separator"
        aria-orientation="horizontal"
        aria-label="拖拽调整终端高度（上下方向键微调）"
        aria-valuemin={MIN_HEIGHT}
        aria-valuemax={MAX_HEIGHT}
        aria-valuenow={height}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            setHeight(height + 24);
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            setHeight(height - 24);
          }
        }}
        data-testid="terminal-panel-resize-handle"
      />
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-3 py-1 border-b border-border flex-shrink-0">
        <span className="text-xs font-medium text-text-secondary">终端</span>
        <div className="flex items-center gap-1">
          <button
            className="p-1 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
            onClick={() => setHeight(height === MAX_HEIGHT ? MIN_HEIGHT : MAX_HEIGHT)}
            title={height === MAX_HEIGHT ? '还原高度' : '最大化'}
            aria-label={height === MAX_HEIGHT ? '还原终端高度' : '最大化终端'}
          >
            {height === MAX_HEIGHT ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronUp className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            className="p-1 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
            onClick={handleClose}
            title="关闭终端面板 (Ctrl+`)"
            aria-label="关闭终端面板"
            data-testid="terminal-panel-close"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {/* xterm 容器 */}
      {ptyError ? (
        <div className="flex-1 flex items-center justify-center text-xs text-text-muted px-4 text-center">
          {ptyError}
        </div>
      ) : (
        <div
          ref={containerRef}
          className="flex-1 min-h-0 p-1 overflow-hidden"
          data-testid="terminal-panel-xterm"
        />
      )}
    </div>
  );
}

/** memo 防止 Chat 流式渲染期间无谓重渲染 */
export const TerminalPanel = memo(TerminalPanelInner);
