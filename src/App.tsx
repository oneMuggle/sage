import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

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
import { NavHistoryProvider } from './app/providers/NavHistoryProvider';
import { useStore } from './shared/lib/store';
import { Layout } from './widgets/layout';

// M6: gate /chat by currentSessionId; fall back to /welcome when missing.
function ChatRoute() {
  const currentSessionId = useStore((s) => s.currentSessionId);
  if (!currentSessionId) {
    return <Navigate to="/welcome" replace />;
  }
  return <Chat />;
}

function App() {
  useEffect(() => {
    loadCurrentSessionId().then((id) => {
      if (id) {
        useStore.getState().setCurrentSessionId(id);
      }
    });
  }, []);

  return (
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
      </NavHistoryProvider>
    </BrowserRouter>
  );
}

export default App;
