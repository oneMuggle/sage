/**
 * 思考面板展开态存储。
 *
 * 背景：流结束/切换会话时消息 id 会被服务端 id 替换，Message 组件重挂载，
 * ThinkingPanel 的 useState(false) 会把刚展开的思考面板立刻折叠，用户主观
 * 感受是“思考过程没有保留”。
 *
 * 以 reasoning 内容哈希为键保存展开态：
 * - 内存 Map：跨重挂载（id 替换）立即生效；
 * - sessionStorage：显式展开/折叠可跨页面刷新保留（best-effort）。
 *
 * 流式期间的自动展开只写内存，不写 sessionStorage，避免每个 delta 落盘。
 */

const STORAGE_PREFIX = 'sage:thinking-expanded:';
const memory = new Map<string, boolean>();

function hashText(text: string): string {
  let hash = 5381;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(36);
}

export function thinkingExpansionKey(reasoning: string): string {
  return `${reasoning.length}-${hashText(reasoning)}`;
}

export function isThinkingExpanded(key: string): boolean {
  const cached = memory.get(key);
  if (cached !== undefined) return cached;
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
    if (raw === '1') {
      memory.set(key, true);
      return true;
    }
    if (raw === '0') {
      memory.set(key, false);
      return false;
    }
  } catch {
    /* sessionStorage unavailable */
  }
  return false;
}

export function setThinkingExpanded(key: string, expanded: boolean, persist = true): void {
  memory.set(key, expanded);
  if (!persist) return;
  try {
    sessionStorage.setItem(STORAGE_PREFIX + key, expanded ? '1' : '0');
  } catch {
    /* sessionStorage unavailable */
  }
}
