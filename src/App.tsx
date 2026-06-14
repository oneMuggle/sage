import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { Agents } from './pages/Agents';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { Memory } from './pages/Memory';
import { Settings } from './pages/Settings';
import Skills from './pages/Skills';
import { Layout } from './widgets/layout';

function App() {
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
