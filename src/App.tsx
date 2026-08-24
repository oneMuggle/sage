import { useEffect, useState } from 'react';
import {
  HashRouter,
  Routes,
  Route,
  Navigate,
  useSearchParams,
  useLocation,
} from 'react-router-dom';

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
import { ApprovalDialog } from './widgets/permission';
import { QuestionDialog } from './widgets/question';
import { BackendStatusBanner } from './widgets/system/BackendStatusBanner';

// ChatRoute 内直接调用 hook 形式的 useStore setter 会引入条件调用问题,
// 用 getState() 命令式写入更直白(与 App useEffect 里的用法一致)。
const setCurrentSessionIdFromStore = (id: string) => useStore.getState().setCurrentSessionId(id);

// 批次三 step 6 (spec §4.3 line 150):
// Memory 页"按会话查看摘要"或"来源会话跳转"以 /chat?session=<id> 深链形式进入。
// 该 hook 让 App 在挂载时知道:有深链就别用持久化恢复覆盖当前会话。
// 持久化恢复仍走 loadCurrentSessionId() — 它会延后到 ChatRoute effect
// 之后才落地,但 deep link 一旦设置 session,App 不再盲回写。
function useRequestedSessionId(): string | null {
  const location = useLocation();
  // location.search 在 HashRouter 下为空 query 时为 ''
  if (!location.search) return null;
  const params = new URLSearchParams(location.search);
  const id = params.get('session');
  return id && id.trim() ? id.trim() : null;
}

function AppStartupRestore() {
  const requestedSessionId = useRequestedSessionId();
  useEffect(() => {
    // 深链优先 — 持久化恢复会让位,避免 App 启动异步读到的"上次会话"
    // 覆盖用户明确要打开的目标会话(Memory 页来源跳转 / 摘要视图)。
    if (requestedSessionId) return;
    let cancelled = false;
    loadCurrentSessionId().then((id) => {
      if (cancelled) return;
      if (id) {
        useStore.getState().setCurrentSessionId(id);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [requestedSessionId]);
  return null;
}

// Phase 7: gate /chat by currentSessionId; fall back to /welcome when missing.
// 批次三 step 6 (spec §4.3 line 150): Memory 页"来源会话跳转"以
// /chat?session=<id> 形式进入 — ChatRoute 消费该参数写入 store,
// 复用 setCurrentSessionId → loadMessages 的既有切换链路。
function ChatRoute() {
  const currentSessionId = useStore((s) => s.currentSessionId);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSessionId = searchParams.get('session');
  useEffect(() => {
    if (requestedSessionId && requestedSessionId !== currentSessionId) {
      setCurrentSessionIdFromStore(requestedSessionId);
      // 清掉参数,避免刷新时反复触发会话切换。
      // 注:必须 replace 而非 push,否则后退按钮会停在带 ?session= 的旧 URL。
      setSearchParams({}, { replace: true });
    }
  }, [requestedSessionId, currentSessionId, setSearchParams]);
  if (!currentSessionId) {
    return <Navigate to="/welcome" replace />;
  }
  return <Chat />;
}

function App() {
  const [commandOpen, setCommandOpen] = useState(false);

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
        <BackendStatusBanner />
        <AppStartupRestore />
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
        {/* M1: 全局工具审批模态框 — 由 permission_request 流事件驱动 */}
        <ApprovalDialog />
        {/* M2 part B: 全局提问模态框 — 由 ask_user_question 流事件驱动 */}
        <QuestionDialog />
      </NavHistoryProvider>
    </HashRouter>
  );
}

export default App;
