// Wiki Zustand store
import { create } from 'zustand'
import { wikiListDirectory, wikiReadFile, wikiWriteFile, wikiDeleteFile } from '../lib/wiki-api'
import type { WikiProject, FileNode, WikiView } from '../types/wiki'

interface WikiStoreState {
  project: WikiProject | null
  fileTree: FileNode[]
  selectedFile: string | null
  fileContent: string
  activeView: WikiView
  isLoading: boolean
  error: string | null

  setProject: (project: WikiProject | null) => void
  loadFileTree: () => Promise<void>
  openFile: (path: string) => Promise<void>
  saveFile: (path: string, content: string) => Promise<void>
  deleteFile: (path: string) => Promise<void>
  setSelectedFile: (path: string | null) => void
  setFileContent: (content: string) => void
  setActiveView: (view: WikiView) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
}

export const useWikiStore = create<WikiStoreState>((set, get) => ({
  project: null,
  fileTree: [],
  selectedFile: null,
  fileContent: '',
  activeView: 'browser',
  isLoading: false,
  error: null,

  setProject: (project) => set({ project, fileTree: [], selectedFile: null, fileContent: '' }),

  loadFileTree: async () => {
    const { project } = get()
    if (!project) return
    set({ isLoading: true })
    try {
      const tree = await wikiListDirectory('', project.path)
      set({ fileTree: tree, isLoading: false })
    } catch (e) {
      set({ error: `加载文件树失败: ${e}`, isLoading: false })
    }
  },

  openFile: async (path) => {
    const { project } = get()
    if (!project) return
    set({ isLoading: true, selectedFile: path })
    try {
      const content = await wikiReadFile(path, project.path)
      set({ fileContent: content, isLoading: false })
    } catch (e) {
      set({ error: `读取文件失败: ${e}`, isLoading: false })
    }
  },

  saveFile: async (path, content) => {
    const { project } = get()
    if (!project) return
    set({ isLoading: true })
    try {
      await wikiWriteFile(path, content, project.path)
      set({ fileContent: content, isLoading: false })
      await get().loadFileTree()
    } catch (e) {
      set({ error: `保存文件失败: ${e}`, isLoading: false })
    }
  },

  deleteFile: async (path) => {
    const { project } = get()
    if (!project) return
    try {
      await wikiDeleteFile(path, project.path)
      if (get().selectedFile === path) {
        set({ selectedFile: null, fileContent: '' })
      }
      await get().loadFileTree()
    } catch (e) {
      set({ error: `删除文件失败: ${e}` })
    }
  },

  setSelectedFile: (path) => set({ selectedFile: path }),
  setFileContent: (content) => set({ fileContent: content }),
  setActiveView: (view) => set({ activeView: view }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}))
