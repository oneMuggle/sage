import { lazy, Suspense, useEffect, useState } from 'react';
import {
  HashRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useSearchParams,
  useLocation,
} from 'react-router-dom';

import { NavHistoryProvider } from './app/providers/NavHistoryProvider';
import { UpdateDialog } from './components/UpdateDialog';
import { loadCurrentSessionId } from './entities/session/storage';
import { onSessionNotifyClick } from './features/send-message/sessionNotify';
import { Chat } from './pages/Chat';
import { Welcome } from './pages/Welcome';
import { useStore } from './shared/lib/store';
import { CommandPalette } from './widgets/command';
import { Layout } from './widgets/layout';
import { ApprovalDialog } from './widgets/permission';
import { QuestionDialog } from './widgets/question';
import { BackendStatusBanner } from './widgets/system/BackendStatusBanner';
import { ShortcutHelpOverlay } from './widgets/system/ShortcutHelpOverlay';

// R24-D6: 路由级代码分割 —— 首屏只加载 Chat/Welcome，低频页面
// (设置/记忆/智能体/技能/Office/知识库/编排/定时任务) 按需加载。
// Electron file:// 下同样减少首屏解析/执行量。
const Settings = lazy(() => import('./pages').then((m) => ({ default: m.Settings })));
const Agents = lazy(() => import('./pages/Agents').then((m) => ({ default: m.Agents })));
const Knowledge = lazy(() => import('./pages/Knowledge').then((m) => ({ default: m.Knowledge })));
const Memory = lazy(() => import('./pages/Memory').then((m) => ({ default: m.Memory })));
const Office = lazy(() => import('./pages/Office').then((m) => ({ default: m.Office })));
const Orchestration = lazy(() =>
  import('./pages/Orchestration').then((m) => ({ default: m.Orchestration })),
);
const ScheduledTasks = lazy(() =>
  import('./pages/ScheduledTasks').then((m) => ({ default: m.ScheduledTasks })),
);
const Skills = lazy(() => import('./pages/Skills').then((m) => ({ default: m.default })));
const Help = lazy(() => import('./pages/Help').then((m) => ({ default: m.Help })));

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
// Gap E (Task 5): allow mounting when the URL carries ?session=… (click-to-trace
// from the Memory page) — Chat applies the session param on mount.
function ChatRoute() {
  const currentSessionId = useStore((s) => s.currentSessionId);
  const [searchParams] = useSearchParams();
  const sessionParam = searchParams.get('session');
  if (!currentSessionId && !sessionParam) {
    return <Navigate to="/welcome" replace />;
  }
  return <Chat />;
}

// S8 (round4): OS 通知点击 → 聚焦窗口后跳转对应会话。
// 主进程 'sage:event:session-notify-click' 回发 sessionId,这里统一
// 写 currentSessionId + 深链跳转（复用 ChatRoute 的 ?session= 消费链路）。
function SessionNotifyBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    const unlisten = onSessionNotifyClick((sessionId) => {
      useStore.getState().setCurrentSessionId(sessionId);
      navigate(`/chat?session=${encodeURIComponent(sessionId)}`);
    });
    return () => {
      void unlisten?.then((fn) => fn?.());
    };
  }, [navigate]);
  return null;
}

function App() {
  const navigate = useNavigate();
  const [commandOpen, setCommandOpen] = useState(false);
  // U18 (round4): 快捷键帮助覆盖层（非输入焦点下按 ? 打开）
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);

  // 全局快捷键 Ctrl+K / Cmd+K 打开命令面板, F1 打开帮助中心
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandOpen((prev) => !prev);
        return;
      }
      // F1: 打开帮助中心
      if (e.key === 'F1') {
        e.preventDefault();
        navigate('/help');
        return;
      }
      // U18: '?' = Shift+/，输入焦点内不劫持（用户可能真的想输入问号）
      if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName;
        const isTextInput =
          tag === 'INPUT' ||
          tag === 'TEXTAREA' ||
          tag === 'SELECT' ||
          target?.isContentEditable === true;
        if (!isTextInput) {
          e.preventDefault();
          setShortcutHelpOpen((prev) => !prev);
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [navigate]);

  return (
    <HashRouter>
      <NavHistoryProvider>
        <BackendStatusBanner />
        <AppStartupRestore />
        <SessionNotifyBridge />
        <Routes>
          <Route
            path="/"
            element={
              <Suspense fallback={<div className="flex-1" />}>
                <Layout />
              </Suspense>
            }
          >
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
            <Route path="help" element={<Help />} />
          </Route>
        </Routes>
        <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
        {/* U18: 快捷键帮助覆盖层（? 触发，Esc/点背景关闭） */}
        <ShortcutHelpOverlay open={shortcutHelpOpen} onClose={() => setShortcutHelpOpen(false)} />
        {/* M1: 全局工具审批模态框 — 由 permission_request 流事件驱动 */}
        <ApprovalDialog />
        {/* M2 part B: 全局提问模态框 — 由 ask_user_question 流事件驱动 */}
        <QuestionDialog />
        {/* Task 11: 全局更新对话框 — 由 update:state-changed 事件驱动 */}
        <UpdateDialog />
      </NavHistoryProvider>
    </HashRouter>
  );
}

export default App;
