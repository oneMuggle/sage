// Wiki Zustand store
import { create } from 'zustand';

import {
  wikiListDirectory,
  wikiReadFile,
  wikiWriteFile,
  wikiDeleteFile,
  wikiRenameFile,
  getWikiGraph,
} from '../../shared/api-client/wiki';
import type { WikiProject, FileNode, WikiView, GraphData } from '../../shared/types/wiki';

interface WikiStoreState {
  project: WikiProject | null;
  fileTree: FileNode[];
  selectedFile: string | null;
  fileContent: string;
  activeView: WikiView;
  isLoading: boolean;
  error: string | null;
  graphData: GraphData | null;
  graphQuery: string;

  setProject: (project: WikiProject | null) => void;
  loadFileTree: () => Promise<void>;
  openFile: (path: string) => Promise<void>;
  saveFile: (path: string, content: string) => Promise<void>;
  deleteFile: (path: string) => Promise<void>;
  /** 在目录下新建 Markdown 文件（目录为空串表示根目录）。 */
  createFile: (dirPath: string, name: string) => Promise<void>;
  /** 重命名文件（同目录内改名，保留扩展名由调用方决定）。 */
  renameFile: (path: string, newName: string) => Promise<void>;
  setSelectedFile: (path: string | null) => void;
  setFileContent: (content: string) => void;
  setActiveView: (view: WikiView) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  loadGraph: (query?: string) => Promise<void>;
  setGraphQuery: (q: string) => void;
}

export const useWikiStore = create<WikiStoreState>((set, get) => ({
  project: null,
  fileTree: [],
  selectedFile: null,
  fileContent: '',
  activeView: 'browser',
  isLoading: false,
  graphData: null,
  graphQuery: '',
  error: null,

  setProject: (project) => set({ project, fileTree: [], selectedFile: null, fileContent: '' }),

  loadFileTree: async () => {
    const { project } = get();
    if (!project) return;
    set({ isLoading: true });
    try {
      const tree = await wikiListDirectory('', project.path);
      set({ fileTree: tree, isLoading: false });
    } catch (e) {
      set({ error: `加载文件树失败: ${e}`, isLoading: false });
    }
  },

  openFile: async (path) => {
    const { project } = get();
    if (!project) return;
    set({ isLoading: true, selectedFile: path });
    try {
      const content = await wikiReadFile(path, project.path);
      set({ fileContent: content, isLoading: false });
    } catch (e) {
      set({ error: `读取文件失败: ${e}`, isLoading: false });
    }
  },

  saveFile: async (path, content) => {
    const { project } = get();
    if (!project) return;
    set({ isLoading: true });
    try {
      await wikiWriteFile(path, content, project.path);
      set({ fileContent: content, isLoading: false });
      await get().loadFileTree();
    } catch (e) {
      set({ error: `保存文件失败: ${e}`, isLoading: false });
    }
  },

  deleteFile: async (path) => {
    const { project } = get();
    if (!project) return;
    try {
      await wikiDeleteFile(path, project.path);
      const selected = get().selectedFile;
      if (selected === path || (selected?.startsWith(`${path}/`) ?? false)) {
        set({ selectedFile: null, fileContent: '' });
      }
      await get().loadFileTree();
    } catch (e) {
      set({ error: `删除文件失败: ${e}` });
      throw e;
    }
  },

  createFile: async (dirPath, name) => {
    const { project } = get();
    if (!project) return;
    const normalized = name.trim();
    if (!normalized) throw new Error('name required');
    const path = dirPath ? `${dirPath}/${normalized}` : normalized;
    set({ isLoading: true });
    try {
      const title = normalized.replace(/\.md$/i, '');
      await wikiWriteFile(path, `# ${title}\n\n`, project.path);
      set({ isLoading: false });
      await get().loadFileTree();
    } catch (e) {
      set({ error: `新建文件失败: ${e}`, isLoading: false });
      throw e;
    }
  },

  renameFile: async (path, newName) => {
    const { project } = get();
    if (!project) return;
    const normalized = newName.trim();
    if (!normalized) throw new Error('name required');
    const separator = path.lastIndexOf('/');
    const dir = separator >= 0 ? path.slice(0, separator) : '';
    const nextPath = dir ? `${dir}/${normalized}` : normalized;
    if (nextPath === path) return;
    set({ isLoading: true });
    try {
      await wikiRenameFile(path, nextPath, project.path);
      if (get().selectedFile === path) set({ selectedFile: nextPath });
      set({ isLoading: false });
      await get().loadFileTree();
    } catch (e) {
      set({ error: `重命名失败: ${e}`, isLoading: false });
      throw e;
    }
  },

  setSelectedFile: (path) => set({ selectedFile: path }),
  setFileContent: (content) => set({ fileContent: content }),
  setActiveView: (view) => set({ activeView: view }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),

  loadGraph: async (query) => {
    const { project } = get();
    if (!project) return;
    set({ isLoading: true, error: null });
    try {
      const q = query ?? get().graphQuery;
      const data = await getWikiGraph(project.path, q || undefined, 100);
      set({ graphData: data, isLoading: false });
    } catch (e) {
      set({ error: `加载图谱失败: ${e}`, isLoading: false });
    }
  },
  setGraphQuery: (q) => set({ graphQuery: q }),
}));

// HMR 支持：防止 Vite 热更新时创建多个 store 实例
declare global {
  var __sageWikiStore: typeof useWikiStore | undefined;
}

// HMR 支持：防止 Vite 热更新时创建多个 store 实例
declare global {
  var __sageWikiStore: typeof useWikiStore | undefined;
}

if (import.meta.hot) {
  if (globalThis.__sageWikiStore) {
    globalThis.__sageWikiStore.setState(useWikiStore.getState());
  }
  globalThis.__sageWikiStore = useWikiStore;
}

export interface WikiStoreAuditInput {
  hasProject?: boolean;
  fileTreeCount?: number;
  selectedFile?: string | null;
  activeView?: WikiView;
  isLoading?: boolean;
  hasError?: boolean;
}

export function buildWikiStoreAuditSnapshot(input: WikiStoreAuditInput = {}): string {
  const hasProject = Boolean(input.hasProject);
  const fileTreeCount = Math.max(0, input.fileTreeCount ?? 0);
  const selectedFile = (input.selectedFile ?? '').trim() || 'none';
  const activeView = input.activeView ?? 'browser';
  const isLoading = Boolean(input.isLoading);
  const hasError = Boolean(input.hasError);
  return `project:${hasProject ? 'yes' : 'no'}|tree:${fileTreeCount}|file:${selectedFile}|view:${activeView}|loading:${isLoading ? 'yes' : 'no'}|err:${hasError ? 'yes' : 'no'}`;
}

export function buildWikiStoreAuditJson(input: WikiStoreAuditInput = {}): string {
  const hasProject = Boolean(input.hasProject);
  const fileTreeCount = Math.max(0, input.fileTreeCount ?? 0);
  const selectedFile = (input.selectedFile ?? '').trim() || 'none';
  const activeView = input.activeView ?? 'browser';
  const isLoading = Boolean(input.isLoading);
  const hasError = Boolean(input.hasError);
  return JSON.stringify({
    hasProject,
    fileTreeCount,
    selectedFile,
    activeView,
    isLoading,
    hasError,
    snapshot: buildWikiStoreAuditSnapshot(input),
  });
}

export function auditWikiStoreGovernance(
  state: {
    pageCount?: number;
    activeSlug?: string;
  } = {},
): {
  module: 'src/entities/wiki/store.ts';
  phase: 'P157';
  pageCount: number;
  activeSlug: string;
  healthy: boolean;
} {
  const pageCount =
    typeof state.pageCount === 'number' && Number.isFinite(state.pageCount)
      ? Math.max(0, Math.trunc(state.pageCount))
      : 1;
  const activeSlug =
    typeof state.activeSlug === 'string' && state.activeSlug.trim().length > 0
      ? state.activeSlug.trim()
      : 'index';
  return {
    module: 'src/entities/wiki/store.ts',
    phase: 'P157',
    pageCount,
    activeSlug,
    healthy: pageCount >= 1 && activeSlug.length > 0,
  };
}
