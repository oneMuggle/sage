/**
 * M2.4: 子代理线程定位请求。
 *
 * TaskCenter 点击子代理任务条目时写入 {sessionId, runId, taskId}，
 * 聊天页的 ProgressSection 在对应会话/run 挂载后消费并直接打开该任务的
 * 详情面板（过程 / 对话 / steering 合一），实现"从任务中心打开子代理线程"。
 */

import { create } from 'zustand';

export interface OrchFocusRequest {
  sessionId: string;
  runId: string;
  taskId: string;
}

interface OrchFocusState {
  request: OrchFocusRequest | null;
  /** 请求打开某子代理线程（覆盖未消费的旧请求）。 */
  focusThread: (request: OrchFocusRequest) => void;
  /**
   * 消费当前请求：仅当 runId 匹配（且 sessionId 在提供时匹配）才清空并返回，
   * 否则保留给后续渲染（例如会话尚未切换完成）。
   */
  consume: (sessionId: string | null, runId: string | null) => OrchFocusRequest | null;
}

export const useOrchestrationFocusStore = create<OrchFocusState>((set, get) => ({
  request: null,
  focusThread: (request) => set({ request }),
  consume: (sessionId, runId) => {
    const request = get().request;
    if (!request) return null;
    if (!runId || request.runId !== runId) return null;
    if (sessionId && request.sessionId !== sessionId) return null;
    set({ request: null });
    return request;
  },
}));
