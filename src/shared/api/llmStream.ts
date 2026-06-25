/**
 * 解析 NDJSON 流式响应
 */

export type AgentState =
  | 'idle'
  | 'thinking'
  | 'reasoning'
  | 'reasoning_delta'
  | 'acting'
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed';

export interface ToolCallRequestFE {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolCallResultFE {
  tool_call_id: string;
  role: 'tool';
  content: string;
}

export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  tool_call?: ToolCallRequestFE;
  tool_result?: ToolCallResultFE;
  error?: string;
  /** 阶段 4: 当前执行 agent 的 ID (供前端显示"当前处理 agent") */
  agent_id?: string;
}

export async function* parseNDJSONStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<AgentEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const evt = JSON.parse(trimmed) as AgentEvent;
          yield evt;
        } catch {
          // 忽略解析失败的行
        }
      }
    }

    const trimmed = buffer.trim();
    if (trimmed) {
      try {
        yield JSON.parse(trimmed) as AgentEvent;
      } catch {
        // 忽略
      }
    }
  } finally {
    reader.releaseLock();
  }
}
