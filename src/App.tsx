import { useEffect, useState } from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';

import { NavHistoryProvider } from './app/providers/NavHistoryProvider';
import { loadCurrentSessionId } from './entities/session/storage';
import { Settings } from './pages';
import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import { Office } from './pages/Office';
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
    <HashRouter>
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
            <Route path="office" element={<Office />} />
            <Route path="knowledge" element={<Knowledge />} />
            <Route path="scheduled" element={<ScheduledTasks />} />
            <Route path="orchestration" element={<Orchestration />} />
          </Route>
        </Routes>
        <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
      </NavHistoryProvider>
    </HashRouter>
  );
}

export default App;
