// src/widgets/chat/messageAudit.ts
//
// R117: 自 Message.tsx 尾部原样抽离的消息审计格式化帮手。
// 原与 Message 组件同文件导出（全文件仅有的非组件导出），
// 触发 react-refresh/only-export-components 存量警告；抽
// 离后组件文件回到单一导出。两函数无生产调用方，仅供测
// 试与诊断场景拼装单行摘要 / JSON，不参与渲染。
import type { Message as MessageType } from '../../shared/lib/store';

export function formatMessageAuditSummary(message: MessageType, isStreaming = false): string {
  const toolCount = Array.isArray(message.tool_calls) ? message.tool_calls.length : 0;
  return `${message.id} · role=${message.role} · streaming=${isStreaming} · tools=${toolCount} · chars=${(message.content ?? '').length}`;
}

export function formatMessageAuditJson(message: MessageType, isStreaming = false): string {
  const toolCount = Array.isArray(message.tool_calls) ? message.tool_calls.length : 0;
  return JSON.stringify(
    {
      id: message.id,
      role: message.role,
      isStreaming,
      toolCallCount: toolCount,
      contentLength: (message.content ?? '').length,
    },
    null,
    2,
  );
}
