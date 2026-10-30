// 新建反馈会话时，可选地在正文末尾附上最近运行日志。
//
// 开关存在 Electron 配置里（feedback.includeDiagnostics），这里只负责取日志
// 并拼成一段 markdown。日志本身已由后端 redact 过敏感信息。

import { fetchLogTail } from '../../shared/api/feedbackApi';

/** 附件里保留的日志尾部行数。 */
export const DIAGNOSTICS_TAIL_LINES = 80;

/** 拼进正文的日志字符上限，防止首条消息过大。 */
export const DIAGNOSTICS_MAX_CHARS = 4000;

/** 把日志文本包成 markdown 代码块；空白日志返回 null。 */
export function formatDiagnosticsSuffix(text: string, header: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const clipped =
    trimmed.length > DIAGNOSTICS_MAX_CHARS
      ? trimmed.slice(trimmed.length - DIAGNOSTICS_MAX_CHARS)
      : trimmed;
  return `${header}\n\n\`\`\`\n${clipped}\n\`\`\``;
}

/** 取日志尾部并格式化。取失败时返回 null —— 附日志是尽力而为，不应挡住发反馈。 */
export async function collectDiagnosticsSuffix(header: string): Promise<string | null> {
  try {
    const tail = await fetchLogTail(DIAGNOSTICS_TAIL_LINES);
    return formatDiagnosticsSuffix(tail.text, header);
  } catch {
    return null;
  }
}
