// src/widgets/chat/artifacts/ArtifactsSection.tsx
import { RefreshCw, FolderOpen } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';
import { useTaskCenterStore } from '../../../features/task-center/taskCenterStore';
import type { WordFormatSpec } from '../../../shared/api/types';

import { ArtifactRow } from './ArtifactRow';

function deriveWorkspacePath(filePath: string, explicitWorkspace?: string | null): string {
  if (explicitWorkspace && explicitWorkspace.trim()) {
    return explicitWorkspace.trim();
  }
  const normalized = filePath.replace(/\\/g, '/');
  const idx = normalized.lastIndexOf('/');
  return idx > 0 ? filePath.slice(0, idx) : filePath;
}

function parseFormatSpec(raw?: string | null): WordFormatSpec | null {
  if (!raw || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as WordFormatSpec) : null;
  } catch {
    return null;
  }
}

interface ArtifactsSectionProps {
  artifacts: Artifact[];
  loading: boolean;
  sessionId: string | null;
  onRefresh: () => void;
  onSelect: (artifact: Artifact) => void;
  onReveal: (artifact: Artifact) => void;
}

// right-panel R4 批次 C: 产物类型过滤分组（kind → 展示组）
type KindFilter = 'all' | 'code' | 'doc' | 'sheet' | 'image';

const FILTER_GROUPS: ReadonlyArray<{ key: KindFilter; label: string; kinds: ReadonlySet<string> }> = [
  { key: 'all', label: '全部', kinds: new Set<string>() },
  {
    key: 'code',
    label: '代码',
    kinds: new Set(['code', 'json']),
  },
  {
    key: 'doc',
    label: '文档',
    kinds: new Set(['markdown', 'text', 'pdf', 'docx', 'pptx']),
  },
  {
    key: 'sheet',
    label: '表格',
    kinds: new Set(['csv', 'xlsx']),
  },
  {
    key: 'image',
    label: '图片',
    kinds: new Set(['image']),
  },
];

function groupOf(kind: ArtifactKind): KindFilter {
  const group = FILTER_GROUPS.find(
    (g) => g.key !== 'all' && g.kinds.has(kind),
  );
  return group?.key ?? 'doc'; // 未识别类型归入文档组兜底展示
}

export function ArtifactsSection({
  artifacts,
  loading,
  sessionId,
  onRefresh,
  onSelect,
  onReveal,
}: ArtifactsSectionProps) {
  // right-panel R4 批次 C: 类型过滤（仅影响列表渲染，计数徽标口径不变）
  const [filter, setFilter] = useState<KindFilter>('all');
  const openDelivery = useTaskCenterStore((s) => s.openDelivery);

  const filtered = useMemo(
    () =>
      filter === 'all'
        ? artifacts
        : artifacts.filter((a) => groupOf(a.kind) === filter),
    [artifacts, filter],
  );

  if (!sessionId) {
    return <div className="p-3 text-sm text-muted">请先选择会话</div>;
  }

  // F1: Office 产物一键打开 OfficeDeliveryDrawer（质检 + 排版修复 + 对比）
  const handleOpenDelivery = (artifact: Artifact) => {
    openDelivery({
      kind: 'office',
      entryId: `artifact:${artifact.id}`,
      ref: {
        workspacePath: deriveWorkspacePath(artifact.path, artifact.workspace_path),
        filePath: artifact.path,
        formatSpec: parseFormatSpec(artifact.format_spec),
      },
    });
  };

  // P2-3.11: 双击 Artifact → 弹出独立窗口 (仅 HTML 类型)
  const handleDoubleClick = (artifact: Artifact) => {
    if (!window.electronAPI?.openArtifactWindow) return;
    // artifact.path 来自后端,格式: /abs/path/to/artifact.html
    window.electronAPI
      .openArtifactWindow({
        id: artifact.id,
        name: artifact.name,
        kind: artifact.kind,
        path: artifact.path,
      })
      .catch(() => {
        // 静默失败:不支持的类型或 IPC 错误
      });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-end gap-1 px-2 py-1 border-b border-border">
        {artifacts.length > 0 && (
          <button
            className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
            title="在文件管理器中显示"
            onClick={() => onReveal(artifacts[0])}
          >
            <FolderOpen className="w-4 h-4" />
          </button>
        )}
        <button
          className="p-1.5 rounded hover:bg-bg-hover text-text-secondary"
          title="刷新"
          aria-label="刷新"
          onClick={onRefresh}
        >
          <RefreshCw className={'w-4 h-4' + (loading ? ' animate-spin' : '')} />
        </button>
      </div>
      {artifacts.length > 0 && (
        <div
          className="flex items-center gap-1 px-2 py-1 border-b border-border"
          data-testid="artifact-filter-bar"
        >
          {FILTER_GROUPS.map((g) => (
            <button
              key={g.key}
              className={
                'px-1.5 py-0.5 text-ui-2xs rounded transition-colors ' +
                (filter === g.key
                  ? 'bg-primary/15 text-primary'
                  : 'text-text-secondary hover:text-text hover:bg-bg-hover')
              }
              aria-pressed={filter === g.key}
              data-testid={`artifact-filter-${g.key}`}
              onClick={() => setFilter(g.key)}
            >
              {g.label}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto">
        {artifacts.length === 0 ? (
          // R2 批次 C: 空态引导 —— 告诉用户产物从哪来（对齐主流空态文案）
          <div className="p-3 text-sm text-muted" data-testid="artifacts-empty">
            暂无产物
            <div className="mt-1 text-xs text-muted/80">
              让 agent 写文件或生成文档后，产物会自动出现在这里
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-3 text-sm text-muted" data-testid="artifacts-filter-empty">
            无该类型产物
          </div>
        ) : (
          <div className="divide-y divide-border">
            {filtered.map((a) => (
              <ArtifactRow
                key={a.id}
                artifact={a}
                onSelect={onSelect}
                onDoubleClick={handleDoubleClick}
                onOpenDelivery={handleOpenDelivery}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
