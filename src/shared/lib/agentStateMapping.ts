/**
 * 统一的 AgentState → UI 展示映射
 *
 * MEDIUM-3 + MEDIUM-4 修复: 之前 useChat.ts 的 agentStateToUiText 和
 * ActiveAgentIndicator.tsx 的 getPhaseInfo 都各自维护一份 state→label 映射,
 * 修改 state 时需两处同步,容易漂移。本文件作为单一真相源。
 */
import type { AgentState } from '../api/types';

/** lucide-react 图标名(用字符串而非组件本身,避免循环依赖) */
export type PhaseIconName = 'Brain' | 'Loader2' | 'Wrench' | 'Eye' | 'Pencil';

export interface PhaseDisplay {
  /** lucide-react 图标名,UI 层渲染时 import 对应组件 */
  iconName: PhaseIconName;
  label: string;
}

/**
 * 编译期守卫:当 switch 漏掉某个 AgentState 变体时,在编译期/运行期给出明确报错。
 * 防止未来给 AgentState 联合类型加新成员后漏处理,默默返回 null。
 */
function assertNever(x: never): never {
  throw new Error(`Unhandled AgentState variant: ${JSON.stringify(x)}`);
}

/**
 * 流式阶段文本(用于内容占位符,显示在消息气泡内)
 * 保留 emoji 前缀是占位文本的视觉锚点,与 ActiveAgentIndicator 的图标分离。
 * 注意:deltas (reasoning_delta / content_delta) 不返回占位文本 — 它们是真实内容
 * 流式输出,不应触发中间态占位符的覆盖。
 */
export function agentStateToText(state: AgentState, toolName?: string): string | null {
  switch (state) {
    case 'thinking':
      return '🤔 思考中…';
    case 'acting':
      return toolName ? `🔧 调工具 ${toolName}…` : '🔧 行动中…';
    case 'observing':
      return '👀 观察结果…';
    case 'failed':
      return '❌ 失败';
    case 'reasoning':
    case 'reasoning_delta':
    case 'content_delta':
    case 'idle':
    case 'done':
      return null;
    default:
      return assertNever(state);
  }
}

/**
 * 流式阶段展示(图标名 + 标签),用于 ActiveAgentIndicator 等展示组件
 * iconName 是 lucide-react 的图标名,UI 层自行 import 对应组件。
 * reasoning_delta 复用 reasoning 的展示,因为 UI 上对用户没有区别(都是
 * 思考内容在累积)。content_delta 复用 content 的最终展示。
 */
export function agentStateToPhase(
  state: AgentState | null | undefined,
): PhaseDisplay | null {
  if (state == null) return null;
  switch (state) {
    case 'thinking':
      return { iconName: 'Brain', label: '思考中' };
    case 'reasoning':
    case 'reasoning_delta':
      return { iconName: 'Brain', label: '推理中' };
    case 'acting':
      return { iconName: 'Wrench', label: '执行工具' };
    case 'observing':
      return { iconName: 'Eye', label: '观察结果' };
    case 'content_delta':
      return { iconName: 'Pencil', label: '生成回答' };
    case 'idle':
    case 'done':
    case 'failed':
      return null;
    default:
      return assertNever(state);
  }
}
