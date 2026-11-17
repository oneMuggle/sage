/**
 * 记忆标题/预览推导工具。
 *
 * 背景（2026-11-17 记忆页详情化）：此前"标题"是前端对 content 的前 30 字符
 * 硬截断，长记忆既无标题可扫读也无详情可看。后端 M2 起会下发真正的
 * ``title`` 字段；存量行或旧后端缺失该字段时，这里提供确定性的降级推导：
 * 取首个非空行、去掉常见 markdown/列表前缀、压缩空白、按字数截断。
 */

/** 标题最大字符数（与后端 derive_title 保持一致）。 */
export const MEMORY_TITLE_MAX = 60;
/** 折叠态预览最大字符数。 */
export const MEMORY_PREVIEW_MAX = 160;

export function normalizeWhitespace(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

/**
 * 确定性标题推导 —— 不调用 LLM，纯函数，便于测试与读取时兜底。
 *
 * 规则：
 * 1. 取首个非空行（跳过空行）；
 * 2. 去掉标题/列表前缀（``#``、``-``、``*``、``>``、``1.``、``1、``）；
 * 3. 压缩连续空白；
 * 4. 超过 ``MEMORY_TITLE_MAX`` 字符时截断并以省略号收尾。
 */
export function deriveMemoryTitle(content: string | null | undefined): string {
  if (!content) return '无标题';
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const firstLine = lines[0] ?? '';
  const cleaned = firstLine
    .replace(/^#{1,6}\s+/, '')
    .replace(/^[-*>•]\s+/, '')
    .replace(/^\d+[.)、]\s*/, '')
    .trim();
  const normalized = normalizeWhitespace(cleaned) || normalizeWhitespace(content);
  if (!normalized) return '无标题';
  return normalized.length > MEMORY_TITLE_MAX
    ? `${normalized.slice(0, MEMORY_TITLE_MAX - 1)}…`
    : normalized;
}

/**
 * 卡片标题：优先使用后端下发的 ``title``（非空且不是纯空白），
 * 否则回退到确定性推导。
 */
export function resolveMemoryTitle(memory: {
  title?: string;
  content?: string;
  summary?: string;
}): string {
  const backendTitle = typeof memory.title === 'string' ? memory.title.trim() : '';
  if (backendTitle) return backendTitle;
  return deriveMemoryTitle(memory.content || memory.summary);
}

/** 折叠态预览：压缩空白后按 ``MEMORY_PREVIEW_MAX`` 截断。 */
export function deriveMemoryPreview(content: string | null | undefined): string {
  const normalized = normalizeWhitespace(content || '');
  if (!normalized) return '';
  return normalized.length > MEMORY_PREVIEW_MAX
    ? `${normalized.slice(0, MEMORY_PREVIEW_MAX).trimEnd()}…`
    : normalized;
}

/** 正文真实字符数（含换行，用于卡片上的「X 字」提示）。 */
export function countMemoryChars(content: string | null | undefined): number {
  return content ? content.length : 0;
}
