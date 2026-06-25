import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { loadCurrentSessionId } from './entities/session/storage';
import { Settings } from './pages';
import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import Skills from './pages/Skills';
import { useStore } from './shared/lib/store';
import { CommandPalette } from './widgets/command';
import { Layout } from './widgets/layout';

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
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
    </BrowserRouter>
  );
}

export default App;
