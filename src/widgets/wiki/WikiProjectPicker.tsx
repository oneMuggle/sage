// Wiki Project Picker - Create or open a wiki project
import {
  FolderPlus,
  FolderOpen,
  FolderSearch,
  X,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useActivityStore } from '../../entities/wiki/activity-store';
import { useLintStore } from '../../entities/wiki/lint-store';
import {
  mockActivities,
  mockLintItems,
  mockResearchTasks,
  mockReviewItems,
} from '../../entities/wiki/mock-data';
import { useResearchStore } from '../../entities/wiki/research-store';
import { useReviewStore } from '../../entities/wiki/review-store';
import { useWikiStore } from '../../entities/wiki/store';
import {
  checkWikiProject,
  createWikiProject,
  getRecentWikiProjects,
  openWikiProject,
  recordRecentWikiProject,
  wikiListDirectory,
} from '../../shared/api-client/wiki';
import type {
  FileNode,
  GraphData,
  ProjectCheckResponse,
  RecentProject,
  WikiProject,
} from '../../shared/types/wiki';

// 演示模式用的模拟数据
const mockFileTree: FileNode[] = [
  {
    name: 'wiki',
    path: 'wiki',
    is_dir: true,
    children: [
      {
        name: 'entities',
        path: 'wiki/entities',
        is_dir: true,
        children: [
          { name: 'api.md', path: 'wiki/entities/api.md', is_dir: false },
          { name: 'user.md', path: 'wiki/entities/user.md', is_dir: false },
          { name: 'graphql.md', path: 'wiki/entities/graphql.md', is_dir: false },
        ],
      },
      {
        name: 'concepts',
        path: 'wiki/concepts',
        is_dir: true,
        children: [
          { name: 'auth.md', path: 'wiki/concepts/auth.md', is_dir: false },
          { name: 'rest.md', path: 'wiki/concepts/rest.md', is_dir: false },
        ],
      },
      {
        name: 'guides',
        path: 'wiki/guides',
        is_dir: true,
        children: [{ name: 'api-guide.md', path: 'wiki/guides/api-guide.md', is_dir: false }],
      },
    ],
  },
];

const mockFileContent = `# API 文档

## 概述

这是一个 **API 文档** 示例页面，演示 Wiki 编辑器。

## 功能

- 📄 Markdown 预览
- ✏️ 编辑模式
- 💾 保存文件
- 🔗 Wiki 链接支持

## 代码示例

\`\`\`typescript
function hello(name: string) {
  return \`Hello, \${name}!\`;
}
\`\`\`

## 相关页面

- [[api-entities|API 实体]]
- [[auth|认证]]
- [[rest|REST API]]

> 这是演示模式，无需后端
`;

// 图谱演示数据
const mockGraphData: GraphData = {
  nodes: [
    {
      id: 'wiki/entities/api.md',
      label: 'api.md',
      page_type: 'entity',
      sources: ['raw/sources/api-docs/rest-api.pdf'],
      wikilinks: ['wiki/concepts/auth.md', 'wiki/concepts/rest.md'],
    },
    {
      id: 'wiki/entities/user.md',
      label: 'user.md',
      page_type: 'entity',
      sources: [],
      wikilinks: ['wiki/entities/api.md'],
    },
    {
      id: 'wiki/entities/graphql.md',
      label: 'graphql.md',
      page_type: 'entity',
      sources: [],
      wikilinks: ['wiki/concepts/rest.md'],
    },
    {
      id: 'wiki/concepts/auth.md',
      label: 'auth.md',
      page_type: 'concept',
      sources: [],
      wikilinks: ['wiki/entities/api.md', 'wiki/guides/api-guide.md'],
    },
    {
      id: 'wiki/concepts/rest.md',
      label: 'rest.md',
      page_type: 'concept',
      sources: [],
      wikilinks: ['wiki/entities/api.md', 'wiki/entities/graphql.md'],
    },
    {
      id: 'wiki/guides/api-guide.md',
      label: 'api-guide.md',
      page_type: 'guide',
      sources: [],
      wikilinks: ['wiki/concepts/auth.md', 'wiki/entities/api.md'],
    },
  ],
  edges: [
    {
      source: 'wiki/entities/api.md',
      target: 'wiki/concepts/auth.md',
      signal: 'DirectLink',
      weight: 1.0,
    },
    {
      source: 'wiki/entities/api.md',
      target: 'wiki/concepts/rest.md',
      signal: 'DirectLink',
      weight: 1.0,
    },
    {
      source: 'wiki/entities/graphql.md',
      target: 'wiki/concepts/rest.md',
      signal: 'DirectLink',
      weight: 1.0,
    },
    {
      source: 'wiki/concepts/auth.md',
      target: 'wiki/entities/api.md',
      signal: 'SourceOverlap',
      weight: 0.6,
    },
    {
      source: 'wiki/concepts/auth.md',
      target: 'wiki/entities/graphql.md',
      signal: 'TypeAffinity',
      weight: 0.8,
    },
  ],
};

// --- Phase 6 (2026-06-27): debounced check + status badge ---

type CheckStatus = 'idle' | 'checking' | 'ok' | 'warn' | 'error';

const DEBOUNCE_MS = 300;

function useDebouncedCheck(
  path: string,
  intent: 'create' | 'open',
  onResult: (r: ProjectCheckResponse) => void,
) {
  const lastReqId = useRef(0);
  // Stabilize callback identity so the effect doesn't re-run on every render.
  const onResultRef = useRef(onResult);
  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  useEffect(() => {
    if (!path) {
      onResultRef.current({
        exists: false,
        writable: false,
        is_project: false,
        parent_writable: false,
        warning: null,
        error: null,
      });
      return;
    }
    const myId = ++lastReqId.current;
    const t = setTimeout(async () => {
      try {
        const result = await checkWikiProject(path, intent);
        if (myId === lastReqId.current) onResultRef.current(result);
      } catch (e) {
        if (myId === lastReqId.current) {
          onResultRef.current({
            exists: false,
            writable: false,
            is_project: false,
            parent_writable: false,
            warning: null,
            error: e instanceof Error ? e.message : '检查失败',
          });
        }
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [path, intent]);
}

export function WikiProjectPicker() {
  const [mode, setMode] = useState<'menu' | 'create' | 'open'>('menu');
  const [name, setName] = useState('');
  const [basePath, setBasePath] = useState('');
  const [openPath, setOpenPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [recents, setRecents] = useState<RecentProject[]>([]);
  const [checkResult, setCheckResult] = useState<ProjectCheckResponse | null>(null);

  const setErrorGlobal = useWikiStore((s) => s.setError);
  const setLintItems = useLintStore((s) => s.setItems);
  const setReviewItems = useReviewStore((s) => s.setItems);
  const setActivities = useActivityStore((s) => s.setItems);
  const setResearchTasks = useResearchStore((s) => s.setTasks);

  // 加载最近项目
  useEffect(() => {
    getRecentWikiProjects()
      .then(setRecents)
      .catch(() => setRecents([]));
  }, []);

  const intent: 'create' | 'open' = mode === 'create' ? 'create' : 'open';
  const activePath = mode === 'create' ? basePath : openPath;
  const setActivePath = mode === 'create' ? setBasePath : setOpenPath;

  // 最近项目的父目录作为文件选择器的默认起始路径
  const defaultStartPath = useMemo(() => {
    if (recents.length === 0) return undefined;
    const parent = recents[0].path.replace(/[^/]+$/, '');
    return parent || undefined;
  }, [recents]);

  // 防抖的路径检查
  useDebouncedCheck(activePath, intent, (r) => setCheckResult(r));

  const checkStatus: CheckStatus = !activePath
    ? 'idle'
    : !checkResult
      ? 'checking'
      : checkResult.error
        ? 'error'
        : checkResult.warning
          ? 'warn'
          : 'ok';

  const canSubmit =
    !!activePath && checkStatus !== 'error' && checkStatus !== 'checking' && !loading;

  const handleBrowse = async () => {
    const api = window.electronAPI as
      | { selectDirectory?: (opts: { intent: 'create' | 'open'; defaultPath?: string }) => Promise<string | null> }
      | undefined;
    if (!api?.selectDirectory) {
      setError('当前环境不支持文件夹选择器');
      return;
    }
    const picked = await api.selectDirectory({ intent, defaultPath: defaultStartPath });
    if (picked) setActivePath(picked);
  };

  const handleCreate = async () => {
    if (!canSubmit) return;
    if (!name.trim()) {
      setError('请填写项目名称和路径');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const project = await createWikiProject(name.trim(), basePath.trim());
      // 从后端获取真实的文件树
      const tree = await wikiListDirectory('', project.path);
      useWikiStore.setState({
        project,
        fileTree: tree,
        selectedFile: null,
        fileContent: '',
        graphData: null,
      });
      await recordRecentWikiProject({ path: project.path, name: project.name, intent: 'create' });
    } catch (e) {
      setError(`创建失败: ${e}`);
      setErrorGlobal(`创建失败: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  const handleOpen = async () => {
    if (!canSubmit) return;
    if (!openPath.trim()) {
      setError('请填写项目路径');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const project = await openWikiProject(openPath.trim());
      // 从后端获取真实的文件树
      const tree = await wikiListDirectory('', project.path);
      useWikiStore.setState({
        project,
        fileTree: tree,
        selectedFile: null,
        fileContent: '',
        graphData: null,
      });
      await recordRecentWikiProject({ path: project.path, name: project.name, intent: 'open' });
    } catch (e) {
      setError(`打开失败: ${e}`);
      setErrorGlobal(`打开失败: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  // 演示模式：直接设置 mock 项目 + 填充所有模拟数据
  const handleDemoMode = () => {
    const demoProject: WikiProject = {
      id: 'demo-project',
      name: '演示项目',
      path: '/demo/path',
    };

    // 一次性设置所有 wiki store 状态（包括 fileTree、selectedFile、fileContent、graphData）
    useWikiStore.setState({
      project: demoProject,
      fileTree: mockFileTree,
      selectedFile: 'wiki/entities/api.md',
      fileContent: mockFileContent,
      graphData: mockGraphData,
    });

    // 填充其他 store 的模拟数据
    setLintItems(mockLintItems);
    setReviewItems(mockReviewItems);
    setActivities(mockActivities);
    setResearchTasks(mockResearchTasks);
  };

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

            {/* 演示模式：直接进入 mock 项目，验证视图切换 */}
            <button
              onClick={handleDemoMode}
              className="flex w-full items-center gap-3 rounded-lg border-2 border-primary/30 bg-primary/5 p-4 text-left hover:bg-primary/10 transition-colors"
            >
              <Sparkles className="h-5 w-5 text-primary" />
              <div>
                <div className="text-sm font-medium text-text">演示模式</div>
                <div className="text-xs text-muted">使用模拟数据浏览所有视图（推荐）</div>
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
              <div className="flex gap-2">
                <input
                  type="text"
                  value={basePath}
                  onChange={(e) => setBasePath(e.target.value)}
                  placeholder="/home/user/wiki-projects"
                  className="flex-1 px-3 py-2 border border-border rounded-radius-sm text-sm font-mono bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <button
                  type="button"
                  onClick={handleBrowse}
                  data-testid="browse-btn"
                  className="px-3 py-2 border border-border rounded-radius-sm text-sm bg-surface hover:bg-surface-hover flex items-center gap-1"
                >
                  <FolderSearch size={14} /> 浏览…
                </button>
              </div>
              <StatusBadge status={checkStatus} result={checkResult} />
            </div>
            <button
              onClick={handleCreate}
              disabled={!canSubmit}
              className="w-full px-4 py-2 bg-primary text-text-inverse text-sm rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="inline-flex items-center">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 创建中...
                </span>
              ) : (
                '创建项目'
              )}
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
              <div className="flex gap-2">
                <input
                  type="text"
                  value={openPath}
                  onChange={(e) => setOpenPath(e.target.value)}
                  placeholder="/home/user/wiki-projects/my-wiki"
                  className="flex-1 px-3 py-2 border border-border rounded-radius-sm text-sm font-mono bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <button
                  type="button"
                  onClick={handleBrowse}
                  data-testid="browse-btn"
                  className="px-3 py-2 border border-border rounded-radius-sm text-sm bg-surface hover:bg-surface-hover flex items-center gap-1"
                >
                  <FolderSearch size={14} /> 浏览…
                </button>
              </div>
              <StatusBadge status={checkStatus} result={checkResult} />
            </div>
            <button
              onClick={handleOpen}
              disabled={!canSubmit}
              className="w-full px-4 py-2 bg-primary text-text-inverse text-sm rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <span className="inline-flex items-center">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 打开中...
                </span>
              ) : (
                '打开项目'
              )}
            </button>
          </div>
        )}

        {error && <div className="mt-4 rounded-md bg-error/10 p-3 text-xs text-error">{error}</div>}
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  result,
}: {
  status: CheckStatus;
  result: ProjectCheckResponse | null;
}) {
  if (status === 'idle') return null;
  if (status === 'checking') {
    return (
      <div
        className="flex items-center gap-1 text-xs text-muted mt-1"
        data-testid="status-checking"
      >
        <Loader2 size={12} className="animate-spin" /> 检查中…
      </div>
    );
  }
  if (status === 'ok') {
    return (
      <div className="flex items-center gap-1 text-xs text-green-600 mt-1" data-testid="status-ok">
        <CheckCircle2 size={12} /> {result?.is_project ? '有效的 wiki 项目' : '可创建'}
      </div>
    );
  }
  if (status === 'warn') {
    return (
      <div
        className="flex items-center gap-1 text-xs text-yellow-600 mt-1"
        data-testid="status-warn"
      >
        <AlertTriangle size={12} /> {result?.warning ?? '将建立结构'}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1 text-xs text-red-500 mt-1" data-testid="status-error">
      <XCircle size={12} /> {result?.error ?? '检查失败'}
    </div>
  );
}
