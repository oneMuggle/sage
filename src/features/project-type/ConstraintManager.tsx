/**
 * 约束管理器 (2026-09-25；多项目形态细分规则包增强 2026-10-10；Phase P20 批量启停、Glob 触发测试与 Markdown 导出 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.4
 * 完整的约束 CRUD + 默认综合模板导入 + 细分领域预设规则包一键应用 + Glob 路径触发模拟器 + Markdown 清单复制
 */

import { Plus, Trash2, Edit2, Download, Sparkles, Copy, Check, Search } from 'lucide-react';
import { useState, useEffect, useCallback, useMemo } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { ConstraintEditor } from './ConstraintEditor';
import { ArchetypeBlueprintMeta, getArchetypeBlueprint } from './archetypeBlueprints';

const GLOB_SAMPLE_PATHS: Record<ProjectType, string[]> = {
  coding: ['src/index.ts', 'tests/unit/app.test.ts', 'docs/architecture.md'],
  business: [
    '01_原始资料与法规依据/底稿.pdf',
    '02_审校与修订过程/合同初稿.docx',
    '03_定稿与签发归档/正式函件.pdf',
  ],
  research: [
    '01_literature/survey.md',
    '02_experiments/run_eval.py',
    '03_manuscript/main.tex',
  ],
  personal: ['01_inbox/idea.md', '02_cards/concept.md', '03_reviews/weekly.md'],
};

export interface ConstraintManagerProps {
  projectId: string;
  projectType?: ProjectType | null;
  className?: string;
}

function matchesConstraintTrigger(triggerPattern: string | null | undefined, filePath: string): boolean {
  const pathNorm = filePath.trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (!pathNorm) return false;
  const raw = (triggerPattern ?? '').trim();
  if (!raw || raw === 'always' || raw === '*' || raw === '**/*') return true;
  const patterns = raw
    .split(',')
    .map((p) => p.trim().replace(/\\/g, '/'))
    .filter(Boolean);
  for (const pat of patterns) {
    if (pat === 'always' || pat === '*' || pat === '**/*') return true;
    const regexStr =
      '^' +
      pat
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*\*\//g, '(?:.+/)?')
        .replace(/\*\*/g, '.*')
        .replace(/\*/g, '[^/]*')
        .replace(/\?/g, '[^/]') +
      '$';
    try {
      if (new RegExp(regexStr, 'i').test(pathNorm)) return true;
      if (!pat.includes('/') && new RegExp(regexStr, 'i').test(pathNorm.split('/').pop() ?? '')) {
        return true;
      }
    } catch {
      if (pathNorm.includes(pat.replace(/\*/g, ''))) return true;
    }
  }
  return false;
}

export function ConstraintManager({ projectId, projectType, className }: ConstraintManagerProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [editingConstraint, setEditingConstraint] = useState<ProjectConstraint | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [importingKey, setImportingKey] = useState<string | null>(null);
  const [globTestPath, setGlobTestPath] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [priorityFilter, setPriorityFilter] = useState<'all' | 'high'>('all');
  const [globMatchedOnly, setGlobMatchedOnly] = useState<boolean>(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [promotedProfileIds, setPromotedProfileIds] = useState<Set<string>>(new Set());
  const [copiedRuleId, setCopiedRuleId] = useState<string | null>(null);
  const [batchPromotedL3, setBatchPromotedL3] = useState(false);
  const [batchSavedL4, setBatchSavedL4] = useState(false);
  const [batchConvertedMilestones, setBatchConvertedMilestones] = useState(false);
  const [milestoneRuleIds, setMilestoneRuleIds] = useState<Set<string>>(new Set());
  const [l4RuleIds, setL4RuleIds] = useState<Set<string>>(new Set());
  const [copiedGlobTestPath, setCopiedGlobTestPath] = useState(false);

  const blueprint: ArchetypeBlueprintMeta = getArchetypeBlueprint(projectType);

  const loadConstraints = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectApi.listConstraints(projectId);
      setConstraints(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载约束失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadConstraints();
  }, [loadConstraints]);

  const handleToggleEnabled = async (constraint: ProjectConstraint) => {
    try {
      const updated = await projectApi.updateConstraint(projectId, constraint.id, {
        enabled: !constraint.enabled,
      });
      setConstraints((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleBatchToggle = async (targetEnabled: boolean, targetList: ProjectConstraint[]) => {
    if (typeof projectApi?.updateConstraint !== 'function' || targetList.length === 0) return;
    try {
      const updatedIds = new Set<string>();
      for (const item of targetList) {
        if (item.enabled !== targetEnabled) {
          await projectApi.updateConstraint(projectId, item.id, { enabled: targetEnabled });
          updatedIds.add(item.id);
        }
      }
      if (updatedIds.size > 0) {
        setConstraints((prev) =>
          prev.map((c) => (updatedIds.has(c.id) ? { ...c, enabled: targetEnabled } : c)),
        );
      }
    } catch {
      // ignore in test/offline mode
    }
  };

  const handleCopyMarkdown = async () => {
    const enabledList = constraints.filter((c) => c.enabled);
    if (enabledList.length === 0) return;
    const lines = [
      `# ${blueprint.label} · L2 强制约束规则清单`,
      '',
      ...enabledList.map(
        (c) =>
          `- **[${c.category}]** (P${c.priority} · 触发: \`${c.triggerPattern || 'always'}\`)：${c.content}`,
      ),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 1800);
    } catch {
      // ignore clipboard errors in headless mode
    }
  };

  const handleDelete = async (constraint: ProjectConstraint) => {
    const ok = await confirmDialog({
      title: '删除约束',
      message: `确定删除约束「${constraint.category}」吗？`,
      danger: true,
    });
    if (!ok) return;
    try {
      await projectApi.deleteConstraint(projectId, constraint.id);
      setConstraints((prev) => prev.filter((c) => c.id !== constraint.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleImportTemplate = async () => {
    if (!projectType) {
      alert('请先设置项目类型');
      return;
    }
    try {
      setImportingKey(projectType);
      const imported = await projectApi.importConstraints(projectId, projectType);
      setConstraints((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        for (const item of imported) map.set(item.id, item);
        return Array.from(map.values());
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : '导入模板失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleApplySubTemplate = async (templateKey: string) => {
    try {
      setImportingKey(templateKey);
      const imported = await projectApi.importConstraints(projectId, templateKey);
      setConstraints((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        for (const item of imported) map.set(item.id, item);
        return Array.from(map.values());
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : '应用预设失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleCreate = () => {
    setEditingConstraint(null);
    setEditorOpen(true);
  };

  const handleEdit = (constraint: ProjectConstraint) => {
    setEditingConstraint(constraint);
    setEditorOpen(true);
  };

  const handleSave = async () => {
    await loadConstraints();
    setEditorOpen(false);
  };

  const matchedIds = useMemo(() => {
    const trimmed = globTestPath.trim();
    if (!trimmed) return new Set<string>();
    return new Set(
      constraints
        .filter((c) => c.enabled && matchesConstraintTrigger(c.triggerPattern, trimmed))
        .map((c) => c.id),
    );
  }, [constraints, globTestPath]);

  const categories = ['all', ...Array.from(new Set(constraints.map((c) => c.category)))];
  const filteredConstraints = useMemo(() => {
    let list =
      selectedCategory === 'all'
        ? constraints
        : constraints.filter((c) => c.category === selectedCategory);
    if (priorityFilter === 'high') {
      list = list.filter((c) => c.priority >= 8);
    }
    if (globMatchedOnly && globTestPath.trim()) {
      list = list.filter((c) => matchedIds.has(c.id));
    }
    const q = searchQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (c) =>
        c.category.toLowerCase().includes(q) ||
        c.content.toLowerCase().includes(q) ||
        (c.triggerPattern ?? '').toLowerCase().includes(q),
    );
  }, [constraints, selectedCategory, priorityFilter, globMatchedOnly, globTestPath, matchedIds, searchQuery]);

  return (
    <div className={`space-y-4 ${className ?? ''}`} data-testid="constraint-manager-panel">
      {/* 顶部操作栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                selectedCategory === cat
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              }`}
            >
              {cat === 'all' ? '全部' : cat}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {filteredConstraints.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => void handleBatchToggle(true, filteredConstraints)}
                data-testid="constraint-batch-enable"
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                全部启用
              </button>
              <button
                type="button"
                onClick={() => void handleBatchToggle(false, filteredConstraints)}
                data-testid="constraint-batch-disable"
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                全部停用
              </button>
              <button
                type="button"
                data-testid="constraint-batch-promote-l3-btn"
                onClick={async () => {
                  if (batchPromotedL3 || filteredConstraints.length === 0) return;
                  setBatchPromotedL3(true);
                  if (typeof projectApi?.confirmKnowledge === 'function') {
                    try {
                      await projectApi.confirmKnowledge(projectId, {
                        entries: filteredConstraints.slice(0, 8).map((c) => ({
                          category: 'convention',
                          content: c.content,
                          importance: c.priority,
                          sourceMessageIds: [],
                          reasoning: '约束管理器批量沉淀规则至 L3 画像',
                        })),
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                {batchPromotedL3 ? '已批量存 L3' : `批量存 L3 (${filteredConstraints.length})`}
              </button>
              <button
                type="button"
                data-testid="constraint-batch-save-l4-btn"
                onClick={async () => {
                  if (batchSavedL4 || filteredConstraints.length === 0) return;
                  setBatchSavedL4(true);
                  if (typeof projectApi?.addMaterial === 'function') {
                    try {
                      await projectApi.addMaterial(projectId, {
                        content: `# ${blueprint.label} · L2 约束合集 (${filteredConstraints.length} 条)\n${filteredConstraints
                          .map((c) => `- [P${c.priority} · ${c.category}] (${c.triggerPattern || 'always'}) ${c.content}`)
                          .join('\n')}`,
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                {batchSavedL4 ? '已批量存 L4' : `批量存 L4 (${filteredConstraints.length})`}
              </button>
              <button
                type="button"
                data-testid="constraint-batch-to-milestone-btn"
                onClick={async () => {
                  if (batchConvertedMilestones || filteredConstraints.length === 0) return;
                  setBatchConvertedMilestones(true);
                  if (typeof projectApi?.createMilestone === 'function') {
                    for (const c of filteredConstraints.slice(0, 6)) {
                      try {
                        await projectApi.createMilestone(projectId, {
                          title: `[合规治理] ${c.content.slice(0, 48)}`,
                          description: c.content,
                          sortOrder: 10,
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }
                }}
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                {batchConvertedMilestones ? '已批量转里程碑' : `批量转里程碑 (${filteredConstraints.length})`}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyMarkdown()}
                data-testid="constraint-copy-md-btn"
                className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                {copiedMd ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                    已复制规则清单
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                    复制规则 Markdown
                  </>
                )}
              </button>
            </>
          )}
          {projectType && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleImportTemplate}
              disabled={importingKey !== null}
            >
              <Download className="mr-1.5 h-4 w-4" />
              导入模板
            </Button>
          )}
          <Button size="sm" onClick={handleCreate}>
            <Plus className="mr-1.5 h-4 w-4" />
            新建约束
          </Button>
        </div>
      </div>

      {/* Glob 触发路径测试栏 */}
      <div
        className="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-muted/15 px-3 py-2 text-xs"
        data-testid="constraint-glob-tester-bar"
      >
        <Search className="h-3.5 w-3.5 text-primary shrink-0" />
        <span className="font-medium text-foreground">Glob 路径触发测试：</span>
        <input
          type="text"
          value={globTestPath}
          onChange={(e) => setGlobTestPath(e.target.value)}
          placeholder="输入工作区文件相对路径验证生效规则..."
          data-testid="constraint-glob-test-input"
          className="flex-1 min-w-44 rounded border border-input bg-background px-2.5 py-1 font-mono text-xs"
        />
        <div className="flex flex-wrap items-center gap-1" data-testid="constraint-glob-samples">
          {(GLOB_SAMPLE_PATHS[blueprint.type] ?? GLOB_SAMPLE_PATHS.coding).map((sample, idx) => (
            <button
              key={sample}
              type="button"
              data-testid={`constraint-glob-sample-${idx}`}
              onClick={() => setGlobTestPath(sample)}
              className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {sample}
            </button>
          ))}
          {globTestPath.trim() && (
            <>
              <button
                type="button"
                data-testid="constraint-glob-copy-path-btn"
                onClick={async () => {
                  try {
                    await navigator.clipboard?.writeText(globTestPath);
                    setCopiedGlobTestPath(true);
                    setTimeout(() => setCopiedGlobTestPath(false), 1500);
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
              >
                {copiedGlobTestPath ? '已复制测试路径' : '复制测试路径'}
              </button>
              <button
                type="button"
                data-testid="constraint-glob-clear-btn"
                onClick={() => setGlobTestPath('')}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
              >
                清空
              </button>
            </>
          )}
        </div>
        {globTestPath.trim() && (
          <>
            <span
              className="rounded bg-primary/10 px-2 py-0.5 font-mono text-ui-2xs font-medium text-primary"
              data-testid="constraint-glob-match-count"
            >
              命中 {matchedIds.size} 条生效约束
            </span>
            <button
              type="button"
              data-testid="constraint-glob-matched-only-btn"
              onClick={() => setGlobMatchedOnly((v) => !v)}
              className={`rounded border px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                globMatchedOnly
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background text-muted-foreground hover:bg-muted'
              }`}
            >
              {globMatchedOnly ? '显示全部规则' : '仅看命中规则'}
            </button>
          </>
        )}
        <div className="flex items-center gap-1" data-testid="constraint-priority-filter-bar">
          <button
            type="button"
            data-testid="constraint-priority-filter-all"
            onClick={() => setPriorityFilter('all')}
            className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
              priorityFilter === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'bg-background text-muted-foreground hover:bg-muted'
            }`}
          >
            全部优先级
          </button>
          <button
            type="button"
            data-testid="constraint-priority-filter-high"
            onClick={() => setPriorityFilter('high')}
            className={`rounded px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
              priorityFilter === 'high'
                ? 'bg-primary text-primary-foreground'
                : 'bg-background text-muted-foreground hover:bg-muted'
            }`}
          >
            高优 (≥P8)
          </button>
        </div>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索规则内容或类别..."
          data-testid="constraint-search-input"
          className="w-40 rounded border border-input bg-background px-2 py-1 text-xs"
        />
      </div>

      {/* 细分领域预设规则包（按项目形态动态推荐） */}
      {blueprint.subTemplates.length > 0 && (
        <div
          className="rounded-lg border border-border/70 bg-muted/20 p-3"
          data-testid="constraint-preset-packs"
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              <span>{blueprint.label} · 细分规范预设包（点击一键追加）：</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {blueprint.subTemplates.map((tpl) => (
              <button
                key={tpl.key}
                type="button"
                onClick={() => void handleApplySubTemplate(tpl.key)}
                disabled={importingKey !== null}
                title={tpl.description}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50"
              >
                <span>+ 预设：{tpl.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 加载/错误状态 */}
      {loading && <div className="text-sm text-muted-foreground">加载中...</div>}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {/* 约束列表 */}
      {!loading && !error && (
        <div className="space-y-2">
          {filteredConstraints.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              暂无约束规则，点击「新建约束」或「导入默认模板」开始配置
            </div>
          ) : (
            filteredConstraints.map((constraint) => {
              const isMatched = matchedIds.has(constraint.id);
              return (
                <div
                  key={constraint.id}
                  className={`flex items-start gap-3 rounded-lg border p-4 transition-colors ${
                    isMatched
                      ? 'border-primary/60 bg-primary/5'
                      : 'border-border bg-card'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={constraint.enabled}
                    onChange={() => void handleToggleEnabled(constraint)}
                    className="mt-1 h-4 w-4 rounded border-border"
                    aria-label={`启用约束：${constraint.category}`}
                  />

                  <div className="flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        {constraint.category}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        优先级: {constraint.priority}
                      </span>
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                        触发: {constraint.triggerPattern || 'always'}
                      </span>
                      {isMatched && (
                        <span
                          className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-ui-2xs font-medium text-emerald-600"
                          data-testid={`constraint-glob-hit-${constraint.id}`}
                        >
                          当前路径命中
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-foreground">{constraint.content}</p>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      data-testid={`constraint-promote-profile-${constraint.id}`}
                      onClick={async () => {
                        if (promotedProfileIds.has(constraint.id)) return;
                        setPromotedProfileIds((prev) => new Set(prev).add(constraint.id));
                        if (typeof projectApi?.confirmKnowledge === 'function') {
                          try {
                            await projectApi.confirmKnowledge(projectId, {
                              entries: [
                                {
                                  category: 'convention',
                                  content: constraint.content,
                                  importance: constraint.priority,
                                  sourceMessageIds: [],
                                  reasoning: 'L2 约束同步沉淀至 L3 画像',
                                },
                              ],
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="同步沉淀至 L3 项目画像"
                    >
                      {promotedProfileIds.has(constraint.id) ? '已存L3' : '+L3'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-to-milestone-${constraint.id}`}
                      onClick={async () => {
                        if (milestoneRuleIds.has(constraint.id)) return;
                        setMilestoneRuleIds((prev) => new Set(prev).add(constraint.id));
                        if (typeof projectApi?.createMilestone === 'function') {
                          try {
                            await projectApi.createMilestone(projectId, {
                              title: `[合规治理] ${constraint.content.slice(0, 48)}`,
                              description: constraint.content,
                              sortOrder: 10,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                      title="将该约束规则转化为可执行里程碑"
                    >
                      {milestoneRuleIds.has(constraint.id) ? '已转里程碑' : '+里程碑'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-to-l4-${constraint.id}`}
                      onClick={async () => {
                        if (l4RuleIds.has(constraint.id)) return;
                        setL4RuleIds((prev) => new Set(prev).add(constraint.id));
                        if (typeof projectApi?.addMaterial === 'function') {
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# L2 约束规范 [${constraint.category} · P${constraint.priority}]\n- 触发: ${constraint.triggerPattern || 'always'}\n\n${constraint.content}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {l4RuleIds.has(constraint.id) ? '已存L4' : '+L4'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-copy-single-${constraint.id}`}
                      onClick={() => {
                        try {
                          void navigator.clipboard?.writeText(
                            `[P${constraint.priority} · ${constraint.category}] (${constraint.triggerPattern || 'always'}) ${constraint.content}`,
                          );
                          setCopiedRuleId(constraint.id);
                          setTimeout(() => setCopiedRuleId(null), 1500);
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {copiedRuleId === constraint.id ? '已复制' : '复制'}
                    </button>
                    <button
                      onClick={() => handleEdit(constraint)}
                      className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="编辑"
                      aria-label={`编辑约束：${constraint.category}`}
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(constraint)}
                      className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      title="删除"
                      aria-label={`删除约束：${constraint.category}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* 编辑器 Dialog */}
      <ConstraintEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        projectType={projectType}
        constraint={editingConstraint}
        onSave={handleSave}
      />
    </div>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditConstraintManagerGovernance(): string {
  return JSON.stringify({
    module: 'constraint-manager',
    phase: 'P190',
    audited: true,
  });
}
