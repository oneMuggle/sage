import { useEffect, useRef, useState } from 'react';

import type { AgentEvent } from '../../shared/api';

interface ActiveAgentIndicatorProps {
  /** 当前活跃 agent 的 ID (null 表示无流式处理) */
  agentId: string | null;
  /** P2: 当前 ReAct 迭代轮次 */
  iteration?: number;
  /** P2: 当前流式状态 */
  streamingState?: AgentEvent['state'] | null;
}

/**
 * 阶段 4 + P2: 聊天流式处理时显示"当前处理 agent + 迭代轮次 + 阶段"的指示器。
 *
 * - agentId 变化时淡入显示 "第 N 轮 · agent · 阶段"
 * - agentId 变为 null 后延迟 3 秒淡出
 * - 始终占据固定高度 (避免聊天内容抖动)
 */
export function ActiveAgentIndicator({
  agentId,
  iteration = 0,
  streamingState = null,
}: ActiveAgentIndicatorProps) {
  const [visible, setVisible] = useState(false);
  const [displayedAgentId, setDisplayedAgentId] = useState<string | null>(null);
  // P2 修复: 跟踪所有 setTimeout 句柄,在 effect cleanup 中一并清除
  // (之前只清 outer 3s timer,inner 300ms timer 会泄漏,导致新 stream
  // 启动后 inner timer 触发,把 displayedAgentId 清掉)
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  useEffect(() => {
    // P2: 有任何流式活动时显示 (streamingState 非 null 即有活动)
    // 向后兼容:agentId 非 null 也触发显示
    if (agentId || streamingState) {
      // LOW fix: 仅当 agentId 实际变化时才 setState,避免每个 content_delta 触发浪费渲染
      setDisplayedAgentId((prev) => (agentId && agentId !== prev ? agentId : prev));
      setVisible(true);
    } else {
      // 延迟 3 秒后淡出
      // capture ref locally (lint: react-hooks/exhaustive-deps)
      const timers = timersRef.current;
      const outer = setTimeout(() => {
        timers.delete(outer);
        setVisible(false);
        // 再延迟 300ms (淡出动画时长) 后清空显示
        const inner = setTimeout(() => {
          timers.delete(inner);
          setDisplayedAgentId(null);
        }, 300);
        timers.add(inner);
      }, 3000);
      timers.add(outer);
      return () => {
        // cleanup: 清掉所有未触发的 timer
        timers.forEach((t) => clearTimeout(t));
        timers.clear();
      };
    }
  }, [agentId, streamingState]);

  // agentId 标签推导 (友好显示)
  const agentLabel =
    displayedAgentId === 'primary'
      ? '主助手'
      : displayedAgentId === 'researcher'
        ? '研究助手'
        : displayedAgentId === 'coder'
          ? '编码助手'
          : displayedAgentId === 'memory_manager'
            ? '记忆管理'
            : displayedAgentId || '';

  // P2: 流式阶段图标 + 文本
  const phaseInfo = getPhaseInfo(streamingState);

  return (
    <div
      className={`h-6 flex items-center px-3 text-xs transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
      aria-live="polite"
      aria-atomic="true"
    >
      {(displayedAgentId || streamingState) && (
        <span className="text-muted flex items-center gap-1.5">
          {streamingState && iteration >= 0 && (
            <span className="text-primary font-medium">第 {iteration + 1} 轮</span>
          )}
          {displayedAgentId && (
            <>
              {streamingState && <span className="text-border">·</span>}
              <span className="font-medium text-text">{agentLabel}</span>
            </>
          )}
          {phaseInfo && (
            <>
              <span className="text-border">·</span>
              <span>
                {phaseInfo.icon} {phaseInfo.label}
              </span>
            </>
          )}
        </span>
      )}
    </div>
  );
}

/** P2: 根据流式状态返回阶段图标和文本 */
function getPhaseInfo(state: AgentEvent['state'] | null): { icon: string; label: string } | null {
  switch (state) {
    case 'thinking':
      return { icon: '🤔', label: '思考中' };
    case 'reasoning':
      return { icon: '🧠', label: '推理中' };
    case 'acting':
      return { icon: '🔧', label: '执行工具' };
    case 'observing':
      return { icon: '👀', label: '观察结果' };
    case 'content_delta':
      return { icon: '✍️', label: '生成回答' };
    default:
      return null;
  }
}
