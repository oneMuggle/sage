/**
 * IPC client for Zotero library access (settings UI).
 *
 * Translates to backend HTTP via Electron preload:
 *   zotero_status       → GET  /api/v1/zotero/status
 *   zotero_search       → GET  /api/v1/zotero/search?q=&collection_key=&tag=&limit=
 *   zotero_item         → GET  /api/v1/zotero/items/{item_key}
 *   zotero_annotations  → GET  /api/v1/zotero/items/{item_key}/annotations
 *   zotero_collections  → GET  /api/v1/zotero/collections?parent_key=
 *   zotero_set_path     → POST /api/v1/zotero/path?path=
 *   zotero_sync         → POST /api/v1/zotero/sync          body {force, project_path}
 *   zotero_sync_status  → GET  /api/v1/zotero/sync-status
 *
 * Wiki tag is a plain preferences KV (`zotero_wiki_tag`), not a Zotero route.
 *
 * All methods throw on IPC failure; ZoteroTab surfaces errors inline.
 */
import { invoke } from './desktopInvoke';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ZoteroStatus {
  available: boolean;
  db_path: string | null;
  error: string | null;
  stats: ZoteroStats | null;
}

export interface ZoteroStats {
  items: number;
  collections: number;
  tags: number;
  attachments: number;
}

export interface ZoteroItemSummary {
  key: string;
  title: string;
  item_type: string;
  year: number | null;
  authors: string[];
  abstract: string | null;
  collections: string[];
  tags: string[];
  date_added: string | null;
}

export interface ZoteroItemDetail extends ZoteroItemSummary {
  date_modified: string | null;
  extra: string | null;
  doi: string | null;
  url: string | null;
  attachments: ZoteroAttachment[];
}

export interface ZoteroAttachment {
  key: string;
  filename: string;
  path: string | null;
  content_type: string | null;
}

export interface ZoteroCollection {
  key: string;
  name: string;
  parent_key: string | null;
  item_count: number;
  version: number;
}

export interface ZoteroAnnotation {
  key: string;
  type: string;
  text: string | null;
  comment: string | null;
  color: string | null;
  page_label: string | null;
  date_added: string | null;
}

/** Outcome of the wiki-sinking half of a sync (backend `wiki_export.py`). */
export interface ZoteroSyncWikiResult {
  items_exported?: number;
  authors_exported?: number;
  errors?: string[];
  /** Set when the whole wiki export failed (e.g. project path missing). */
  error?: string;
}

/** `POST /api/v1/zotero/sync` response. */
export interface ZoteroSyncResult {
  items: number;
  chunks: number;
  dim: number;
  last_sync_ts: string | null;
  skipped: boolean;
  elapsed_ms: number;
  errors: string[];
  wiki?: ZoteroSyncWikiResult;
}

/** `GET /api/v1/zotero/sync-status` response. */
export interface ZoteroSyncStatus {
  last_sync_ts: string | null;
  last_sync_at: string | null;
  item_count: number;
  wiki_page_count: number;
  embedding_configured: boolean;
  vector_dim: number | null;
  sync_in_progress: boolean;
  errors: string[];
}

/** Zotero tag whose items are sunk into wiki pages; mirrors backend default. */
export const DEFAULT_WIKI_TAG = 'sage:wiki';

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export const zoteroClient = {
  async status(): Promise<ZoteroStatus> {
    return invoke<ZoteroStatus>('zotero_status', {});
  },

  async search(params: {
    q?: string;
    collection_key?: string;
    tag?: string;
    limit?: number;
  }): Promise<ZoteroItemSummary[]> {
    return invoke<ZoteroItemSummary[]>('zotero_search', params);
  },

  async getItem(itemKey: string): Promise<ZoteroItemDetail> {
    return invoke<ZoteroItemDetail>('zotero_item', { item_key: itemKey });
  },

  async getAnnotations(itemKey: string): Promise<ZoteroAnnotation[]> {
    return invoke<ZoteroAnnotation[]>('zotero_annotations', { item_key: itemKey });
  },

  async listCollections(parentKey?: string): Promise<ZoteroCollection[]> {
    return invoke<ZoteroCollection[]>('zotero_collections', {
      parent_key: parentKey ?? null,
    });
  },

  async setPath(path: string): Promise<{ ok: boolean; db_path: string }> {
    return invoke<{ ok: boolean; db_path: string }>('zotero_set_path', { path });
  },

  /**
   * Run the index-layer sync.
   *
   * `force` rebuilds from scratch; default is incremental (watermark based).
   * `projectPath` additionally sinks tag-marked items into `<project>/wiki/zotero/`.
   * Omit it to index only — the backend skips wiki export without a project root.
   */
  async sync(options: { force?: boolean; projectPath?: string | null } = {}): Promise<ZoteroSyncResult> {
    return invoke<ZoteroSyncResult>('zotero_sync', {
      force: options.force ?? false,
      project_path: options.projectPath ?? null,
    });
  },

  async syncStatus(): Promise<ZoteroSyncStatus> {
    return invoke<ZoteroSyncStatus>('zotero_sync_status', {});
  },

  /** Read the wiki-sinking tag; falls back to `sage:wiki` when unset. */
  async getWikiTag(): Promise<string> {
    const pref = await invoke<{ value: string | null } | null>('get_preference', {
      key: 'zotero_wiki_tag',
    });
    return (pref?.value ?? '').trim() || DEFAULT_WIKI_TAG;
  },

  /** Persist the wiki-sinking tag; empty input resets to the default. */
  async setWikiTag(tag: string): Promise<void> {
    await invoke('set_preference', {
      key: 'zotero_wiki_tag',
      value: tag.trim() || DEFAULT_WIKI_TAG,
      value_type: 'string',
      category: 'general',
    });
  },
};

export function auditZoteroClientGovernance(
  state: {
    connected?: boolean;
    indexedItemCount?: number;
  } = {},
): {
  module: 'src/shared/api/zoteroClient.ts';
  phase: 'P146';
  connected: boolean;
  indexedItemCount: number;
  healthy: boolean;
} {
  const connected = state.connected !== false;
  const indexedItemCount =
    typeof state.indexedItemCount === 'number' && Number.isFinite(state.indexedItemCount)
      ? Math.max(0, Math.trunc(state.indexedItemCount))
      : 0;
  return {
    module: 'src/shared/api/zoteroClient.ts',
    phase: 'P146',
    connected,
    indexedItemCount,
    healthy: connected && indexedItemCount >= 0,
  };
}
