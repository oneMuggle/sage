// Wiki Project Picker - Create or open a wiki project
import { FolderPlus, FolderOpen, X } from 'lucide-react'
import { useState } from 'react'

import { createWikiProject, openWikiProject } from '../../lib/wiki-api'
import { useWikiStore } from '../../stores/wiki-store'

export function WikiProjectPicker() {
  const [mode, setMode] = useState<'menu' | 'create' | 'open'>('menu')
  const [name, setName] = useState('')
  const [basePath, setBasePath] = useState('')
  const [openPath, setOpenPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const setProject = useWikiStore((s) => s.setProject)
  const setErrorGlobal = useWikiStore((s) => s.setError)

  const handleCreate = async () => {
    if (!name.trim() || !basePath.trim()) {
      setError('请填写项目名称和路径')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const project = await createWikiProject(name.trim(), basePath.trim())
      setProject(project)
    } catch (e) {
      setError(`创建失败: ${e}`)
      setErrorGlobal(`创建失败: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleOpen = async () => {
    if (!openPath.trim()) {
      setError('请填写项目路径')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const project = await openWikiProject(openPath.trim())
      setProject(project)
    } catch (e) {
      setError(`打开失败: ${e}`)
      setErrorGlobal(`打开失败: ${e}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-bg-muted/50">
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-lg">
        <h3 className="text-lg font-semibold text-text mb-4">LLM Wiki</h3>

        {mode === 'menu' && (
          <div className="space-y-3">
            <button
              onClick={() => setMode('create')}
              className="flex w-full items-center gap-3 rounded-lg border border-border p-4 text-left hover:bg-bg-muted transition-colors"
            >
              <FolderPlus className="h-5 w-5 text-primary" />
              <div>
                <div className="text-sm font-medium text-text">创建新项目</div>
                <div className="text-xs text-muted">创建一个新的 wiki 知识库</div>
              </div>
            </button>
            <button
              onClick={() => setMode('open')}
              className="flex w-full items-center gap-3 rounded-lg border border-border p-4 text-left hover:bg-bg-muted transition-colors"
            >
              <FolderOpen className="h-5 w-5 text-primary" />
              <div>
                <div className="text-sm font-medium text-text">打开现有项目</div>
                <div className="text-xs text-muted">打开已有的 wiki 项目</div>
              </div>
            </button>
          </div>
        )}

        {mode === 'create' && (
          <div className="space-y-4">
            <button
              onClick={() => setMode('menu')}
              className="flex items-center gap-1 text-xs text-muted hover:text-text"
            >
              <X className="h-3 w-3" /> 返回
            </button>
            <div>
              <label className="text-xs text-muted block mb-1">项目名称</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="我的知识库"
                className="w-full px-3 py-2 border border-border rounded-radius-sm text-sm bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div>
              <label className="text-xs text-muted block mb-1">存储路径</label>
              <input
                type="text"
                value={basePath}
                onChange={(e) => setBasePath(e.target.value)}
                placeholder="/home/user/wiki-projects"
                className="w-full px-3 py-2 border border-border rounded-radius-sm text-sm font-mono bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <button
              onClick={handleCreate}
              disabled={loading}
              className="w-full px-4 py-2 bg-primary text-text-inverse text-sm rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-50"
            >
              {loading ? '创建中...' : '创建项目'}
            </button>
          </div>
        )}

        {mode === 'open' && (
          <div className="space-y-4">
            <button
              onClick={() => setMode('menu')}
              className="flex items-center gap-1 text-xs text-muted hover:text-text"
            >
              <X className="h-3 w-3" /> 返回
            </button>
            <div>
              <label className="text-xs text-muted block mb-1">项目路径</label>
              <input
                type="text"
                value={openPath}
                onChange={(e) => setOpenPath(e.target.value)}
                placeholder="/home/user/wiki-projects/my-wiki"
                className="w-full px-3 py-2 border border-border rounded-radius-sm text-sm font-mono bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <button
              onClick={handleOpen}
              disabled={loading}
              className="w-full px-4 py-2 bg-primary text-text-inverse text-sm rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-50"
            >
              {loading ? '打开中...' : '打开项目'}
            </button>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-md bg-error/10 p-3 text-xs text-error">{error}</div>
        )}
      </div>
    </div>
  )
}
