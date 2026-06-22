import { useEffect, useState } from 'react';

interface ActiveAgentIndicatorProps {
  /** 当前活跃 agent 的 ID (null 表示无流式处理) */
  agentId: string | null;
}

/**
 * 阶段 4: 聊天流式处理时显示"当前处理 agent"的指示器。
 *
 * - agentId 变化时淡入显示 "🤖 当前 agent: xxx"
 * - agentId 变为 null 后延迟 3 秒淡出
 * - 始终占据固定高度 (避免聊天内容抖动)
 */
export function ActiveAgentIndicator({ agentId }: ActiveAgentIndicatorProps) {
  const [visible, setVisible] = useState(false);
  const [displayedAgentId, setDisplayedAgentId] = useState<string | null>(null);

  useEffect(() => {
    if (agentId) {
      setDisplayedAgentId(agentId);
      setVisible(true);
    } else {
      // 延迟 3 秒后淡出
      const timer = setTimeout(() => {
        setVisible(false);
        // 再延迟 300ms (淡出动画时长) 后清空显示
        setTimeout(() => setDisplayedAgentId(null), 300);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [agentId]);

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

  return (
    <div
      className={`h-6 flex items-center px-3 text-xs transition-opacity duration-300 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
      aria-live="polite"
      aria-atomic="true"
    >
      {displayedAgentId && (
        <span className="text-muted">
          🤖 当前处理: <span className="font-medium text-text">{agentLabel}</span>
        </span>
      )}
    </div>
  );
}
