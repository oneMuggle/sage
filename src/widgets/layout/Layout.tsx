import { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { useResizableSidebar } from '../../shared/lib/useResizableSidebar';

import { ResizeDivider } from './ResizeDivider';
import { Sidebar } from './Sidebar';
import { Titlebar } from './Titlebar';

export function Layout() {
  // DIAGNOSTIC: log at each hook boundary so we can localize which hook throws
  // (alpha.25 confirmed: blue LAYOUT MOUNTED marker doesn't render → throw in
  // one of the hooks below). Logs are captured by electron/main.ts console-message
  // handler and written to the main process log file.
  console.warn('[sage] Layout 1: function entered');

  const { width, onMouseDown } = useResizableSidebar();
  console.warn('[sage] Layout 2: useResizableSidebar OK');

  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  );
  console.warn('[sage] Layout 3: useState isMobile OK');

  const [mobileOpen, setMobileOpen] = useState(false);
  console.warn('[sage] Layout 4: useState mobileOpen OK');

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
  console.warn('[sage] Layout 5: useEffect OK, about to return');

  return (
    <>
      {/* DIAGNOSTIC MARKER (alpha.26): green instead of blue. If you see this
          green bar, all 4 hooks (useResizableSidebar + 2 useState + useEffect)
          succeeded and Layout's return statement executed. The throw (if any)
          is in the JSX children below (Sidebar/Titlebar/Outlet). If you don't
          see it, check the main process log for the last "[sage] Layout N:" line
          — that's the last successful step before the throw. */}
      <h1
        data-testid="sage-layout-hooks-ok"
        style={{
          position: 'fixed',
          top: 80,
          left: 0,
          right: 0,
          zIndex: 999980,
          background: 'green',
          color: 'white',
          padding: '8px 12px',
          fontFamily: 'sans-serif',
          fontSize: 14,
          fontWeight: 'bold',
          textAlign: 'center',
        }}
      >
        LAYOUT FULL HOOKS — 如果看到这条绿条,所有 hook 执行成功,throw 在 JSX children
      </h1>
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
        <Titlebar />
        <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
    </>
  );
}
