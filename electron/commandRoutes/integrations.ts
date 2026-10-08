import type { CommandRoute } from '../commands';

export const integrationRoutes: Record<string, CommandRoute> = {

  // M3: MCP multi-server management (backend/api/mcp_routes.py).
  // mcp_server_add: args are the full server config, forwarded as body.
  // mcp_server_update: name goes in the path; body carries only the
  // merge-patch fields (enabled / timeout_seconds) — extra=forbid on the
  // backend model means name must NOT leak into the body.
  mcp_status: { method: 'GET', path: () => '/api/v1/mcp/status' },
  mcp_servers: { method: 'GET', path: () => '/api/v1/mcp/servers' },
  // rawBody: env keys are user-defined (API_TOKEN, PATH, …) and must not
  // pass through camelToSnakeKeys; mcpClient sends snake_case keys.
  mcp_server_add: { method: 'POST', path: () => '/api/v1/mcp/servers', rawBody: true },
  mcp_server_update: {
    method: 'PATCH',
    path: (a) => `/api/v1/mcp/servers/${encodeURIComponent(String(a.name))}`,
    body: (a) => {
      const body: Record<string, unknown> = {};
      if (a.enabled !== undefined) body.enabled = a.enabled;
      if (a.timeout_seconds !== undefined) body.timeout_seconds = a.timeout_seconds;
      return body;
    },
  },
  mcp_server_delete: {
    method: 'DELETE',
    path: (a) => `/api/v1/mcp/servers/${encodeURIComponent(String(a.name))}`,
  },

  // Zotero: read-only library access (backend/api/zotero_routes.py).
  // Settings UI uses these to show connection status, library stats, browse
  // collections, and search items — all via the Zotero SQLite client.
  zotero_status: { method: 'GET', path: () => '/api/v1/zotero/status' },
  zotero_search: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a.q) params.set('q', String(a.q));
      if (a.collection_key) params.set('collection_key', String(a.collection_key));
      if (a.tag) params.set('tag', String(a.tag));
      if (a.limit) params.set('limit', String(a.limit));
      return `/api/v1/zotero/search?${params.toString()}`;
    },
  },
  zotero_item: {
    method: 'GET',
    path: (a) => `/api/v1/zotero/items/${encodeURIComponent(String(a.item_key))}`,
  },
  zotero_annotations: {
    method: 'GET',
    path: (a) => `/api/v1/zotero/items/${encodeURIComponent(String(a.item_key))}/annotations`,
  },
  zotero_collections: {
    method: 'GET',
    path: (a) => {
      const params = new URLSearchParams();
      if (a.parent_key) params.set('parent_key', String(a.parent_key));
      return `/api/v1/zotero/collections?${params.toString()}`;
    },
  },
  zotero_set_path: {
    method: 'POST',
    path: (a) => `/api/v1/zotero/path?path=${encodeURIComponent(String(a.path ?? ''))}`,
  },
};
