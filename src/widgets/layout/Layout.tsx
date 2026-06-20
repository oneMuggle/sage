import { Outlet } from 'react-router-dom';

import { Sidebar } from './Sidebar';

export function Layout() {
  return (
    <div className="flex h-screen bg-bg">
      {/* 跳到主内容链接 (a11y) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-blue-600 focus:text-white focus:rounded"
      >
        跳到主内容
      </a>

      {/* 侧边栏 */}
      <Sidebar />

      {/* 主内容区 */}
      <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
