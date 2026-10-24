import { Brain, Eye, Pencil, RefreshCw, Wrench } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { AgentEvent } from '../../shared/api';
import { agentStateToPhase, type PhaseIconName } from '../../shared/lib/agentStateMapping';

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
  // 2026-10-20: LLM 重试阶段图标（旋转）
  RefreshCw,
  // Loader2 暂未用,留接口
  Loader2: Wrench,
};

/**
 * 阶段 4 + P2: 聊天流式处理时显示"当前处理 agent + 迭代轮次 + 阶段"的指示器。
 *
 * - agentId 变化时淡入显示 "第 N 轮 · agent · 阶段"
 * - agentId 变为 null 后延迟 3 秒淡出
 * - 淡出结束后不再占位（卸载，归还 24px 给消息滚动区）
 *   —— 原「始终占固定高度」策略被用户反馈「遮挡会话信息」推翻
 *   (2026-10-24)。淡出期间 (300ms) 保留 h-6 以支持 opacity 过渡。
 */
export function ActiveAgentIndicator({
  agentId,
  iteration = 0,
  streamingState = null,
}: ActiveAgentIndicatorProps) {
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);
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
      setMounted(true);
    } else {
      // 延迟 3 秒后淡出
      // capture ref locally (lint: react-hooks/exhaustive-deps)
      const timers = timersRef.current;
      const outer = setTimeout(() => {
        timers.delete(outer);
        setVisible(false);
        // 再延迟 300ms (淡出动画时长) 后卸载 —— 归还 24px 给消息区
        const inner = setTimeout(() => {
          timers.delete(inner);
          setDisplayedAgentId(null);
          setMounted(false);
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

  // 淡出动画结束后不再占位 —— 归还 24px 给消息滚动区
  if (!mounted) return null;

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
              <span
                className={`flex items-center gap-1 ${
                  phaseInfo.iconName === 'RefreshCw' ? 'text-warning' : ''
                }`}
              >
                {(() => {
                  const Icon = PHASE_ICON[phaseInfo.iconName];
                  // 重试阶段图标旋转,提示"系统正在自动恢复"
                  const spin = phaseInfo.iconName === 'RefreshCw' ? ' animate-spin' : '';
                  return (
                    <Icon
                      className={`w-3.5 h-3.5 ${phaseInfo.iconName === 'RefreshCw' ? 'text-warning' : 'text-muted'}${spin}`}
                    />
                  );
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

export interface ActiveAgentIndicatorAuditReport {
  schemaVersion: '1.0';
  module: 'src/widgets/chat/ActiveAgentIndicator.tsx';
  componentName: 'ActiveAgentIndicator';
  hasActiveAgent: boolean;
  isStreaming: boolean;
  exportedAt: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditActiveAgentIndicator(
  agentName: string | null = 'Sage',
  isStreaming = false,
): ActiveAgentIndicatorAuditReport {
  return {
    schemaVersion: '1.0',
    module: 'src/widgets/chat/ActiveAgentIndicator.tsx',
    componentName: 'ActiveAgentIndicator',
    hasActiveAgent: Boolean(agentName && agentName.trim().length > 0),
    isStreaming: Boolean(isStreaming),
    exportedAt: '2026-10-22',
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportActiveAgentIndicatorAuditJson(
  agentName: string | null = 'Sage',
  isStreaming = false,
): string {
  return JSON.stringify(auditActiveAgentIndicator(agentName, isStreaming), null, 2);
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditActiveAgentIndicatorGovernance(): string {
  return JSON.stringify({
    module: 'active-agent-indicator',
    phase: 'P185',
    audited: true,
  });
}
