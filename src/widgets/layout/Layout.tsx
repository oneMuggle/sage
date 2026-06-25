import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { useResizableSidebar } from '../../shared/lib/useResizableSidebar';

import { ResizeDivider } from './ResizeDivider';
import { Sidebar } from './Sidebar';
import { TitlebarActions } from './TitlebarActions';

export function Layout() {
  const { width, onMouseDown } = useResizableSidebar();
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  );
  const [mobileOpen, setMobileOpen] = useState(false);

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
            <Sidebar />
          </div>
        </>
      ) : (
        <>
          {/* 桌面端侧边栏（可调整宽度） */}
          <Sidebar width={width} />
          <ResizeDivider onMouseDown={onMouseDown} />
        </>
      )}

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部标题栏（导航操作） */}
        <div className="flex items-center px-4 h-10 border-b border-border bg-bg-subtle">
          <TitlebarActions />
        </div>
        <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
