/**
 * 约束摘要 Widget (2026-09-25; Phase P15 空状态一键导入与 Glob 触发统计; Phase P25 中文类别映射与手动刷新; Phase P30 高优规则预览与 Markdown 导出)
 *
 * 项目类型分类系统 - Phase 4.3
 * 显示项目的约束统计信息（启用数量、Glob 触发数量、中文类别分组、高优规则预览、复制规则 MD、手动刷新及空状态快速导入）
 */

import { Shield, CheckCircle2, Sparkles, RefreshCw, Copy, Check } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';

const CONSTRAINT_CATEGORY_LABELS: Record<string, string> = {
  code_style: '代码风格与规范',
  git_convention: 'Git 提交与分支规范',
  architecture: '架构分层与边界',
  testing: '测试与质量门禁',
  security: '安全与脱敏红线',
  document_format: '公文与合同版式规范',
  legal_compliance: '法务与合规审查',
  financial_audit: '金额与台账双轨校核',
  archive_standard: '四级立卷归档标准',
  academic_writing: '学术写作与语体规范',
  citation_rule: '零幻觉文献引用铁律',
  reproducibility: '实验可复现性规范',
  ethics_review: '科研伦理与数据合规',
  note_structure: '卡片盒笔记结构规范',
  privacy_guard: '个人隐私与本地隔离',
  risk_guard: 'AI 顾问风险防护规则',
};

export interface ConstraintSummaryWidgetProps {
  projectId: string;
  projectType: ProjectType | null | undefined;
}

export function ConstraintSummaryWidget({ projectId, projectType }: ConstraintSummaryWidgetProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedRules, setCopiedRules] = useState(false);
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [savedSummaryL3, setSavedSummaryL3] = useState(false);
  const [savedSummaryL4, setSavedSummaryL4] = useState(false);
  const [convertedTopMilestones, setConvertedTopMilestones] = useState(false);
  const [promotedRuleL3Ids, setPromotedRuleL3Ids] = useState<Set<string>>(new Set());
  const [promotedRuleMilestoneIds, setPromotedRuleMilestoneIds] = useState<Set<string>>(new Set());
  const [promotedRuleL4Ids, setPromotedRuleL4Ids] = useState<Set<string>>(new Set());
  const [copiedRuleId, setCopiedRuleId] = useState<string | null>(null);
  const [copiedCategories, setCopiedCategories] = useState(false);
  const [convertedDisabledMilestone, setConvertedDisabledMilestone] = useState(false);
  const [savedGlobL3, setSavedGlobL3] = useState(false);
  const [copiedGlobRules, setCopiedGlobRules] = useState(false);

  const fetchConstraints = useCallback(async () => {
    if (typeof projectApi?.listConstraints !== 'function') {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const list = await projectApi.listConstraints(projectId);
      setConstraints(Array.isArray(list) ? list : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取约束失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void fetchConstraints();
  }, [fetchConstraints]);

  const handleQuickImport = async () => {
    if (!projectType || importing || typeof projectApi?.importConstraints !== 'function') return;
    setImporting(true);
    try {
      await projectApi.importConstraints(projectId, projectType);
      await fetchConstraints();
    } catch {
      // ignore in test/offline mode
    } finally {
      setImporting(false);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            约束统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">加载中...</div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            约束统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-red-500">{error}</div>
        </CardContent>
      </Card>
    );
  }

  const enabledConstraints = constraints.filter((c) => c.enabled);
  const globCount = enabledConstraints.filter((c) => Boolean(c.triggerPattern?.trim())).length;
  const highPriorityCount = enabledConstraints.filter((c) => c.priority >= 8).length;
  const categoryCount = new Map<string, number>();
  enabledConstraints.forEach((c) => {
    categoryCount.set(c.category, (categoryCount.get(c.category) || 0) + 1);
  });
  const disabledConstraints = constraints.filter((c) => !c.enabled);
  const topRules = [...enabledConstraints]
    .filter((c) => !selectedCategory || c.category === selectedCategory)
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 3);

  const handleCopyActiveRules = async () => {
    if (enabledConstraints.length === 0) return;
    const lines = [
      `# 项目生效约束规则清单 (${enabledConstraints.length} 条)`,
      '',
      ...enabledConstraints
        .sort((a, b) => b.priority - a.priority)
        .map(
          (c) =>
            `- **[P${c.priority} · ${CONSTRAINT_CATEGORY_LABELS[c.category] ?? c.category}]** \`${c.triggerPattern || 'always'}\`：${c.content}`,
        ),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedRules(true);
      setTimeout(() => setCopiedRules(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  return (
    <Card data-testid="constraint-summary-widget">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Shield className="h-4 w-4" />
            约束统计
          </CardTitle>
          <div className="flex items-center gap-1">
            {enabledConstraints.length > 0 && (
              <>
              <button
                type="button"
                data-testid="constraint-summary-save-l3-btn"
                onClick={async () => {
                  if (savedSummaryL3) return;
                  setSavedSummaryL3(true);
                  if (typeof projectApi?.confirmKnowledge === 'function') {
                    try {
                      await projectApi.confirmKnowledge(projectId, {
                        entries: enabledConstraints
                          .slice(0, 5)
                          .map((c) => ({
                            category: 'convention',
                            content: c.content,
                            importance: c.priority,
                            sourceMessageIds: [],
                            reasoning: '约束统计摘要高优规则沉淀至 L3 画像',
                          })),
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {savedSummaryL3 ? '已存高优 L3' : '沉淀高优至 L3'}
              </button>
              <button
                type="button"
                data-testid="constraint-summary-save-l4-btn"
                onClick={async () => {
                  if (savedSummaryL4) return;
                  setSavedSummaryL4(true);
                  if (typeof projectApi?.addMaterial === 'function') {
                    try {
                      await projectApi.addMaterial(projectId, {
                        content: `# L2 生效约束规则快照 (${enabledConstraints.length} 条)\n${enabledConstraints.map((c) => `- [P${c.priority} · ${c.category}] ${c.content}`).join('\n')}`,
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {savedSummaryL4 ? '已存 L4' : '存 L4'}
              </button>
              <button
                type="button"
                data-testid="constraint-summary-top-to-milestone-btn"
                onClick={async () => {
                  if (convertedTopMilestones) return;
                  setConvertedTopMilestones(true);
                  if (typeof projectApi?.createMilestone === 'function') {
                    for (const rule of topRules) {
                      try {
                        await projectApi.createMilestone(projectId, {
                          title: `[高优约束验收] ${rule.content.slice(0, 60)}`,
                          description: `来自 L2 高优规则 P${rule.priority} (${rule.category})`,
                          status: 'pending',
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {convertedTopMilestones ? '已转里程碑' : '高优转里程碑'}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyActiveRules()}
                data-testid="constraint-summary-copy-md-btn"
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                title="复制生效约束规则 Markdown"
              >
                {copiedRules ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-500" />
                    已复制
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    复制规则
                  </>
                )}
              </button>
              </>
            )}
            <button
              type="button"
              onClick={() => void fetchConstraints()}
              data-testid="constraint-summary-refresh-btn"
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              title="刷新约束统计"
              aria-label="刷新约束统计"
            >
              <RefreshCw className="h-3 w-3" />
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            <span className="text-muted-foreground">启用约束：</span>
            <span className="font-medium">
              {enabledConstraints.length} / {constraints.length}
            </span>
            {disabledConstraints.length > 0 && (
              <button
                type="button"
                data-testid="constraint-summary-enable-all-btn"
                onClick={async () => {
                  if (typeof projectApi?.updateConstraint !== 'function') return;
                  try {
                    for (const c of disabledConstraints) {
                      await projectApi.updateConstraint(projectId, c.id, { enabled: true });
                    }
                    await fetchConstraints();
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
              >
                启用全部 ({disabledConstraints.length})
              </button>
            )}
            {disabledConstraints.length > 0 && (
              <button
                type="button"
                data-testid="constraint-summary-disabled-to-milestone-btn"
                onClick={async () => {
                  if (convertedDisabledMilestone) return;
                  setConvertedDisabledMilestone(true);
                  if (typeof projectApi?.createMilestone === 'function') {
                    try {
                      await projectApi.createMilestone(projectId, {
                        title: `[待审约束复核] 复核 ${disabledConstraints.length} 条停用规则`,
                        description: disabledConstraints.map((c) => c.content).join('；'),
                        status: 'pending',
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {convertedDisabledMilestone ? '已建复核里程碑' : '停用转里程碑'}
              </button>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {highPriorityCount > 0 && (
              <span
                className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-ui-2xs font-medium text-amber-600"
                data-testid="constraint-summary-high-priority-count"
              >
                高优 ≥P8：{highPriorityCount} 条
              </span>
            )}
            {globCount > 0 && (
              <>
                <span
                  className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-ui-2xs text-primary"
                  data-testid="constraint-summary-glob-count"
                >
                  Glob 按需触发：{globCount} 条
                </span>
                <button
                  type="button"
                  data-testid="constraint-summary-glob-to-l3-btn"
                  onClick={async () => {
                    if (savedGlobL3) return;
                    setSavedGlobL3(true);
                    const globRules = enabledConstraints.filter((c) =>
                      Boolean(c.triggerPattern?.trim()),
                    );
                    if (typeof projectApi?.confirmKnowledge === 'function') {
                      try {
                        await projectApi.confirmKnowledge(projectId, {
                          entries: globRules.map((gc) => ({
                            category: 'convention' as const,
                            content: `[Glob: ${gc.triggerPattern}] ${gc.content}`,
                            importance: gc.priority,
                            sourceMessageIds: [],
                            reasoning: 'Glob 按需触发约束规则沉淀至 L3 画像',
                          })),
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {savedGlobL3 ? '已存Glob至L3' : 'Glob规则存L3'}
                </button>
                <button
                  type="button"
                  data-testid="constraint-summary-copy-glob-btn"
                  onClick={async () => {
                    const globRules = enabledConstraints.filter((c) =>
                      Boolean(c.triggerPattern?.trim()),
                    );
                    const md = globRules
                      .map((gc) => `- \`${gc.triggerPattern}\` (P${gc.priority}): ${gc.content}`)
                      .join('\n');
                    try {
                      await navigator.clipboard?.writeText(md);
                      setCopiedGlobRules(true);
                      setTimeout(() => setCopiedGlobRules(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedGlobRules ? '已复制Glob' : '复制Glob规则'}
                </button>
              </>
            )}
          </div>
        </div>

        {categoryCount.size > 0 && (
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <div className="text-xs text-muted-foreground">按类别</div>
                <button
                  type="button"
                  data-testid="constraint-summary-copy-cats-btn"
                  onClick={async () => {
                    const md = [
                      '# L2 约束类别分布',
                      ...Array.from(categoryCount.entries()).map(
                        ([cat, cnt]) => `- **${CONSTRAINT_CATEGORY_LABELS[cat] ?? cat} (${cat})**: ${cnt} 条`,
                      ),
                    ].join('\n');
                    try {
                      await navigator.clipboard?.writeText(md);
                      setCopiedCategories(true);
                      setTimeout(() => setCopiedCategories(false), 1500);
                    } catch {
                      // ignore in test/offline mode
                    }
                  }}
                  className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {copiedCategories ? '已复制分布' : '复制分布'}
                </button>
              </div>
              {selectedCategory && (
                <button
                  type="button"
                  data-testid="constraint-summary-clear-cat"
                  onClick={() => setSelectedCategory(null)}
                  className="text-ui-2xs text-primary hover:underline"
                >
                  清除类别过滤
                </button>
              )}
            </div>
            <div className="space-y-1">
              {Array.from(categoryCount.entries())
                .sort((a, b) => b[1] - a[1])
                .slice(0, 5)
                .map(([category, count]) => (
                  <button
                    key={category}
                    type="button"
                    data-testid={`constraint-summary-cat-pill-${category}`}
                    onClick={() => {
                      setSelectedCategory((prev) => (prev === category ? null : category));
                      setPreviewExpanded(true);
                    }}
                    className={`flex w-full items-center justify-between rounded px-1 py-0.5 text-xs transition-colors ${
                      selectedCategory === category ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted/50'
                    }`}
                  >
                    <span className={selectedCategory === category ? 'text-primary' : 'text-muted-foreground'}>
                      {CONSTRAINT_CATEGORY_LABELS[category] ?? category}
                    </span>
                    <span className="font-medium">{count}</span>
                  </button>
                ))}
            </div>
          </div>
        )}

        {topRules.length > 0 && (
          <div className="pt-1">
            <button
              type="button"
              onClick={() => setPreviewExpanded((v) => !v)}
              data-testid="constraint-summary-preview-toggle"
              className="text-xs font-medium text-primary hover:underline"
            >
              {previewExpanded
                ? '收起高优规则预览'
                : `查看高优规则预览 (${topRules.length})`}
            </button>
            {previewExpanded && (
              <div
                className="mt-1.5 space-y-1 rounded border border-border bg-muted/30 p-2 text-xs"
                data-testid="constraint-summary-preview-list"
              >
                {topRules.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="shrink-0 rounded bg-primary/10 px-1 py-0.5 font-mono text-ui-2xs text-primary">
                        P{rule.priority}
                      </span>
                      <span className="shrink-0 rounded bg-muted px-1 py-0.5 font-mono text-ui-2xs text-muted-foreground">
                        {rule.triggerPattern || 'always'}
                      </span>
                      <span className="truncate text-foreground">{rule.content}</span>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      data-testid={`constraint-summary-rule-to-l3-${rule.id}`}
                      onClick={async () => {
                        if (promotedRuleL3Ids.has(rule.id)) return;
                        setPromotedRuleL3Ids((prev) => new Set(prev).add(rule.id));
                        if (typeof projectApi?.confirmKnowledge === 'function') {
                          try {
                            await projectApi.confirmKnowledge(projectId, {
                              entries: [
                                {
                                  category: 'convention',
                                  content: rule.content,
                                  importance: rule.priority,
                                  sourceMessageIds: [],
                                  reasoning: '约束统计预览规则沉淀至 L3 画像',
                                },
                              ],
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                    >
                      {promotedRuleL3Ids.has(rule.id) ? '已存 L3' : '+L3'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-summary-rule-to-milestone-${rule.id}`}
                      onClick={async () => {
                        if (promotedRuleMilestoneIds.has(rule.id)) return;
                        setPromotedRuleMilestoneIds((prev) => new Set(prev).add(rule.id));
                        if (typeof projectApi?.createMilestone === 'function') {
                          try {
                            await projectApi.createMilestone(projectId, {
                              title: `[规则验收] ${rule.content.slice(0, 60)}`,
                              description: `来自 L2 高优规则 P${rule.priority} (${rule.category})`,
                              status: 'pending',
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {promotedRuleMilestoneIds.has(rule.id) ? '已转里程碑' : '+里程碑'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-summary-rule-to-l4-${rule.id}`}
                      onClick={async () => {
                        if (promotedRuleL4Ids.has(rule.id)) return;
                        setPromotedRuleL4Ids((prev) => new Set(prev).add(rule.id));
                        if (typeof projectApi?.addMaterial === 'function') {
                          try {
                            await projectApi.addMaterial(projectId, {
                              content: `# 高优约束归档 [P${rule.priority} · ${rule.category}]\n\n${rule.content}`,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {promotedRuleL4Ids.has(rule.id) ? '已存L4' : '+L4'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-summary-rule-copy-${rule.id}`}
                      onClick={async () => {
                        try {
                          await navigator.clipboard?.writeText(
                            `[P${rule.priority}] (${rule.triggerPattern || 'always'}) ${rule.content}`,
                          );
                          setCopiedRuleId(rule.id);
                          setTimeout(() => setCopiedRuleId(null), 1500);
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {copiedRuleId === rule.id ? '已复制' : '复制'}
                    </button>
                    <button
                      type="button"
                      data-testid={`constraint-summary-quick-toggle-${rule.id}`}
                      onClick={async () => {
                        if (typeof projectApi?.updateConstraint !== 'function') return;
                        try {
                          await projectApi.updateConstraint(projectId, rule.id, {
                            enabled: !rule.enabled,
                          });
                          await fetchConstraints();
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="shrink-0 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      停用
                    </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {constraints.length === 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground pt-2 border-t">
            <div>
              暂无约束。
              {projectType && <span> {getProjectTypeConstraintHint(projectType)}</span>}
            </div>
            {projectType && (
              <button
                type="button"
                disabled={importing}
                onClick={() => void handleQuickImport()}
                data-testid="constraint-summary-quick-import"
                className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
              >
                <Sparkles className="h-3 w-3" />
                {importing ? '导入中...' : '一键导入默认规范'}
              </button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function getProjectTypeConstraintHint(projectType: ProjectType): string {
  const hints: Record<ProjectType, string> = {
    coding: '可导入代码风格、Git 提交规范模板',
    research: '可导入学术写作、文献引用规范模板',
    business: '可导入商务文档、格式规范模板',
    personal: '可导入笔记组织、学习规划模板',
  };
  return hints[projectType];
}
