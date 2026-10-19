/**
 * AI 对话知识提取面板 (M2, 2026-10-12；Phase P21 会话联动；Phase P24 跨项目状态重置与全选/清空切换；Phase P29 会话手动刷新与提取建议一键复制 Markdown)
 *
 * 嵌入项目画像 Profile Tab 顶部，支持从项目已绑定会话列表一键选择、手动刷新会话或手动输入会话 ID，
 * 提取知识建议并支持一键复制提取结果 Markdown、全选/清空与勾选确认后写入 ProjectProfileStore。
 */

import { Sparkles, Loader2, CheckCircle2, Lightbulb, RefreshCw, Copy, Check, ShieldPlus } from 'lucide-react';
import { useState, useCallback, useEffect } from 'react';

import { projectApi, type KnowledgeEntryProposal, type Session } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface KnowledgeExtractionPanelProps {
  projectId: string;
  /** 提取并确认后回调（外部重新拉取画像列表） */
  onConfirmed?: () => void;
}

type Phase = 'idle' | 'loading' | 'review' | 'confirming';

const CATEGORY_LABELS: Record<string, string> = {
  convention: '约定',
  architecture: '架构',
  decision: '决策',
  goal: '目标',
  note: '备注',
};

export function KnowledgeExtractionPanel({
  projectId,
  onConfirmed,
}: KnowledgeExtractionPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [entries, setEntries] = useState<KnowledgeEntryProposal[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [reasoning, setReasoning] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState('');
  const [boundSessions, setBoundSessions] = useState<Session[]>([]);
  const [copiedMd, setCopiedMd] = useState(false);
  const [convertedConstraintIndices, setConvertedConstraintIndices] = useState<Set<number>>(new Set());
  const [convertedMilestoneIndices, setConvertedMilestoneIndices] = useState<Set<number>>(new Set());
  const [convertedL4Indices, setConvertedL4Indices] = useState<Set<number>>(new Set());
  const [savedReasoningL4, setSavedReasoningL4] = useState(false);
  const [savedReasoningL3, setSavedReasoningL3] = useState(false);
  const [copiedEntryIdx, setCopiedEntryIdx] = useState<number | null>(null);
  const [copiedSelectedMd, setCopiedSelectedMd] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('all');

  const resetPanel = useCallback(() => {
    setPhase('idle');
    setEntries([]);
    setSelected(new Set());
    setConvertedConstraintIndices(new Set());
    setCategoryFilter('all');
    setReasoning('');
    setError(null);
  }, []);

  const loadBoundSessions = useCallback(async () => {
    if (!projectId || typeof projectApi?.listSessions !== 'function') {
      setBoundSessions([]);
      return;
    }
    try {
      const list = await projectApi.listSessions(projectId);
      if (!Array.isArray(list)) return;
      setBoundSessions(list);
      setSessionId((prev) => prev || (list[0]?.id ?? ''));
    } catch {
      setBoundSessions([]);
    }
  }, [projectId]);

  useEffect(() => {
    resetPanel();
    setSessionId('');
    if (!projectId || typeof projectApi?.listSessions !== 'function') {
      setBoundSessions([]);
      return;
    }
    let active = true;
    Promise.resolve(projectApi.listSessions(projectId))
      .then((list) => {
        if (!active || !Array.isArray(list)) return;
        setBoundSessions(list);
        setSessionId(list[0]?.id ?? '');
      })
      .catch(() => {
        if (active) setBoundSessions([]);
      });
    return () => {
      active = false;
    };
  }, [projectId, resetPanel]);

  const handleExtract = useCallback(async () => {
    if (!sessionId.trim()) {
      setError('请输入会话 ID');
      return;
    }
    if (typeof projectApi?.extractKnowledge !== 'function') return;
    setError(null);
    setPhase('loading');
    try {
      const result = await projectApi.extractKnowledge(projectId, {
        sessionId: sessionId.trim(),
      });
      setEntries(result.entries);
      setReasoning(result.reasoning);
      setSelected(new Set(result.entries.map((_, i) => i)));
      setPhase('review');
    } catch (err) {
      setError(err instanceof Error ? err.message : '知识提取失败');
      setPhase('idle');
    }
  }, [projectId, sessionId]);

  const handleConfirm = useCallback(async () => {
    if (selected.size === 0 || typeof projectApi?.confirmKnowledge !== 'function') return;
    setError(null);
    setPhase('confirming');
    try {
      const selectedEntries = [...selected].sort((a, b) => a - b).map((i) => entries[i]);
      await projectApi.confirmKnowledge(projectId, {
        entries: selectedEntries,
      });
      onConfirmed?.();
      resetPanel();
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败');
      setPhase('review');
    }
  }, [projectId, entries, selected, onConfirmed, resetPanel]);

  const handleCopyProposalsMarkdown = async () => {
    if (entries.length === 0) return;
    const lines = [
      `# M2 对话知识提取建议 (会话 ${sessionId})`,
      reasoning ? `> 提取思路：${reasoning}` : '',
      '',
      ...entries.map(
        (entry, idx) =>
          `${idx + 1}. **[${CATEGORY_LABELS[entry.category] ?? entry.category} · 重要性 ${entry.importance}/10]** ${entry.content}${
            entry.reasoning ? ` _(${entry.reasoning})_` : ''
          }`,
      ),
    ].filter(Boolean);
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  const toggleEntry = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  const handleToggleSelectAll = () => {
    if (selected.size === entries.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(entries.map((_, i) => i)));
    }
  };

  const handleSelectHighImportance = () => {
    const highIndices = entries
      .map((e, i) => (e.importance >= 8 ? i : -1))
      .filter((i) => i >= 0);
    setSelected(new Set(highIndices));
  };

  const handleConvertToConstraint = async (entry: KnowledgeEntryProposal, idx: number) => {
    if (convertedConstraintIndices.has(idx) || typeof projectApi?.createConstraint !== 'function') {
      return;
    }
    try {
      await projectApi.createConstraint(projectId, {
        category: entry.category || 'convention',
        content: entry.content,
        priority: Math.min(10, Math.max(1, entry.importance || 7)),
      });
      setConvertedConstraintIndices((prev) => new Set(prev).add(idx));
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <div className="space-y-3" data-testid="knowledge-extraction-panel">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {/* 输入阶段 */}
      {(phase === 'idle' || phase === 'loading') && (
        <div className="flex flex-wrap gap-2 items-center">
          <Lightbulb className="h-3.5 w-3.5 text-primary shrink-0" />
          {boundSessions.length > 0 && (
            <select
              value={boundSessions.some((s) => s.id === sessionId) ? sessionId : ''}
              onChange={(e) => {
                if (e.target.value) setSessionId(e.target.value);
              }}
              disabled={phase === 'loading'}
              aria-label="选择项目绑定会话"
              data-testid="knowledge-session-select"
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground"
            >
              <option value="">选择项目会话 ({boundSessions.length})...</option>
              {boundSessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title || s.id}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={() => void loadBoundSessions()}
            disabled={phase === 'loading'}
            data-testid="knowledge-refresh-sessions-btn"
            aria-label="刷新项目会话列表"
            title="刷新项目会话列表"
            className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
          <input
            type="text"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            placeholder="输入要分析的会话 ID..."
            disabled={phase === 'loading'}
            data-testid="knowledge-session-id-input"
            className="flex-1 min-w-[200px] rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void handleExtract()}
            disabled={!sessionId.trim() || phase === 'loading'}
            data-testid="knowledge-extract-btn"
          >
            {phase === 'loading' ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                分析中...
              </>
            ) : (
              <>
                <Sparkles className="mr-1 h-3 w-3 text-primary" />
                AI 提取知识
              </>
            )}
          </Button>
        </div>
      )}

      {/* 审核阶段 */}
      {(phase === 'review' || phase === 'confirming') && (
        <div className="space-y-2">
          {reasoning && (
            <div className="flex items-start justify-between gap-2 rounded-lg border bg-muted/50 p-2 text-xs text-muted-foreground">
              <div>
                <span className="font-medium text-foreground">提取思路：</span> {reasoning}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  data-testid="knowledge-save-reasoning-l3-btn"
                  onClick={async () => {
                    if (savedReasoningL3) return;
                    setSavedReasoningL3(true);
                    if (typeof projectApi?.confirmKnowledge === 'function') {
                      try {
                        await projectApi.confirmKnowledge(projectId, {
                          entries: [
                            {
                              category: 'note',
                              content: `[M2 对话知识提取思路 (${sessionId})] ${reasoning}`,
                              importance: 6,
                              sourceMessageIds: [],
                              reasoning: 'M2 对话知识提取思路沉淀至 L3 画像',
                            },
                          ],
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  {savedReasoningL3 ? '已存 L3' : '思路存为 L3'}
                </button>
                <button
                  type="button"
                  data-testid="knowledge-save-reasoning-l4-btn"
                  onClick={async () => {
                    if (savedReasoningL4) return;
                    setSavedReasoningL4(true);
                    if (typeof projectApi?.addMaterial === 'function') {
                      try {
                        await projectApi.addMaterial(projectId, {
                          content: `[M2 对话知识提取摘要] ${reasoning}\n${entries.map((e) => `- [${e.category}] ${e.content}`).join('\n')}`,
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  {savedReasoningL4 ? '已存 L4 资料' : '思路存为 L4 资料'}
                </button>
              </div>
            </div>
          )}
          {entries.length === 0 ? (
            <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
              本次分析未发现值得提取的知识
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                <span>发现 {entries.length} 条建议，勾选要添加的：</span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void handleCopyProposalsMarkdown()}
                    data-testid="knowledge-copy-md-btn"
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {copiedMd ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-500" />
                        已复制
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3 text-primary" />
                        复制提取结果 MD
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    data-testid="knowledge-copy-selected-md-btn"
                    onClick={async () => {
                      const picked = Array.from(selected)
                        .map((idx) => entries[idx])
                        .filter(Boolean);
                      const md = [
                        `# 已选中 M2 提炼知识建议 (${picked.length} 条)`,
                        ...picked.map(
                          (e) =>
                            `- **[${CATEGORY_LABELS[e.category] ?? e.category}]** (重要度 ${e.importance}/10) ${e.content}`,
                        ),
                      ].join('\n');
                      try {
                        await navigator.clipboard?.writeText(md);
                        setCopiedSelectedMd(true);
                        setTimeout(() => setCopiedSelectedMd(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {copiedSelectedMd ? '已复制选中项' : '复制仅选中项 MD'}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      const targetIndices = Array.from(selected).filter(
                        (idx) => !convertedConstraintIndices.has(idx) && entries[idx],
                      );
                      if (targetIndices.length === 0) return;
                      setConvertedConstraintIndices((prev) => {
                        const next = new Set(prev);
                        targetIndices.forEach((idx) => next.add(idx));
                        return next;
                      });
                      if (typeof projectApi?.createConstraint === 'function') {
                        for (const idx of targetIndices) {
                          const entry = entries[idx];
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: entry.category || 'convention',
                              content: entry.content,
                              priority: Math.min(10, Math.max(1, entry.importance || 7)),
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    data-testid="knowledge-batch-to-constraint-btn"
                    className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                  >
                    <ShieldPlus className="h-3 w-3" />
                    选中项同步转 L2 约束
                  </button>
                  <button
                    type="button"
                    data-testid="knowledge-batch-to-milestone-btn"
                    onClick={async () => {
                      const targetIndices = Array.from(selected).filter(
                        (idx) => !convertedMilestoneIndices.has(idx) && entries[idx],
                      );
                      if (targetIndices.length === 0) return;
                      setConvertedMilestoneIndices((prev) => {
                        const next = new Set(prev);
                        targetIndices.forEach((idx) => next.add(idx));
                        return next;
                      });
                      if (typeof projectApi?.createMilestone === 'function') {
                        for (const idx of targetIndices) {
                          const entry = entries[idx];
                          try {
                            await projectApi.createMilestone(projectId, {
                              title: entry.content.slice(0, 80),
                              description: entry.reasoning || '从 M2 对话知识提取批量转化',
                              status: 'pending',
                              sortOrder: idx + 1,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    选中项转里程碑
                  </button>
                  <button
                    type="button"
                    data-testid="knowledge-batch-to-l4-btn"
                    onClick={async () => {
                      const targetIndices = Array.from(selected).filter(
                        (idx) => !convertedL4Indices.has(idx) && entries[idx],
                      );
                      if (targetIndices.length === 0) return;
                      setConvertedL4Indices((prev) => {
                        const next = new Set(prev);
                        targetIndices.forEach((idx) => next.add(idx));
                        return next;
                      });
                      if (typeof projectApi?.addMaterial === 'function') {
                        for (const idx of targetIndices) {
                          const entry = entries[idx];
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# M2 提炼知识归档 [${CATEGORY_LABELS[entry.category] ?? entry.category}]\n\n${entry.content}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    选中项转 L4 资料
                  </button>
                  <button
                    type="button"
                    onClick={handleSelectHighImportance}
                    data-testid="knowledge-select-high-btn"
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    仅选高重要度 (≥8)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSelected((prev) => new Set(entries.map((_, i) => i).filter((i) => !prev.has(i))));
                    }}
                    data-testid="knowledge-select-invert-btn"
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    反选建议
                  </button>
                  <button
                    type="button"
                    onClick={handleToggleSelectAll}
                    data-testid="knowledge-toggle-select-all"
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {selected.size === entries.length ? '清空选择' : '全选建议'}
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1" data-testid="knowledge-category-filter-bar">
                <button
                  type="button"
                  data-testid="knowledge-category-filter-all"
                  onClick={() => setCategoryFilter('all')}
                  className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                    categoryFilter === 'all'
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-muted'
                  }`}
                >
                  全部类别 ({entries.length})
                </button>
                {Array.from(new Set(entries.map((e) => e.category))).map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    data-testid={`knowledge-category-filter-${cat}`}
                    onClick={() => setCategoryFilter(cat)}
                    className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                      categoryFilter === cat
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {CATEGORY_LABELS[cat] ?? cat}
                  </button>
                ))}
                <button
                  type="button"
                  data-testid="knowledge-select-filtered-btn"
                  onClick={() => {
                    const matched = entries
                      .map((e, i) => (categoryFilter === 'all' || e.category === categoryFilter ? i : -1))
                      .filter((i) => i >= 0);
                    setSelected(new Set(matched));
                  }}
                  className="ml-auto rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                >
                  按筛选类别全选
                </button>
              </div>
              {entries.map((entry, idx) =>
                categoryFilter !== 'all' && entry.category !== categoryFilter ? null : (
                <label
                  key={idx}
                  className="flex items-start gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs cursor-pointer hover:bg-muted/30"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(idx)}
                    onChange={() => toggleEntry(idx)}
                    data-testid={`knowledge-entry-checkbox-${idx}`}
                    className="mt-0.5 shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1.5">
                      <div className="flex items-center gap-1.5">
                        <Badge variant="outline" className="text-ui-2xs shrink-0">
                          {CATEGORY_LABELS[entry.category] ?? entry.category}
                        </Badge>
                        <span className="text-ui-2xs text-muted-foreground">
                          重要性 {entry.importance}/10
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          data-testid={`knowledge-copy-entry-${idx}`}
                          onClick={(ev) => {
                            ev.preventDefault();
                            ev.stopPropagation();
                            try {
                              void navigator.clipboard?.writeText(
                                `[${CATEGORY_LABELS[entry.category] ?? entry.category}] ${entry.content}`,
                              );
                              setCopiedEntryIdx(idx);
                            } catch {
                              // ignore in test/offline mode
                            }
                          }}
                          className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {copiedEntryIdx === idx ? '已复制' : '复制'}
                        </button>
                        <button
                          type="button"
                          data-testid={`knowledge-to-milestone-${idx}`}
                          onClick={(ev) => {
                            ev.preventDefault();
                            ev.stopPropagation();
                            if (convertedMilestoneIndices.has(idx)) return;
                            setConvertedMilestoneIndices((prev) => new Set(prev).add(idx));
                            if (typeof projectApi?.createMilestone === 'function') {
                              void Promise.resolve(
                                projectApi.createMilestone(projectId, {
                                  title: entry.content.slice(0, 80),
                                  description: entry.reasoning || '从 M2 对话知识提取转化',
                                  status: 'pending',
                                  sortOrder: idx + 1,
                                }),
                              ).catch(() => {});
                            }
                          }}
                          className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {convertedMilestoneIndices.has(idx) ? '已转里程碑' : '转里程碑'}
                        </button>
                        <button
                          type="button"
                          data-testid={`knowledge-to-l4-${idx}`}
                          onClick={(ev) => {
                            ev.preventDefault();
                            ev.stopPropagation();
                            if (convertedL4Indices.has(idx)) return;
                            setConvertedL4Indices((prev) => new Set(prev).add(idx));
                            if (typeof projectApi?.addMaterial === 'function') {
                              void Promise.resolve(
                                projectApi.addMaterial(projectId, {
                                  content: `# M2 提炼知识归档 [${CATEGORY_LABELS[entry.category] ?? entry.category}]\n\n${entry.content}`,
                                }),
                              ).catch(() => {});
                            }
                          }}
                          className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {convertedL4Indices.has(idx) ? '已存L4' : '+L4'}
                        </button>
                        <button
                          type="button"
                          data-testid={`knowledge-to-constraint-${idx}`}
                        onClick={(ev) => {
                          ev.preventDefault();
                          ev.stopPropagation();
                          void handleConvertToConstraint(entry, idx);
                        }}
                        className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        title="将此知识条目同步固化为 L2 项目约束"
                      >
                        <ShieldPlus className="h-3 w-3 text-primary" />
                        {convertedConstraintIndices.has(idx) ? '已转 L2 约束' : '转 L2 约束'}
                        </button>
                      </div>
                    </div>
                    <p className="mt-0.5 text-foreground">{entry.content}</p>
                    {entry.reasoning && (
                      <p className="mt-0.5 text-muted-foreground text-ui-2xs">{entry.reasoning}</p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={resetPanel}>
              取消
            </Button>
            <Button
              size="sm"
              onClick={() => void handleConfirm()}
              disabled={selected.size === 0 || phase === 'confirming'}
              data-testid="knowledge-confirm-btn"
            >
              {phase === 'confirming' ? (
                <>
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  写入中...
                </>
              ) : (
                <>
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  确认添加 ({selected.size})
                </>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
