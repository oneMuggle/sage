/**
 * Duplicate-group listing types (Phase 1 Item A: 文档库重复清理).
 *
 * Backend counterpart: `GET /api/v1/office/documents/duplicate-groups`
 * (`backend/api/office_dedup_routes.py`).
 */

import type { OfficeDocumentSummary } from './types';

/**
 * Live documents in one workspace that share identical bytes. The
 * backend groups by `office_document_hashes.content_hash`; members
 * within a group are returned newest-first so the UI can offer
 * "keep newest, archive the rest" without additional sorting.
 */
export interface OfficeDuplicateGroup {
  /** `sha256:<64 hex>` digest shared by every document in the group. */
  content_hash: string;
  /** Live documents that hold the same bytes, newest first. */
  documents: OfficeDocumentSummary[];
}

/**
 * Response of GET /office/documents/duplicate-groups — every group of
 * live documents whose content hash collides, newest group first.
 * Singleton groups are never returned; documents without a stored
 * hash (imported before content hashing existed) are excluded.
 */
export interface OfficeDuplicateGroupsResult {
  groups: OfficeDuplicateGroup[];
  total: number;
}
