import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { ErrorBoundary } from './app/providers/ErrorBoundary';
import { NavHistoryProvider } from './app/providers/NavHistoryProvider';
import { loadCurrentSessionId } from './entities/session/storage';
import { Settings } from './pages';
import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import { Orchestration } from './pages/Orchestration';
import { ScheduledTasks } from './pages/ScheduledTasks';
import Skills from './pages/Skills';
import { Welcome } from './pages/Welcome';
import { useStore } from './shared/lib/store';
import { CommandPalette } from './widgets/command';
import { Layout } from './widgets/layout';

// Phase 7: gate /chat by currentSessionId; fall back to /welcome when missing.
function ChatRoute() {
  const currentSessionId = useStore((s) => s.currentSessionId);
  if (!currentSessionId) {
    return <Navigate to="/welcome" replace />;
  }
  return <Chat />;
}

function App() {
  const [commandOpen, setCommandOpen] = useState(false);

  useEffect(() => {
    loadCurrentSessionId().then((id) => {
      if (id) {
        useStore.getState().setCurrentSessionId(id);
      }
    });
  }, []);

  // 全局快捷键 Ctrl+K / Cmd+K 打开命令面板
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <>
      {/* DIAGNOSTIC BANNER — red bar so we can confirm App mounted */}
      <div
        data-testid="sage-app-mounted"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 999999,
          background: 'red',
          color: 'white',
          padding: '8px 12px',
          fontFamily: 'sans-serif',
          fontSize: 14,
          fontWeight: 'bold',
        }}
      >
        APP MOUNTED — 如果你看到这条红条,App 组件正常挂载
      </div>
      <ErrorBoundary>
        {/* MINIMAL TEST: replace Layout with plain div to isolate which component throws */}
        <BrowserRouter>
          <div data-testid="sage-minimal-router" style={{ padding: '20px', color: 'white' }}>
            ✅ BrowserRouter + plain div 渲染成功！
            <br />
            如果你看到这条,说明问题在 Layout 组件,不在 BrowserRouter。
          </div>
        </BrowserRouter>
      </ErrorBoundary>
      <ErrorBoundary>
        <BrowserRouter>
          <NavHistoryProvider>
            <Routes>
              <Route path="/" element={<Layout />}>
                <Route index element={<Navigate to="/chat" replace />} />
                <Route path="welcome" element={<Welcome />} />
                <Route path="chat" element={<ChatRoute />} />
                <Route path="settings" element={<Settings />} />
                <Route path="memory" element={<Memory />} />
                <Route path="agents" element={<Agents />} />
                <Route path="skills" element={<Skills />} />
                <Route path="knowledge" element={<Knowledge />} />
                <Route path="scheduled" element={<ScheduledTasks />} />
                <Route path="orchestration" element={<Orchestration />} />
              </Route>
            </Routes>
            <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
          </NavHistoryProvider>
        </BrowserRouter>
      </ErrorBoundary>
    </>
  );
}

export default App;
