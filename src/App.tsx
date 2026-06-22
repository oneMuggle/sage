import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { loadCurrentSessionId } from './entities/session/storage';
import { Settings } from './pages';
import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import Skills from './pages/Skills';
import { useStore } from './shared/lib/store';
import { Layout } from './widgets/layout';

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
