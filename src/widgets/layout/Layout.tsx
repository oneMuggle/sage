import { useEffect, useState } from 'react';
import { Suspense } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { ErrorBoundary } from '../../app/providers/ErrorBoundary';
import { useResizableSidebar } from '../../shared/lib/useResizableSidebar';
import { PageSkeleton } from '../../shared/ui';

import { ResizeDivider } from './ResizeDivider';
import { Sidebar } from './Sidebar';
import { Titlebar } from './Titlebar';

export function Layout() {
  const { width, isDragging, onMouseDown } = useResizableSidebar();
  const location = useLocation();
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
            <ErrorBoundary
              fallback={(error, reset) => (
                <div className="p-4 text-error">
                  Sidebar 错误: {error.message}
                  <button onClick={reset} className="ml-2 text-primary">
                    重试
                  </button>
                </div>
              )}
            >
              <Sidebar />
            </ErrorBoundary>
          </div>
        </>
      ) : (
        <>
          {/* P1-3.6 (UI 优化方案 2026-09-13): 折叠态 → 56px icon rail（Claude 风格）。
               不再 translate-x-full 隐藏，而是始终保留窄栏在流中，
               显示品牌 logo + 导航图标，会话列表/sections 隐藏。
               2026-09-13 P0: 折叠/展开宽度加 200ms 过渡；拖拽调宽时禁用
               过渡（isDragging），否则拖拽跟手性会被动画拖慢。 */}
          <div
            className={`flex-shrink-0 overflow-hidden ${isDragging ? '' : 'transition-[width] duration-200 ease-in-out'}`}
            style={{ width: collapsed ? 56 : width }}
          >
            <ErrorBoundary
              fallback={(error, reset) => (
                <div className="w-64 p-4 text-error">
                  Sidebar 错误: {error.message}
                  <button onClick={reset} className="ml-2 text-primary">
                    重试
                  </button>
                </div>
              )}
            >
              <Sidebar width={collapsed ? 56 : width} collapsed={collapsed} />
            </ErrorBoundary>
          </div>

          {!collapsed && <ResizeDivider onMouseDown={onMouseDown} />}
        </>
      )}

      <div className="flex-1 flex flex-col overflow-hidden">
        <Titlebar />
        <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
          <ErrorBoundary
            fallback={(error, reset) => (
              <div className="flex items-center justify-center h-full text-error">
                Page 错误: {error.message}
                <button onClick={reset} className="ml-2 text-primary">
                  重试
                </button>
              </div>
            )}
          >
            {/* 2026-09-13 P0: 路由切换过渡 — 按 pathname key 触发入场动画
                (fade + 6px 上移，进入式无退出动画)。search 变化不换 key，
                /chat?session=x 深链不会重挂 Chat。 */}
            {/* 内层 Suspense: lazy 页面 chunk 加载期间显示页面骨架，
                Sidebar 保持不动；此前的空 div fallback 挂在 App.tsx 外层，
                会把整个布局（含 Sidebar）替换成空白。 */}
            <div
              key={location.pathname}
              className="flex-1 flex flex-col overflow-hidden animate-route-enter"
            >
              <Suspense fallback={<PageSkeleton />}>
                <Outlet />
              </Suspense>
            </div>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
