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
};
