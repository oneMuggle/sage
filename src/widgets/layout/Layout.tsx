import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { ErrorBoundary } from '../../app/providers/ErrorBoundary';
import { useResizableSidebar } from '../../shared/lib/useResizableSidebar';

import { ResizeDivider } from './ResizeDivider';
import { Sidebar } from './Sidebar';
import { Titlebar } from './Titlebar';

export function Layout() {
  const { width, onMouseDown } = useResizableSidebar();
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  // 监听窗口大小变化
  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) {
        setMobileOpen(false);
      }
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Toggle collapse with keyboard shortcut (Ctrl+B / Cmd+B)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        setCollapsed((prev) => !prev);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="flex h-screen bg-bg">
      {/* 跳到主内容链接 (a11y) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-blue-600 focus:text-white focus:rounded"
      >
        跳到主内容
      </a>

      {isMobile ? (
        <>
          {/* 移动端遮罩 */}
          {mobileOpen && (
            <div
              className="fixed inset-0 z-30 bg-overlay transition-opacity"
              onClick={() => setMobileOpen(false)}
            />
          )}
          {/* 移动端侧边栏（覆盖层） */}
          <div
            className={`fixed z-40 h-screen transition-transform duration-200 ${
              mobileOpen ? 'translate-x-0' : '-translate-x-full'
            }`}
          >
            <ErrorBoundary fallback={(error, reset) => (
              <div className="p-4 text-error">
                Sidebar 错误: {error.message}
                <button onClick={reset} className="ml-2 text-primary">重试</button>
              </div>
            )}>
              <Sidebar />
            </ErrorBoundary>
          </div>
        </>
      ) : (
        <>
          {/* P1-3.6 (UI 优化方案 2026-09-13): 折叠态 → 56px icon rail（Claude 风格）。
               不再 translate-x-full 隐藏，而是始终保留窄栏在流中，
               显示品牌 logo + 导航图标，会话列表/sections 隐藏。 */}
          <div
            className={collapsed ? 'flex-shrink-0' : 'relative'}
            style={collapsed ? { width: 56 } : undefined}
          >
            <ErrorBoundary fallback={(error, reset) => (
              <div className="w-64 p-4 text-error">
                Sidebar 错误: {error.message}
                <button onClick={reset} className="ml-2 text-primary">重试</button>
              </div>
            )}>
              <Sidebar width={collapsed ? 56 : width} collapsed={collapsed} />
            </ErrorBoundary>
          </div>

          {!collapsed && <ResizeDivider onMouseDown={onMouseDown} />}
        </>
      )}

      <div className="flex-1 flex flex-col overflow-hidden">
        <Titlebar />
        <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
          <ErrorBoundary fallback={(error, reset) => (
            <div className="flex items-center justify-center h-full text-error">
              Page 错误: {error.message}
              <button onClick={reset} className="ml-2 text-primary">重试</button>
            </div>
          )}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}