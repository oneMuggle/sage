/**
 * M4: 语义检索面板 (2026-10-12 / Phase P22 跨项目同步 / Phase P25 四形态检索词预设与全量结果导出 / Phase P31 M4→L3 画像沉淀与相似度阈值过滤)
 *
 * 嵌入 StudioMaterialsTabPanel，提供语义检索入口：
 * - 四形态快捷检索词预设胶囊：一键触发当前形态高频语义查询
 * - 输入框 + 搜索按钮：调用后端语义检索 API
 * - 结果展示：显示匹配的 chunks（按相关性排序），支持相似度阈值过滤、单条复制、一键沉淀至 L3 项目画像与全量结果 Markdown 导出
 * - 索引状态：随项目切换自动同步索引统计，支持手动刷新统计
 */

import { Search, Loader2, FileText, AlertCircle, Copy, Check, RefreshCw, Sparkles, BookmarkPlus, ShieldPlus } from 'lucide-react';
import { useState, useCallback, useEffect } from 'react';

import { projectApi } from '../../shared/api';
import type { SemanticSearchHit, IndexingStats, ProjectType } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

const SEMANTIC_QUERY_PRESETS: Record<ProjectType, string[]> = {
  coding: ['核心架构与 IPC 通信边界', '错误处理与异常恢复策略', '鉴权与权限校验逻辑'],
  business: ['违约责任与赔偿上限条款', '付款节点与发票开具约定', '保密期限与争议管辖法院'],
  research: ['基线模型对比与消融实验结果', '核心假设与研究问题 (RQ)', '数据集划分与超参数设置'],
  personal: ['核心概念定义与双链笔记', '待办行动项 (Next Actions)', '读书摘录与关键启发'],
};

export interface SemanticSearchPanelProps {
  projectId: string;
  projectType?: ProjectType;
}

export function SemanticSearchPanel({
  projectId,
  projectType = 'coding',
}: SemanticSearchPanelProps) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SemanticSearchHit[] | null>(null);
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [copiedAll, setCopiedAll] = useState(false);
  const [minScorePct, setMinScorePct] = useState<number>(0);
  const [topK, setTopK] = useState<number>(10);
  const [savedProfileIndices, setSavedProfileIndices] = useState<Set<number>>(new Set());
  const [savedConstraintIndices, setSavedConstraintIndices] = useState<Set<number>>(new Set());

  const presets = SEMANTIC_QUERY_PRESETS[projectType] ?? SEMANTIC_QUERY_PRESETS.coding;

  /** 执行语义检索 */
  const runSearch = useCallback(
    async (targetQuery: string) => {
      const trimmed = targetQuery.trim();
      if (!trimmed || searching || typeof projectApi?.semanticSearchMaterials !== 'function') {
        return;
      }
      setSearching(true);
      setError(null);
      setResults(null);
      setSavedProfileIndices(new Set());
    setSavedConstraintIndices(new Set());
      setSavedConstraintIndices(new Set());
      try {
        const result = await projectApi.semanticSearchMaterials(projectId, trimmed, topK);
        setResults(result.results);
      } catch (err) {
        setError(err instanceof Error ? err.message : '语义检索失败');
      } finally {
        setSearching(false);
      }
    },
    [projectId, searching, topK],
  );

  const handleSearch = useCallback(async () => {
    await runSearch(query);
  }, [query, runSearch]);

  /** 加载索引统计 */
  const loadStats = useCallback(async () => {
    if (!projectId || typeof projectApi?.getMaterialIndexingStats !== 'function') return;
    try {
      const s = await projectApi.getMaterialIndexingStats(projectId);
      setStats(s);
    } catch {
      // 静默失败（统计非关键）
    }
  }, [projectId]);

  /** 复制检索命中文本片段 */
  const handleCopyHit = async (content: string, idx: number) => {
    try {
      await navigator.clipboard?.writeText(content);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 1500);
    } catch {
      // ignore in test env
    }
  };

  /** M4 -> L2: 将检索命中片段直接固化为 L2 行为约束 */
  const handleSaveHitToConstraint = async (hit: SemanticSearchHit, idx: number) => {
    if (savedConstraintIndices.has(idx) || typeof projectApi?.createConstraint !== 'function') {
      return;
    }
    try {
      await projectApi.createConstraint(projectId, {
        category: 'convention',
        content: hit.content.slice(0, 300),
        priority: 7,
      });
      setSavedConstraintIndices((prev) => new Set(prev).add(idx));
    } catch {
      // ignore in test/offline mode
    }
  };

  /** M4 -> L3: 将高价值检索片段一键沉淀至 L3 项目画像 */
  const handleSaveHitToProfile = async (hit: SemanticSearchHit, idx: number) => {
    if (savedProfileIndices.has(idx) || typeof projectApi?.confirmKnowledge !== 'function') return;
    try {
      await projectApi.confirmKnowledge(projectId, {
        entries: [
          {
            category: 'note',
            content: hit.content.slice(0, 500),
            importance: 7,
            sourceMessageIds: [],
            reasoning: 'M4 语义检索命中',
          },
        ],
      });
      setSavedProfileIndices((prev) => new Set(prev).add(idx));
    } catch {
      // ignore in test/offline mode
    }
  };

  const filteredResults = results
    ? results.filter((hit) => hit.score * 100 >= minScorePct)
    : null;

  /** 复制全部检索命中结果为 Markdown */
  const handleCopyAllResults = async () => {
    if (!filteredResults || filteredResults.length === 0) return;
    const lines = [
      `# M4 语义检索结果（查询：${query}）`,
      '',
      ...filteredResults.map(
        (hit, i) =>
          `### ${i + 1}. 材料 ${hit.materialId.slice(0, 8)} (chunk #${hit.chunkIndex} · 相似度 ${(hit.score * 100).toFixed(1)}%)\n${hit.content}`,
      ),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n\n'));
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  /** Enter 键触发搜索 */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      void handleSearch();
    }
  };

  /** 面板挂载或切换项目时重置检索结果并加载当前项目统计 */
  useEffect(() => {
    setResults(null);
    setError(null);
    setMinScorePct(0);
    setSavedProfileIndices(new Set());
    setSavedConstraintIndices(new Set());
    void loadStats();
  }, [projectId, loadStats]);

  return (
    <div className="space-y-3" data-testid="semantic-search-panel">
      {/* 标题 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-medium">语义检索</span>
          <Badge variant="default">M4</Badge>
        </div>
        <button
          type="button"
          onClick={() => void loadStats()}
          data-testid="semantic-stats-refresh-btn"
          className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <RefreshCw className="h-2.5 w-2.5" />
          刷新索引统计
        </button>
      </div>

      <p className="text-xs text-muted-foreground">
        基于向量相似度搜索项目资料库，找到最相关的文本片段。
      </p>

      {/* 索引状态 */}
      {stats && (
        <div
          className="rounded-md border border-border bg-muted/30 p-2 text-xs"
          data-testid="semantic-indexing-stats"
        >
          <div className="flex flex-wrap gap-3">
            <span>
              总材料: <strong>{stats.totalMaterials}</strong>
            </span>
            <span>
              已索引: <strong className="text-green-600">{stats.indexedMaterials}</strong>
            </span>
            <span>
              待索引: <strong className="text-amber-600">{stats.pendingMaterials}</strong>
            </span>
            {stats.failedMaterials > 0 && (
              <span>
                失败: <strong className="text-red-600">{stats.failedMaterials}</strong>
              </span>
            )}
            <span>
              总 chunks: <strong>{stats.totalChunks}</strong>
            </span>
          </div>
          {stats.embedderType && stats.embedderType !== 'unavailable' && (
            <div className="mt-1 text-xs text-muted-foreground">
              Embedder: {stats.embedderType} ({stats.embedderDims} 维)
            </div>
          )}
        </div>
      )}

      {/* 四形态推荐检索词预设 */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="semantic-query-presets">
        <span className="inline-flex items-center gap-1 text-ui-2xs text-muted-foreground">
          <Sparkles className="h-3 w-3 text-primary" />
          快捷检索预设：
        </span>
        {presets.map((presetText, idx) => (
          <button
            key={presetText}
            type="button"
            disabled={searching}
            data-testid={`semantic-preset-${idx}`}
            onClick={() => {
              setQuery(presetText);
              void runSearch(presetText);
            }}
            className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-50"
          >
            {presetText}
          </button>
        ))}
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 搜索框与 Top-K 快捷胶囊 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1" data-testid="semantic-topk-pills">
          {[3, 5, 10].map((k) => (
            <button
              key={k}
              type="button"
              data-testid={`semantic-topk-pill-${k}`}
              onClick={() => setTopK(k)}
              className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                topK === k
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-background text-muted-foreground hover:bg-muted'
              }`}
            >
              Top {k}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入查询文本，按 Enter 搜索..."
          data-testid="semantic-search-input"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs"
          disabled={searching}
        />
        <Button
          size="sm"
          onClick={() => void handleSearch()}
          disabled={!query.trim() || searching}
          data-testid="semantic-search-button"
        >
          {searching ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Search className="mr-1.5 h-3.5 w-3.5" />
          )}
          搜索
        </Button>
      </div>

      {/* 搜索结果 */}
      {filteredResults !== null && (
        <div className="space-y-2">
          {results && results.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <div className="flex flex-wrap items-center gap-1.5">
                <span>找到 {filteredResults.length} 个相关片段</span>
                <div className="flex items-center gap-1" data-testid="semantic-score-filters">
                  {[
                    { pct: 0, label: '全部' },
                    { pct: 50, label: '≥50%' },
                    { pct: 75, label: '≥75%' },
                  ].map((item) => (
                    <button
                      key={item.pct}
                      type="button"
                      onClick={() => setMinScorePct(item.pct)}
                      data-testid={`semantic-score-filter-${item.pct}`}
                      className={`rounded border px-1.5 py-0.5 text-ui-2xs ${
                        minScorePct === item.pct
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border bg-background text-muted-foreground hover:bg-muted'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
              {filteredResults.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    data-testid="semantic-batch-to-constraint-btn"
                    onClick={async () => {
                      const unsaved = filteredResults
                        .map((hit, idx) => ({ hit, idx }))
                        .filter(({ idx }) => !savedConstraintIndices.has(idx));
                      if (unsaved.length === 0) return;
                      setSavedConstraintIndices((prev) => {
                        const next = new Set(prev);
                        unsaved.forEach(({ idx }) => next.add(idx));
                        return next;
                      });
                      if (typeof projectApi?.createConstraint === 'function') {
                        for (const { hit } of unsaved) {
                          try {
                            await projectApi.createConstraint(projectId, {
                              category: 'reference_rule',
                              content: hit.content.slice(0, 300),
                              priority: 7,
                            });
                          } catch {
                            // ignore in test/offline mode
                          }
                        }
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                  >
                    <ShieldPlus className="h-3 w-3 text-primary" />
                    批量转 L2 约束 ({filteredResults.filter((_, idx) => !savedConstraintIndices.has(idx)).length})
                  </button>
                  <button
                    type="button"
                    data-testid="semantic-batch-save-profile-btn"
                    onClick={async () => {
                      const unsaved = filteredResults
                        .map((hit, idx) => ({ hit, idx }))
                        .filter(({ idx }) => !savedProfileIndices.has(idx));
                      if (unsaved.length === 0 || typeof projectApi?.confirmKnowledge !== 'function') {
                        return;
                      }
                      try {
                        await projectApi.confirmKnowledge(projectId, {
                          entries: unsaved.map(({ hit }) => ({
                            category: 'note',
                            content: hit.content.slice(0, 500),
                            importance: 7,
                            sourceMessageIds: [],
                            reasoning: 'M4 语义检索批量沉淀',
                          })),
                        });
                        setSavedProfileIndices((prev) => {
                          const next = new Set(prev);
                          unsaved.forEach(({ idx }) => next.add(idx));
                          return next;
                        });
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
                  >
                    <BookmarkPlus className="h-3 w-3" />
                    批量沉淀 L3 ({filteredResults.filter((_, idx) => !savedProfileIndices.has(idx)).length})
                  </button>
                  <button
                    type="button"
                    data-testid="semantic-clear-results-btn"
                    onClick={() => {
                      setResults(null);
                      setQuery('');
                      setMinScorePct(0);
                    }}
                    className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
                  >
                    清空结果
                  </button>
                  <button
                  type="button"
                  onClick={() => void handleCopyAllResults()}
                  data-testid="semantic-copy-all-btn"
                  className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
                >
                  {copiedAll ? (
                    <>
                      <Check className="h-3 w-3 text-emerald-500" />
                      已复制全部结果
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3 text-primary" />
                      复制全部检索结果
                    </>
                  )}
                </button>
                </div>
              )}
            </div>
          )}

          {filteredResults.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
              未找到相关内容
            </div>
          ) : (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {filteredResults.map((hit, idx) => {
                const isSavedToProfile = savedProfileIndices.has(idx);
                return (
                  <div
                    key={`${hit.materialId}-${hit.chunkIndex}-${idx}`}
                    className="rounded-md border border-border bg-card p-3 text-xs"
                  >
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5 text-blue-500" />
                        <span className="font-medium">
                          材料 {hit.materialId.slice(0, 8)}... (chunk #{hit.chunkIndex})
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Badge variant="outline" className="text-xs">
                          相似度: {(hit.score * 100).toFixed(1)}%
                        </Badge>
                        <button
                          type="button"
                          disabled={isSavedToProfile}
                          onClick={() => void handleSaveHitToProfile(hit, idx)}
                          data-testid={`semantic-hit-save-profile-${idx}`}
                          className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-60"
                          title="将此片段沉淀至 L3 项目画像"
                        >
                          {isSavedToProfile ? (
                            <>
                              <Check className="h-2.5 w-2.5 text-emerald-500" />
                              已沉淀 L3
                            </>
                          ) : (
                            <>
                              <BookmarkPlus className="h-2.5 w-2.5" />
                              沉淀至 L3 画像
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          disabled={savedConstraintIndices.has(idx)}
                          onClick={() => void handleSaveHitToConstraint(hit, idx)}
                          data-testid={`semantic-hit-to-constraint-${idx}`}
                          className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-60"
                          title="将此检索片段固化为 L2 强约束规则"
                        >
                          <ShieldPlus className="h-2.5 w-2.5 text-primary" />
                          {savedConstraintIndices.has(idx) ? '已转 L2 约束' : '转 L2 约束'}
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleCopyHit(hit.content, idx)}
                          data-testid={`semantic-hit-copy-${idx}`}
                          className="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {copiedIdx === idx ? (
                            <>
                              <Check className="h-2.5 w-2.5 text-emerald-500" />
                              已复制
                            </>
                          ) : (
                            <>
                              <Copy className="h-2.5 w-2.5 text-muted-foreground" />
                              复制片段
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                    <div className="max-h-32 overflow-y-auto rounded bg-muted/50 p-2 font-mono text-xs whitespace-pre-wrap">
                      {hit.content}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
