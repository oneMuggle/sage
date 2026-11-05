import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  specialistKnowledgeApi,
  type AgentProfile,
  type KnowledgeBinding,
  type KnowledgeSourceType,
} from '../../shared/api';
import { Button } from '../../shared/ui';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

/** source_type → 中文标签（与后端 KnowledgeSourceType 五选一对齐）。 */
export const KNOWLEDGE_SOURCE_TYPE_LABELS: Record<KnowledgeSourceType, string> = {
  wiki_project: '项目 Wiki',
  zotero_collection: 'Zotero 集合',
  project_material: '项目资料',
  workspace_fts: '工作区全文',
  specialist_private: '专家私有目录',
};

const SOURCE_TYPE_ORDER: KnowledgeSourceType[] = [
  'specialist_private',
  'wiki_project',
  'project_material',
  'zotero_collection',
  'workspace_fts',
];

const SOURCE_ID_PLACEHOLDERS: Record<KnowledgeSourceType, string> = {
  wiki_project: '项目 ID，如 proj_123',
  zotero_collection: '集合 key，如 ABCD1234',
  project_material: '项目 ID，如 proj_123',
  workspace_fts: '工作区路径',
  specialist_private: '留空表示当前专家的私有目录',
};

interface KnowledgeBindingsEditorProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  /** 正在编辑知识的专家（null = 对话框关闭态）。 */
  agent: AgentProfile | null;
  /** 增删成功后回调（父级可刷新专家卡片，version 已 +1）。 */
  onChanged?: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * M2-Task 2 专家「知识」Tab 编辑器：列出/新增/删除知识绑定。
 *
 * 后端契约见 `specialistKnowledgeApi`；本组件不做检索，只管理绑定列表。
 * 绑定变更会自动把专家 version +1（后端行为），父级通过 `onChanged` 刷新。
 */
export function KnowledgeBindingsEditor({
  open,
  onOpenChange,
  agent,
  onChanged,
}: KnowledgeBindingsEditorProps) {
  const agentId = agent?.id ?? '';
  const [bindings, setBindings] = useState<KnowledgeBinding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>('specialist_private');
  const [sourceId, setSourceId] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadBindings = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError(null);
    try {
      setBindings(await specialistKnowledgeApi.list(agentId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (!open || !agentId) return;
    setSourceType('specialist_private');
    setSourceId('');
    setName('');
    void loadBindings();
  }, [open, agentId, loadBindings]);

  async function handleCreate() {
    if (!agentId) return;
    const trimmedName = name.trim();
    const trimmedSourceId = sourceId.trim();
    const effectiveSourceId =
      trimmedSourceId || (sourceType === 'specialist_private' ? agentId : '');
    if (!trimmedName) {
      toast.error('请填写展示名称');
      return;
    }
    if (!effectiveSourceId) {
      toast.error('请填写源标识');
      return;
    }
    setSubmitting(true);
    try {
      const created = await specialistKnowledgeApi.create(agentId, {
        source_type: sourceType,
        source_id: effectiveSourceId,
        name: trimmedName,
      });
      setBindings((prev) => [...prev, created].sort((a, b) => a.created_at - b.created_at));
      setSourceId('');
      setName('');
      toast.success(`已绑定「${created.name}」`);
      onChanged?.();
    } catch (err) {
      toast.error(`绑定失败：${errorMessage(err)}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(binding: KnowledgeBinding) {
    if (!agentId) return;
    setDeletingId(binding.id);
    try {
      await specialistKnowledgeApi.remove(agentId, binding.id);
      setBindings((prev) => prev.filter((b) => b.id !== binding.id));
      toast.success(`已解绑「${binding.name}」`);
      onChanged?.();
    } catch (err) {
      toast.error(`解绑失败：${errorMessage(err)}`);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>知识绑定</DialogTitle>
          <DialogDescription>
            {agent ? `为「${agent.name}」绑定可检索的知识源；` : ''}
            检索结果会以引用形式出现在聊天消息中。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {error && (
            <div
              role="alert"
              className="flex items-center justify-between rounded-lg bg-error/10 p-3 text-sm text-error"
            >
              <span>{error}</span>
              <Button variant="ghost" size="sm" onClick={() => void loadBindings()}>
                重试
              </Button>
            </div>
          )}

          {loading ? (
            <p className="text-sm text-muted">加载知识绑定…</p>
          ) : bindings.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted">
              尚未绑定任何知识源。
            </p>
          ) : (
            <ul className="flex flex-col gap-2" aria-label="知识绑定列表">
              {bindings.map((binding) => (
                <li
                  key={binding.id}
                  data-testid={`knowledge-binding-${binding.id}`}
                  className="flex items-center gap-3 rounded-lg border border-border p-3"
                >
                  <span className="shrink-0 rounded-full bg-bg-subtle px-2 py-0.5 text-ui-xs text-text-secondary">
                    {KNOWLEDGE_SOURCE_TYPE_LABELS[binding.source_type] ?? binding.source_type}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{binding.name}</p>
                    <p className="truncate font-mono text-ui-xs text-faint">{binding.source_id}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDelete(binding)}
                    disabled={deletingId === binding.id}
                    aria-label={`解绑 ${binding.name}`}
                  >
                    {deletingId === binding.id ? '解绑中…' : '解绑'}
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <div className="rounded-lg border border-border bg-bg-subtle/40 p-3">
            <p className="mb-2 text-sm font-medium">新增绑定</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-ui-xs text-muted">
                知识源类型
                <select
                  aria-label="知识源类型"
                  value={sourceType}
                  onChange={(e) => setSourceType(e.target.value as KnowledgeSourceType)}
                  className="rounded-radius-md border border-border bg-surface px-2 py-1.5 text-sm text-text"
                >
                  {SOURCE_TYPE_ORDER.map((type) => (
                    <option key={type} value={type}>
                      {KNOWLEDGE_SOURCE_TYPE_LABELS[type]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-ui-xs text-muted">
                源标识
                <input
                  type="text"
                  aria-label="源标识"
                  value={sourceId}
                  onChange={(e) => setSourceId(e.target.value)}
                  placeholder={SOURCE_ID_PLACEHOLDERS[sourceType]}
                  className="rounded-radius-md border border-border bg-surface px-2 py-1.5 text-sm text-text"
                />
              </label>
              <label className="flex flex-col gap-1 text-ui-xs text-muted">
                展示名称
                <input
                  type="text"
                  aria-label="展示名称"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：团队论文库"
                  className="rounded-radius-md border border-border bg-surface px-2 py-1.5 text-sm text-text"
                />
              </label>
            </div>
            <div className="mt-2 flex justify-end">
              <Button size="sm" onClick={() => void handleCreate()} disabled={submitting}>
                {submitting ? '绑定中…' : '绑定'}
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
