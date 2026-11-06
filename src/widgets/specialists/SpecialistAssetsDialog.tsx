/**
 * 专家资产对话框（资产中心，M3-Task 7）。
 *
 * 在一个入口内查看与管理专家的三类资产：
 * - 私有记忆：仅该专家私有层（`/memory/list?agent_id=` 精确过滤）的列表，
 *   支持手动添加（写入私有层）、删除、提升为共享；
 * - 知识绑定：绑定列表（只读）+ 跳转既有 KnowledgeBindingsEditor 管理；
 * - 技能：只读 chips（修改仍走向导）。
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { memoryApi, type AgentProfile, type Memory } from '../../shared/api';
import { specialistKnowledgeApi } from '../../shared/api/specialistKnowledgeApi';
import type { KnowledgeBinding } from '../../shared/api/types/domainEntityTypes';
import { formatDate } from '../../shared/lib/timeFormatter';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

const MEMORY_PAGE_SIZE = 20;

const KNOWLEDGE_SOURCE_LABELS: Record<string, string> = {
  wiki_project: '项目 Wiki',
  zotero_collection: 'Zotero 分类',
  project_material: '项目资料',
  workspace_fts: '工作区全文',
  specialist_private: '专家私有',
};

const MEMORY_TYPE_LABELS: Record<string, string> = {
  episodic: '情景',
  semantic: '语义',
};

type MemoryDraftType = 'episodic' | 'semantic';

interface SpecialistAssetsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent: AgentProfile | null;
  /** 打开既有知识绑定管理对话框。 */
  onManageKnowledge: (agent: AgentProfile) => void;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function SpecialistAssetsDialog({
  open,
  onOpenChange,
  agent,
  onManageKnowledge,
}: SpecialistAssetsDialogProps) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryTotal, setMemoryTotal] = useState(0);
  const [bindings, setBindings] = useState<KnowledgeBinding[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);

  const [draftContent, setDraftContent] = useState('');
  const [draftType, setDraftType] = useState<MemoryDraftType>('episodic');
  const [draftImportance, setDraftImportance] = useState(5);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const agentId = agent?.id ?? null;

  const loadAssets = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setLoadError(null);
    setKnowledgeError(null);
    try {
      const [list, knowledge] = await Promise.all([
        memoryApi.getMemories('all', 1, MEMORY_PAGE_SIZE, { agentId }),
        specialistKnowledgeApi.list(agentId).catch((err: unknown) => {
          setKnowledgeError(err instanceof Error ? err.message : String(err));
          return [] as KnowledgeBinding[];
        }),
      ]);
      setMemories(list.items);
      setMemoryTotal(list.total);
      setBindings(knowledge);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (!open) return;
    setDraftContent('');
    setDraftType('episodic');
    setDraftImportance(5);
    void loadAssets();
  }, [open, loadAssets]);

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    const content = draftContent.trim();
    if (!content || !agentId) return;
    setSaving(true);
    try {
      await memoryApi.saveMemory(
        content,
        draftType,
        draftImportance,
        ['manual'],
        undefined,
        agentId,
      );
      toast.success('已添加到专家私有记忆');
      setDraftContent('');
      await loadAssets();
    } catch (err) {
      toast.error(`添加失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(memory: Memory) {
    setBusyId(memory.id);
    try {
      await memoryApi.deleteMemory(memory.id);
      setMemories((prev) => prev.filter((m) => m.id !== memory.id));
      setMemoryTotal((total) => Math.max(0, total - 1));
      toast.success('记忆已删除');
    } catch (err) {
      toast.error(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handlePromote(memory: Memory) {
    setBusyId(memory.id);
    try {
      const result = await memoryApi.promoteMemory(memory.id);
      // 提升后归属变为共享，不再属于本专家私有列表
      setMemories((prev) => prev.filter((m) => m.id !== memory.id));
      setMemoryTotal((total) => Math.max(0, total - 1));
      toast.success(result.status === 'already_shared' ? '该记忆已在共享层' : '已提升为共享记忆');
    } catch (err) {
      toast.error(`提升失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  if (!agent) return null;

  const skillCount = agent.skills?.length ?? 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>专家资产 · {agent.name}</DialogTitle>
          <DialogDescription>
            私有记忆 {memoryTotal} 条 · 知识绑定 {bindings.length} 项 · 技能 {skillCount} 个
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 flex flex-col gap-6">
          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">私有记忆</h3>
              <span className="text-ui-xs text-faint">
                仅该专家可见；对话自动产生的记忆也归入这里
              </span>
            </div>

            {loading ? (
              <div className="rounded-lg border border-border bg-bg-subtle/40 p-4 text-center text-sm text-muted">
                加载资产…
              </div>
            ) : loadError ? (
              <div className="flex flex-col items-center gap-2 rounded-lg border border-error/30 bg-bg-subtle/40 p-4 text-center text-sm text-error">
                <span>加载失败：{loadError}</span>
                <Button size="sm" variant="secondary" onClick={() => void loadAssets()}>
                  重试
                </Button>
              </div>
            ) : memories.length === 0 ? (
              <div className="rounded-lg border border-border bg-bg-subtle/40 p-4 text-center text-sm text-muted">
                暂无私有记忆。可在下方手动添加，或与专家对话让它自动沉淀。
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {memories.map((memory) => {
                  const type = memory.memory_type ?? memory.source ?? 'episodic';
                  const ts = memory.created_at_ms ?? memory.created_at * 1000;
                  return (
                    <li
                      key={memory.id}
                      data-testid={`specialist-asset-memory-${memory.id}`}
                      className="rounded-lg border border-border bg-surface-elevated/60 p-3"
                    >
                      <p className="text-sm whitespace-pre-wrap break-words">
                        {truncate(memory.content || memory.summary || '', 240)}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-ui-xs text-muted">
                        <span className="rounded-full border border-border px-2 py-0.5">
                          {MEMORY_TYPE_LABELS[type] ?? type}
                        </span>
                        <span>重要性 {memory.importance}</span>
                        <span>{formatDate(ts)}</span>
                        <span className="ml-auto flex items-center gap-2">
                          <button
                            type="button"
                            disabled={busyId === memory.id}
                            onClick={() => void handlePromote(memory)}
                            className="rounded-radius-sm border border-border px-2 py-0.5 text-ui-xs hover:bg-bg-hover disabled:opacity-50"
                          >
                            提升为共享
                          </button>
                          <button
                            type="button"
                            disabled={busyId === memory.id}
                            onClick={() => void handleDelete(memory)}
                            className="rounded-radius-sm border border-error/40 px-2 py-0.5 text-ui-xs text-error hover:bg-error/10 disabled:opacity-50"
                          >
                            删除
                          </button>
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <form
              onSubmit={handleAdd}
              className="mt-3 flex flex-col gap-2 rounded-lg border border-border bg-bg-subtle/40 p-3"
            >
              <textarea
                data-testid="specialist-asset-memory-input"
                value={draftContent}
                onChange={(e) => setDraftContent(e.target.value)}
                rows={2}
                placeholder="手动添加一条该专家私有的事实或偏好…"
                className="w-full resize-y rounded-radius-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
              />
              <div className="flex flex-wrap items-center gap-2">
                <select
                  data-testid="specialist-asset-memory-type"
                  value={draftType}
                  onChange={(e) => setDraftType(e.target.value as MemoryDraftType)}
                  className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs"
                >
                  <option value="episodic">情景</option>
                  <option value="semantic">语义</option>
                </select>
                <label className="flex items-center gap-1 text-ui-xs text-muted">
                  重要性
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={draftImportance}
                    onChange={(e) => setDraftImportance(Number(e.target.value) || 5)}
                    className="w-14 rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs"
                  />
                </label>
                <Button
                  type="submit"
                  size="sm"
                  className="ml-auto"
                  disabled={saving || !draftContent.trim()}
                >
                  {saving ? '添加中…' : '添加记忆'}
                </Button>
              </div>
            </form>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">知识与技能</h3>
              <Button size="sm" variant="secondary" onClick={() => onManageKnowledge(agent)}>
                管理知识绑定
              </Button>
            </div>

            {knowledgeError ? (
              <div className="rounded-lg border border-error/30 bg-bg-subtle/40 p-3 text-sm text-error">
                知识绑定加载失败：{knowledgeError}
              </div>
            ) : bindings.length === 0 ? (
              <div className="rounded-lg border border-border bg-bg-subtle/40 p-3 text-sm text-muted">
                尚未绑定知识源。点「管理知识绑定」可接入项目资料、Wiki 或 Zotero 分类。
              </div>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {bindings.map((binding) => (
                  <li
                    key={binding.id}
                    data-testid={`specialist-asset-binding-${binding.id}`}
                    className="flex items-center gap-2 rounded-lg border border-border bg-surface-elevated/60 px-3 py-2 text-sm"
                  >
                    <span className="rounded-full border border-border px-2 py-0.5 text-ui-xs text-muted">
                      {KNOWLEDGE_SOURCE_LABELS[binding.source_type] ?? binding.source_type}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{binding.name}</span>
                    <span className="truncate text-ui-xs text-faint">{binding.source_id}</span>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-3">
              <p className="mb-1.5 text-ui-xs text-muted">技能</p>
              {skillCount === 0 ? (
                <p className="text-ui-xs text-faint">未配置技能（可在「编辑」向导第 3 步勾选）。</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {(agent.skills ?? []).map((skill) => (
                    <span
                      key={skill}
                      className="rounded-full border border-border px-2.5 py-1 text-ui-xs text-text-secondary"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
