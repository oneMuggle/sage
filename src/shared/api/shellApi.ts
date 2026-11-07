// src/shared/api/shellApi.ts
//
// 后台 shell 列表与输出流客户端（2026-11-06 Phase 3）。
// 列表经 Electron 主进程 invoke（命令路由 shell_list）；
// 输出流经 desktopEvent.listen('shell-stream-{shellId}') relay 消费 NDJSON。

import { listen, type UnlistenFn } from './desktopEvent';
import { invoke } from './desktopInvoke';

export interface ShellInfo {
  shell_id: string;
  command: string;
  status: 'running' | 'exited';
  pid: number | null;
  age_seconds: number;
  /** 2026-11-07 Phase 5: 已退出 shell 的退出码（未知为 null）。 */
  exit_code?: number | null;
}

export type ShellStreamEvent =
  | { type: 'output'; stream: 'stdout' | 'stderr'; data: string }
  | { type: 'exit'; exit_code: number | null };

/** 拉取当前注册表中的后台 shell。 */
export async function listShells(): Promise<ShellInfo[]> {
  const response = await invoke<{ shells?: ShellInfo[] }>('shell_list');
  return Array.isArray(response?.shells) ? response.shells : [];
}

/** 订阅后台 shell 输出流；返回取消订阅函数。 */
export async function listenShellStream(
  shellId: string,
  handler: (event: ShellStreamEvent) => void,
): Promise<UnlistenFn> {
  return listen<ShellStreamEvent>(`shell-stream-${shellId}`, (e) => handler(e.payload), {
    streamId: shellId,
  });
}
