import { invoke } from './desktopInvoke';
import type {
  OfficeDocType,
  SessionWorkspaceBinding,
  WorkspaceRevokeResponse,
  WorkspaceSearchKind,
  WorkspaceSearchResponse,
  WorkspaceSearchResult,
} from './types';
import { handleApiError } from './utils';

interface WorkspaceBindingWire {
  session_id: string;
  workspace_path: string;
  generation: number;
  activated_at: number;
  revoked_at: number | null;
}

interface WorkspaceSearchResultWire {
  name: string;
  kind: WorkspaceSearchKind;
  doc_type: OfficeDocType | null;
  doc_id: string | null;
  size_bytes: number;
  needs_import: boolean;
  source_path: string | null;
}

interface WorkspaceBindWireResponse {
  binding: WorkspaceBindingWire;
}

interface WorkspaceGetWireResponse {
  binding: WorkspaceBindingWire | null;
}

interface WorkspaceSearchWireResponse {
  results: WorkspaceSearchResultWire[];
  total: number;
}

function mapBinding(binding: WorkspaceBindingWire): SessionWorkspaceBinding {
  return {
    sessionId: binding.session_id,
    workspacePath: binding.workspace_path,
    generation: binding.generation,
    activatedAt: binding.activated_at,
    revokedAt: binding.revoked_at,
  };
}

function mapSearchResult(result: WorkspaceSearchResultWire): WorkspaceSearchResult {
  return {
    name: result.name,
    kind: result.kind,
    docType: result.doc_type,
    docId: result.doc_id,
    sizeBytes: result.size_bytes,
    needsImport: result.needs_import,
    sourcePath: result.source_path,
  };
}

export const workspaceApi = {
  async bind(
    sessionId: string,
    workspacePath: string,
  ): Promise<{ binding: SessionWorkspaceBinding }> {
    try {
      const response = await invoke<WorkspaceBindWireResponse>('workspace_bind', {
        sessionId,
        workspacePath,
      });
      return { binding: mapBinding(response.binding) };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async get(sessionId: string): Promise<{ binding: SessionWorkspaceBinding | null }> {
    try {
      const response = await invoke<WorkspaceGetWireResponse>('workspace_get', { sessionId });
      return {
        binding: response.binding === null ? null : mapBinding(response.binding),
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async revoke(sessionId: string): Promise<WorkspaceRevokeResponse> {
    try {
      return await invoke<WorkspaceRevokeResponse>('workspace_revoke', { sessionId });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async search(
    sessionId: string,
    query: string,
    limit: number = 20,
  ): Promise<WorkspaceSearchResponse> {
    try {
      const response = await invoke<WorkspaceSearchWireResponse>('workspace_search_files', {
        sessionId,
        query,
        limit,
      });
      return {
        results: response.results.map(mapSearchResult),
        total: response.total,
      };
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
