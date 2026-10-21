/**
 * Workspace MCP Server client (M4).
 *
 * Backend admin API (/api/v1/remote-mcp/*) goes through COMMAND_ROUTES:
 *   remote_mcp_state            → GET    /state
 *   remote_mcp_listener_start   → POST   /listener/start      { port }
 *   remote_mcp_listener_stop    → POST   /listener/stop
 *   remote_mcp_workspace_create → POST   /workspaces          { name, root }
 *   remote_mcp_workspace_update → PATCH  /workspaces/{id}     { enabled?, permissions?, approval? }
 *   remote_mcp_workspace_rotate → POST   /workspaces/{id}/rotate
 *   remote_mcp_workspace_delete → DELETE /workspaces/{id}
 *   remote_mcp_resume           → POST   /resume
 *
 * Tunnel / emergency stop / copy-url live in the Electron main process
 * (window.electronAPI.remoteMcp) so the token never reaches the renderer.
 */
import { invoke } from './desktopInvoke';

export type RemoteApprovalMode = 'auto' | 'ask';

export type RemotePermission = 'read' | 'write' | 'shell' | 'office' | 'memory';

export interface RemoteWorkspace {
  id: string;
  name: string;
  root: string;
  enabled: boolean;
  permissions: Partial<Record<RemotePermission, boolean>>;
  approval?: RemoteApprovalMode;
  /** token 无法解密（换机器 / 换用户）后已重置，需重新复制地址 */
  token_reset?: boolean;
  sessions: number;
  created_at?: number;
}

interface RemoteAuditEntry {
  ts?: number | string;
  time?: number | string;
  event: string;
  workspace_id?: string;
  tool?: string;
  code?: string;
  ms?: number;
}

export interface RemoteMcpState {
  listener: { running: boolean; port: number | null; error: string | null; host: string };
  paused: boolean;
  running_commands: number;
  workspaces: RemoteWorkspace[];
  audit: RemoteAuditEntry[];
}

type RemoteTunnelStateName = 'stopped' | 'starting' | 'running' | 'degraded' | 'reconnecting' | 'error';

export interface RemoteTunnelState {
  state: RemoteTunnelStateName;
  url: string | null;
  error: string | null;
  health: { state: string; latencyMs?: number; checkedAt?: string; failures?: number; reason?: string };
  addressChanged: boolean;
  retryCount: number;
  supported: boolean;
  hotkeyRegistered: boolean;
}

export interface RemoteMcpElectronApiBridge {
  tunnelState(): Promise<RemoteTunnelState>;
  startTunnel(): Promise<RemoteTunnelState>;
  stopTunnel(): Promise<RemoteTunnelState>;
  emergencyStop(): Promise<RemoteTunnelState>;
  /** Writes the connection URL to the clipboard; resolves true. */
  copyUrl(id: string, options?: { public?: boolean }): Promise<boolean>;
}

export const DEFAULT_REMOTE_MCP_PORT = 8767;

export const remoteMcpApi = {
  state: () => invoke<RemoteMcpState>('remote_mcp_state'),
  startListener: (port: number) => invoke<RemoteMcpState>('remote_mcp_listener_start', { port }),
  stopListener: () => invoke<RemoteMcpState>('remote_mcp_listener_stop'),
  createWorkspace: (name: string, root: string) =>
    invoke<RemoteMcpState>('remote_mcp_workspace_create', { name, root }),
  updateWorkspace: (
    id: string,
    patch: {
      enabled?: boolean;
      permissions?: Partial<Record<RemotePermission, boolean>>;
      approval?: RemoteApprovalMode;
    },
  ) => invoke<RemoteMcpState>('remote_mcp_workspace_update', { id, ...patch }),
  rotateWorkspace: (id: string) => invoke<RemoteMcpState>('remote_mcp_workspace_rotate', { id }),
  deleteWorkspace: (id: string) => invoke<RemoteMcpState>('remote_mcp_workspace_delete', { id }),
  resume: () => invoke<RemoteMcpState>('remote_mcp_resume'),
};

/** Electron-only bridge; null in web / demo builds. */
export function remoteMcpBridge(): RemoteMcpElectronApiBridge | null {
  const api = (globalThis as { electronAPI?: { remoteMcp?: RemoteMcpElectronApiBridge } }).electronAPI;
  return api?.remoteMcp ?? null;
}
