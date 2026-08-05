/**
 * MemoryCard - 单条记忆卡片（Gap E / Task 5 可追溯性 UI）。
 *
 * 展示记忆内容 + 分类中文标签 + importance，支持删除；
 * 当记忆带 session_id + source_turn_id/source_message_id 时，
 * 渲染"跳转到产生该记忆的会话"按钮，点击后导航到
 * ``/chat?session={session_id}&highlight_turn={turn_id}``。
 */
import { MapPin, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export interface MemoryItem {
  id: string;
  content: string;
  importance: number;
  memory_type?: string;
  memory_category?: string;
  session_id?: string;
  source_turn_id?: string;
  source_message_id?: string;
  created_at: number | string;
}

/** memory_category 词汇 → 中文标签（与 backend extractor vocab 对齐）。 */
export const CATEGORY_LABELS: Record<string, string> = {
  user_pref: '用户偏好',
  project_fact: '项目事实',
  task_summary: '任务总结',
  decision: '决策',
  cross_session_pattern: '跨会话模式',
};

function formatTime(value: number | string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN');
}

export function MemoryCard({
  memory,
  onDelete,
}: {
  memory: MemoryItem;
  onDelete: (id: string) => void;
}) {
  const navigate = useNavigate();
  // 优先 source_message_id（= 消息 id，Chat 页 data-turn-id 可精确命中），
  // 回退 source_turn_id（run_id）——见 task-5 Concerns。
  const traceTurn = memory.source_message_id ?? memory.source_turn_id;
  const canTrace = Boolean(memory.session_id) && Boolean(traceTurn);

  const handleTraceabilityClick = () => {
    if (!canTrace || !traceTurn) return;
    navigate(
      `/chat?session=${encodeURIComponent(memory.session_id as string)}&highlight_turn=${encodeURIComponent(traceTurn)}`,
    );
  };

  const categoryLabel = memory.memory_category
    ? (CATEGORY_LABELS[memory.memory_category] ?? memory.memory_category)
    : (memory.memory_type ?? 'episodic');

  return (
    <div className="border rounded-lg p-4 mb-2 bg-white dark:bg-gray-800">
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs text-gray-500">
          🧠 {categoryLabel} · {formatTime(memory.created_at)}
        </span>
        <button
          type="button"
          aria-label="删除记忆"
          onClick={() => onDelete(memory.id)}
          className="text-red-500 hover:text-red-700 transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      <p className="text-sm mb-2 break-words">{memory.content}</p>
      <div className="flex justify-between items-center text-xs text-gray-500">
        <span>importance: {memory.importance}</span>
        {canTrace && traceTurn && (
          <button
            type="button"
            onClick={handleTraceabilityClick}
            className="flex items-center gap-1 hover:text-blue-500 transition-colors"
            aria-label="跳转到来源会话"
          >
            <MapPin className="w-3 h-3" />
            Session #{memory.session_id?.slice(0, 8)} · Turn #{traceTurn.slice(0, 8)}
          </button>
        )}
      </div>
    </div>
  );
}
