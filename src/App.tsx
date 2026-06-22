import { useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { Settings } from './pages';
import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import Skills from './pages/Skills';
import { Layout } from './widgets/layout';
import { useStore } from './shared/lib/store';
import { loadCurrentSessionId } from './entities/session/storage';

function App() {
  // React 18+ StrictMode 在 dev 模式下会双调用 useEffect，导致 loadCurrentSessionId
  // 被调用两次。用 useRef 防护，确保只加载一次。
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;

    loadCurrentSessionId().then((id) => {
      if (id) {
        useStore.getState().setCurrentSessionId(id);
      }
    });
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<Chat />} />
          <Route path="settings" element={<Settings />} />
          <Route path="memory" element={<Memory />} />
          <Route path="agents" element={<Agents />} />
          <Route path="skills" element={<Skills />} />
          <Route path="knowledge" element={<Knowledge />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
