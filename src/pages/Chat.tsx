import { useEffect, useRef } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { resolveEndpoint } from '../entities/setting/types';
import { useSettings } from '../features/manage-settings/useSettings';
import { useChat } from '../features/send-message/useChat';
import type { ChatOfficeRef, TaskPlanItem } from '../shared/api';
import { orchRunClient } from '../shared/api/orchRunClient';
import { useStore } from '../shared/lib/store';
import { useCurrentWorkspace } from '../shared/lib/workspaceContext';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { ActiveAgentIndicator, ChatInput, MessageList } from '../widgets/chat';
import { PlanCard } from '../components/PlanCard';
import { PlanCardList } from '../components/PlanCardList';
import { TaskTreeSection } from '../widgets/chat/progress/TaskTreeSection';

export function Chat() {
  const {
    messages,
    isLoading,
    error,
    clearError,
    sendMessage,
    interrupt,
    loadMessages,
    currentAgentId, // 阶段 4: 当前流式处理中的 agent ID
    streamingMessageId, // P1: 当前流式消息 ID
    iteration, // P2: ReAct 迭代轮次
    streamingState, // P2: 当前流式状态
    taskBoard, // Multi-Agent Orchestration: 编排任务板
    resumeOrchestration, // Wave 3: resume 恢复流入口（计划卡恢复按钮）
    clearTaskBoard, // Wave 3: 取消执行后清空任务板
  } = useChat();

  const {
    currentSessionId,
    setCurrentSessionId,
    createSession,
    isLoading: storeLoading,
  } = useStore();
  const { settings, isLoading: settingsLoading } = useSettings();
  const navigate = useNavigate();
  const location = useLocation();
  // Office M1-M2 chat-read: inject the active workspace path so the
  // ChatInput → AtFileMenu chain can surface office docs in @ autocomplete.
  // Default provider value is `undefined` (no workspace selected yet in M1-M2),
  // which keeps file-search behavior unchanged in production. Office.tsx will
  // be migrated onto this context in a follow-up PR.
  const workspacePath = useCurrentWorkspace();
  const pendingSentRef = useRef(false);
  // LOW-1: 跟随新消息/流式 token 自动滚到底。
  // 必须用 derivedMessages 而非 messages —— 流式 override 只在 derivedMessages 里,
  // 原 messages 中最后一条仍是占位符 '🤔 思考中…'。
  // 依赖:消息条数 + 最后一条 content + reasoning + tool_call 数 — 任一变化都触发滚动。
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastMsg = messages[messages.length - 1];
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [
    messages.length,
    lastMsg?.content,
    lastMsg?.reasoning_content,
    lastMsg?.tool_calls?.length,
    // streamingMessageId 变化时也需要滚 (新 stream 开始)
    streamingMessageId,
  ]);

  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);
  const hasConfig =
    Boolean(chatEndpoint?.baseUrl) && Boolean(settings.modelSelections.chatModel.modelId);
  const showConfigWarning = !hasConfig;

  // Gap E (Task 5) — click-to-trace from the Memory page:
  //   /chat?session={session_id}&highlight_turn={turn_id}
  const [searchParams] = useSearchParams();
  const highlightTurn = searchParams.get('highlight_turn');
  const sessionParam = searchParams.get('session');

  // 只在到达 /chat 时把 URL 的 session 应用一次（ref 守卫），之后用户
  // 在侧栏自由切换会话不受 URL 参数干扰。
  const appliedSessionRef = useRef<string | null>(null);
  useEffect(() => {
    if (!sessionParam || appliedSessionRef.current === sessionParam) return;
    appliedSessionRef.current = sessionParam;
    if (sessionParam !== currentSessionId) {
      setCurrentSessionId(sessionParam);
    }
  }, [sessionParam, currentSessionId, setCurrentSessionId]);

  // 高亮产生该记忆的轮次对应消息：滚动到 [data-turn-id="..."] 并加 2s 高亮环。
  // 消息加载完成后执行（依赖 messages），带 150ms 延迟让自动滚底先完成，
  // 避免两个滚动互相覆盖。highlightAppliedRef 保证每个 turn 只高亮一次。
  const highlightAppliedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightTurn || !messages.length || highlightAppliedRef.current === highlightTurn) return;
    highlightAppliedRef.current = highlightTurn;
    const timer = window.setTimeout(() => {
      const el = document.querySelector(`[data-turn-id="${highlightTurn}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-blue-500');
        window.setTimeout(() => el.classList.remove('ring-2', 'ring-blue-500'), 2000);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [highlightTurn, messages]);

  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId);
    }
  }, [currentSessionId, loadMessages]);

  // Auto-send pending message passed from Welcome page via router state
  const pendingMessage = (location.state as { pendingMessage?: string } | null)?.pendingMessage;
  useEffect(() => {
    if (
      pendingMessage &&
      currentSessionId &&
      !pendingSentRef.current &&
      !settingsLoading &&
      !storeLoading
    ) {
      pendingSentRef.current = true;
      sendMessage(pendingMessage, currentSessionId);
      // Clear location state so refresh doesn't re-send
      window.history.replaceState({}, '');
    }
  }, [pendingMessage, currentSessionId, sendMessage, settingsLoading, storeLoading]);

  const handleNewSession = async () => {
    // 与 Sidebar 的 "+ 新对话" 行为对齐:跳到欢迎页由用户输入后再创建会话。
    // 必须清空 currentSessionId,否则 ChatRoute 因为 sessionId 非空仍会
    // 渲染 Chat 页,导致跳到 /welcome 后又被重定向回 /chat。
    setCurrentSessionId(null);
    navigate('/welcome');
  };

  const handleSendMessage = async (
    content: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
      officeRefs?: readonly ChatOfficeRef[];
      // Wave 3 C6: 放宽为 string —— 编排模式条可传 'template:<id>' 等。
      orchestrationMode?: string;
    },
  ) => {
    clearError();
    const officeRefs = options?.officeRefs;
    const orchestrationMode = options?.orchestrationMode;
    if (!currentSessionId) {
      const sessionId = await createSession();
      await sendMessage(content, sessionId, officeRefs, orchestrationMode);
    } else {
      await sendMessage(content, undefined, officeRefs, orchestrationMode);
    }
  };

  // Wave 3 C3 (2026-08-15): 计划卡"开始执行" → updatePlan 落库后由后端派发。
  // 409（派发竞态）→ 保持编辑态，TaskBoard 首 task_status 事件会锁。
  const handlePlanStart = async (runId: string, plan: TaskPlanItem[]) => {
    try {
      await orchRunClient.updatePlan(runId, plan);
    } catch {
      // 409（派发竞态）→ 保持编辑态，TaskBoard 首 status 事件会锁
    }
  };

  // Wave 3 C4+H1 (2026-08-15): 统一取消语义 —— 未派发/已派发/运行中一律调
  // cancelRun（后端置 cancelled + dispatcher.cancel() 阻止自动派发，避免空转
  // 烧 token），成功或 409 等错误都清空 taskBoard（board 信息已过时）。
  // M1：取消失败也照常清理，避免计划卡永久锁定 + unhandled rejection。
  const handleCancelRun = async (runId: string) => {
    try {
      await orchRunClient.cancelRun(runId);
    } catch {
      // 409（run 已终态）等 → 前端照常清空计划卡（board 信息过时）
    }
    clearTaskBoard();
  };

  // 顶层错误：渲染整页 ErrorState，提供"关闭"清除错误后回到聊天
  if (error) {
    return (
      <div className="flex-1 flex flex-col">
        <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-sm font-semibold text-text">对话</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <ErrorState
            title="对话出错"
            message={error}
            onRetry={clearError}
            retryLabel="关闭并重试"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* 页面头部 */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-sm font-semibold text-text">对话</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={handleNewSession}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
          >
            + 新对话
          </button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        {isLoading && messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <LoadingState label="正在加载对话..." />
          </div>
        ) : (
          <MessageList messages={messages} streamingMessageId={streamingMessageId} />
        )}
      </div>

      {/* 阶段 4 + P2: 流式处理时显示当前活跃 agent + 迭代轮次 + 阶段 */}
      <ActiveAgentIndicator
        agentId={currentAgentId}
        iteration={iteration}
        streamingState={streamingState}
      />

      {showConfigWarning && (
        <div
          data-testid="config-warning"
          className="px-4 py-2 bg-yellow-50 border-t border-yellow-300 text-yellow-900 text-xs flex items-center gap-2"
        >
          <span aria-hidden="true">⚠️</span>
          <span>
            未配置 API 端点或对话模型，
            <button
              type="button"
              onClick={() => navigate('/settings')}
              className="underline text-yellow-900 hover:text-yellow-700 transition-colors"
            >
              前往设置
            </button>
          </span>
        </div>
      )}

      {/* Wave 3 三态 (win7 适配, 复用 main ProgressSection 分发):
          无编排 → 历史编排记录; 未派发 → 计划卡(可编辑); 已派发 → 任务树 */}
      {taskBoard == null ? (
        <PlanCardList onResume={(runId) => void resumeOrchestration(runId)} />
      ) : taskBoard.dispatchedAt ? (
        <TaskTreeSection board={taskBoard} onCancel={() => void handleCancelRun(taskBoard.runId)} />
      ) : (
        <PlanCard
          runId={taskBoard.runId}
          plan={taskBoard.plan}
          locked={false}
          // C4+H1 (2026-08-15): 任意阶段取消都走 handleCancelRun ——
          // cancelRun（未派发时后端置 cancelled + dispatcher.cancel() 阻止
          // 自动派发）+ 清空 taskBoard。
          onCancel={() => void handleCancelRun(taskBoard.runId)}
          onStart={(updated) => void handlePlanStart(taskBoard.runId, updated)}
        />
      )}

      <ChatInput
        onSend={handleSendMessage}
        onInterrupt={interrupt}
        isLoading={isLoading}
        disabled={!hasConfig}
        placeholder="输入消息..."
        workspacePath={workspacePath}
      />
    </div>
  );
}
