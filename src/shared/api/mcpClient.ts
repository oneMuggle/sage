/**
 * IPC client for MCP multi-server management (M3).
 *
 * Translates to backend HTTP via Electron preload:
 *   mcp_status        → GET    /api/v1/mcp/status
 *   mcp_servers       → GET    /api/v1/mcp/servers
 *   mcp_server_add    → POST   /api/v1/mcp/servers        (rawBody)
 *   mcp_server_update → PATCH  /api/v1/mcp/servers/{name}
 *   mcp_server_delete → DELETE /api/v1/mcp/servers/{name}
 *
 * Responses arrive snake_case (backend contract). Add/update inputs are
 * snake_case by construction: mcp_server_add is a rawBody route, so env
 * keys (user-defined names like PATH / API_TOKEN) never pass through the
 * camelCase→snake_case bridge.
 *
 * All methods throw on IPC failure; McpTab surfaces errors inline.
 */
import { invoke } from './desktopInvoke';

export type McpServerState = 'discovering' | 'ready' | 'failed' | 'disabled';

export interface McpServerStatusEntry {
  name: string;
  state: McpServerState;
  tool_count: number;
  last_error: string | null;
  since: number;
  required: boolean;
}

export interface McpStatusReport {
  generated_at: number;
  all_ready: boolean;
  degraded: boolean;
  failed_required: boolean;
  servers: McpServerStatusEntry[];
}

export interface McpServerConfig {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  required: boolean;
  timeout_seconds: number;
  builtin: boolean;
}

export interface AddMcpServerInput {
  name: string;
  command: string;
  args: string[];
  required: boolean;
}

export interface UpdateMcpServerChanges {
  enabled?: boolean;
  timeoutSeconds?: number;
}

export const MCP_NAME_REGEX = /^[a-z0-9_-]{1,64}$/;

export const mcpClient = {
  async status(): Promise<McpStatusReport> {
    return invoke<McpStatusReport>('mcp_status', {});
  },

  async listServers(): Promise<McpServerConfig[]> {
    const resp = await invoke<{ servers: McpServerConfig[] }>('mcp_servers', {});
    return resp.servers;
  },

  async addServer(input: AddMcpServerInput): Promise<{ ok: boolean; name: string; state: McpServerState }> {
    // rawBody route: keys already snake_case, env omitted (no UI field).
    return invoke('mcp_server_add', {
      name: input.name,
      command: input.command,
      args: input.args,
      env: {},
      enabled: true,
      required: input.required,
      timeout_seconds: 30,
    });
  },

  async updateServer(
    name: string,
    changes: UpdateMcpServerChanges,
  ): Promise<{ ok: boolean; name: string; state: McpServerState }> {
    return invoke('mcp_server_update', {
      name,
      enabled: changes.enabled,
      timeout_seconds: changes.timeoutSeconds,
    });
  },

  async deleteServer(name: string): Promise<{ ok: boolean; name: string }> {
    return invoke('mcp_server_delete', { name });
  },
};
