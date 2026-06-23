import { Brain, Eye, Pencil, Wrench } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { AgentEvent } from '../../shared/api';
import {
  agentStateToPhase,
  type PhaseIconName,
} from '../../shared/lib/agentStateMapping';

interface ActiveAgentIndicatorProps {
  /** 当前活跃 agent 的 ID (null 表示无流式处理) */
  agentId: string | null;
  /** P2: 当前 ReAct 迭代轮次 */
  iteration?: number;
  /** P2: 当前流式状态 */
  streamingState?: AgentEvent['state'] | null;
}

const PHASE_ICON: Record<PhaseIconName, React.ComponentType<{ className?: string }>> = {
  Brain,
  Wrench,
  Eye,
  Pencil,
  // Loader2 暂未用,留接口
  Loader2: Wrench,
};

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

  // P2: 流式阶段图标 + 文本 (从共享模块获取,UI 层渲染 lucide 图标)
  const phaseInfo = agentStateToPhase(streamingState);

  // LOW-2: 单轮 LLM 调用显示 '第 1 轮' 是噪音,只在有 ReAct 循环(iteration > 0)
  // 或多轮的情况下才显示迭代轮次
  const showIteration = iteration > 0;

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
          {streamingState && showIteration && (
            <span className="text-primary font-medium">第 {iteration} 轮</span>
          )}
          {displayedAgentId && (
            <>
              {streamingState && showIteration && <span className="text-border">·</span>}
              <span className="font-medium text-text">{agentLabel}</span>
            </>
          )}
          {phaseInfo && (
            <>
              <span className="text-border">·</span>
              <span className="flex items-center gap-1">
                {(() => {
                  const Icon = PHASE_ICON[phaseInfo.iconName];
                  return <Icon className="w-3.5 h-3.5 text-muted" />;
                })()}
                {phaseInfo.label}
              </span>
            </>
          )}
        </span>
      )}
    </div>
  );
}