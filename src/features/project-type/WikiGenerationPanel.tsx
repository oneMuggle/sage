/**
 * AI 代码→Wiki 生成面板 (M5, 2026-10-12 / Phase P22 多形态适配 / Phase P24 M5→L4 入库闭环与清单导出 / Phase P31 全量批量纳入 L4 与扫描文件过滤)
 *
 * 嵌入项目工作台，用户可预览将被扫描的文件与提取的符号（支持按文件路径/语言筛选），
 * 一键调用 LLM 生成 Wiki 文档写入 wiki/ 目录，并支持单页或全量批量将生成的 Wiki 页面纳入 L4 受控资料池。
 *
 * 流程: idle → previewing → previewed → generating → done
 */

import {
  BookMarked,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileCode2,
  Sparkles,
  Copy,
  Check,
  FilePlus2,
  Search,
} from 'lucide-react';
import { useState, useCallback, useEffect } from 'react';

import { projectApi } from '../../shared/api';
import type { ScannedFile, ExtractedSymbol, WikiGenerateResult, ProjectType } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface WikiGenerationPanelProps {
  projectId: string;
  projectType?: ProjectType | null;
  /** 生成完成后回调（外部可刷新 Wiki 列表等） */
  onGenerated?: () => void;
}

type Phase = 'idle' | 'previewing' | 'previewed' | 'generating' | 'done';

const KIND_LABELS: Record<string, string> = {
  function: '函数',
  async_function: '异步函数',
  class: '类',
  method: '方法',
  async_method: '异步方法',
};

const LANGUAGE_LABELS: Record<string, string> = {
  python: 'Python',
  typescript: 'TypeScript',
  javascript: 'JavaScript',
  rust: 'Rust',
  go: 'Go',
  java: 'Java',
  cpp: 'C++',
  c: 'C',
};

const ARCHETYPE_WIKI_HINTS: Record<ProjectType, string> = {
  coding:
    '扫描项目源文件，提取函数/类/方法符号，由 LLM 规划文档结构并自动生成 README、ARCHITECTURE、DECISIONS 与 API_INDEX。',
  business:
    '扫描项目工作区文书与脚本资产，自动梳理生成项目总览 README、组织架构与审校决策台账 Wiki 页面。',
  research:
    '扫描课题实验脚本、文献与分析代码，自动生成课题总览、实验架构说明与研究决策记录 Wiki 页面。',
  personal:
    '扫描个人知识空间脚本与结构化笔记，自动汇总生成索引导航 README 与知识演进台账 Wiki 页面。',
};

export function WikiGenerationPanel({
  projectId,
  projectType = 'coding',
  onGenerated,
}: WikiGenerationPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [incremental, setIncremental] = useState(false);
  const [files, setFiles] = useState<ScannedFile[]>([]);
  const [symbols, setSymbols] = useState<ExtractedSymbol[]>([]);
  const [result, setResult] = useState<WikiGenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedPreview, setCopiedPreview] = useState(false);
  const [copiedManifest, setCopiedManifest] = useState(false);
  const [ingestedPaths, setIngestedPaths] = useState<Set<string>>(new Set());
  const [ingestingAll, setIngestingAll] = useState(false);
  const [fileFilter, setFileFilter] = useState('');
  const [symbolKindFilter, setSymbolKindFilter] = useState<string>('all');
  const [copiedSymbols, setCopiedSymbols] = useState(false);
  const [savedSymbolsProfile, setSavedSymbolsProfile] = useState(false);
  const [guardedSymbolIndices, setGuardedSymbolIndices] = useState<Set<number>>(new Set());
  const [milestoneSymbolIndices, setMilestoneSymbolIndices] = useState<Set<number>>(new Set());
  const [l3SymbolIndices, setL3SymbolIndices] = useState<Set<number>>(new Set());
  const [savedManifestL3, setSavedManifestL3] = useState(false);

  /** 重置 */
  const handleReset = useCallback(() => {
    setPhase('idle');
    setFiles([]);
    setSymbols([]);
    setResult(null);
    setError(null);
    setCopiedPreview(false);
    setCopiedManifest(false);
    setIngestedPaths(new Set());
    setIngestingAll(false);
    setFileFilter('');
    setSymbolKindFilter('all');
    setCopiedSymbols(false);
    setSavedSymbolsProfile(false);
  }, []);

  useEffect(() => {
    handleReset();
  }, [projectId, handleReset]);

  /** 预览：扫描文件 + 提取符号 */
  const handlePreview = useCallback(async () => {
    if (
      typeof projectApi?.wikiScanFiles !== 'function' ||
      typeof projectApi?.wikiExtractSymbols !== 'function'
    ) {
      return;
    }
    setError(null);
    setPhase('previewing');
    try {
      const [scanResult, symbolResult] = await Promise.all([
        projectApi.wikiScanFiles(projectId),
        projectApi.wikiExtractSymbols(projectId),
      ]);
      setFiles(scanResult.files);
      setSymbols(symbolResult.symbols);
      setPhase('previewed');
    } catch (err) {
      setError(err instanceof Error ? err.message : '预览失败');
      setPhase('idle');
    }
  }, [projectId]);

  /** 生成 Wiki */
  const handleGenerate = useCallback(async () => {
    if (typeof projectApi?.wikiGenerate !== 'function') return;
    setError(null);
    setPhase('generating');
    try {
      const genResult = await projectApi.wikiGenerate(projectId, { incremental });
      setResult(genResult);
      setPhase('done');
      onGenerated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Wiki 生成失败');
      setPhase('previewed');
    }
  }, [projectId, incremental, onGenerated]);

  /** M5 -> L4: 将生成的 Wiki 页面纳入 L4 受控资料池 */
  const handleIngestToMaterials = async (wikiPath: string) => {
    if (typeof projectApi?.addMaterialFromFile !== 'function' || ingestedPaths.has(wikiPath)) return;
    try {
      await projectApi.addMaterialFromFile(projectId, wikiPath);
      setIngestedPaths((prev) => new Set(prev).add(wikiPath));
    } catch {
      // ignore in offline/test mode
    }
  };

  /** M5 -> L4: 一键将全部生成的 Wiki 页面纳入 L4 受控资料池 */
  const handleIngestAllToMaterials = async () => {
    if (!result || ingestingAll || typeof projectApi?.addMaterialFromFile !== 'function') return;
    setIngestingAll(true);
    try {
      for (const p of result.wikiPaths) {
        if (!ingestedPaths.has(p)) {
          await projectApi.addMaterialFromFile(projectId, p);
        }
      }
      setIngestedPaths(new Set(result.wikiPaths));
    } catch {
      // ignore in offline/test mode
    } finally {
      setIngestingAll(false);
    }
  };

  const handleCopyPreviewSummary = async () => {
    const lines = [
      `# M5 Wiki 扫描与符号提取预览`,
      `- 源文件总数: ${files.length}`,
      `- 提取符号数: ${symbols.length}`,
      '',
      ...files.slice(0, 20).map((f) => `- \`${f.path}\` (${f.language})`),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedPreview(true);
      setTimeout(() => setCopiedPreview(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  const handleCopyManifest = async () => {
    if (!result) return;
    const lines = [
      `# M5 Wiki 生成清单`,
      `- 新生成: ${result.pagesGenerated} 页 | 更新: ${result.pagesUpdated} 页 | 跳过: ${result.pagesSkipped} 页`,
      '',
      ...result.wikiPaths.map((p) => `- \`${p}\``),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedManifest(true);
      setTimeout(() => setCopiedManifest(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  // ── 语言分组统计 ──
  const fileCountByLang = files.reduce<Record<string, number>>((acc, f) => {
    acc[f.language] = (acc[f.language] ?? 0) + 1;
    return acc;
  }, {});

  // ── 符号分组统计 ──
  const symbolCountByKind = symbols.reduce<Record<string, number>>((acc, s) => {
    acc[s.kind] = (acc[s.kind] ?? 0) + 1;
    return acc;
  }, {});

  const q = fileFilter.trim().toLowerCase();
  const filteredFiles = files.filter((f) => {
    if (!q) return true;
    return f.path.toLowerCase().includes(q) || f.language.toLowerCase().includes(q);
  });

  const allIngested =
    Boolean(result && result.wikiPaths.length > 0) &&
    result!.wikiPaths.every((p) => ingestedPaths.has(p));

  return (
    <div
      className="space-y-3 rounded-lg border border-border bg-card p-3.5"
      data-testid="wiki-generation-panel"
    >
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <BookMarked className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium">AI 代码→Wiki 文档生成</span>
        <Badge variant="default">M5</Badge>
      </div>

      <p className="text-xs text-muted-foreground">
        {ARCHETYPE_WIKI_HINTS[projectType ?? 'coding'] ?? ARCHETYPE_WIKI_HINTS.coding}
      </p>

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 结果展示 */}
      {phase === 'done' && result && (
        <div className="space-y-2 rounded-md border border-green-200 bg-green-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-medium text-green-700">
              <CheckCircle2 className="h-4 w-4" />
              Wiki 生成完成
            </div>
            <div className="flex items-center gap-1.5">
              {result.wikiPaths.length > 0 && (
                <button
                  type="button"
                  disabled={allIngested || ingestingAll}
                  onClick={() => void handleIngestAllToMaterials()}
                  data-testid="wiki-ingest-all-btn"
                  className="inline-flex items-center gap-1 rounded border border-green-300 bg-white/80 px-2 py-0.5 text-ui-2xs font-medium text-green-700 hover:bg-white disabled:opacity-60"
                >
                  {allIngested ? (
                    <>
                      <Check className="h-3 w-3" />
                      已全部纳入 L4
                    </>
                  ) : (
                    <>
                      <FilePlus2 className="h-3 w-3" />
                      全部纳入 L4 资料池
                    </>
                  )}
                </button>
              )}
              <button
                type="button"
                data-testid="wiki-save-manifest-l3-btn"
                onClick={async () => {
                  if (savedManifestL3) return;
                  setSavedManifestL3(true);
                  if (typeof projectApi?.confirmKnowledge === 'function') {
                    try {
                      await projectApi.confirmKnowledge(projectId, {
                        entries: [
                          {
                            category: 'architecture',
                            content: `M5 Wiki 生成索引（共 ${result.wikiPaths.length} 页）：${result.wikiPaths.join('、')}`,
                            importance: 7,
                            sourceMessageIds: [],
                            reasoning: 'M5 Wiki 文档清单沉淀至 L3 项目画像',
                          },
                        ],
                      });
                    } catch {
                      // ignore in test/offline mode
                    }
                  }
                }}
                className="inline-flex items-center gap-1 rounded border border-green-300 bg-white/80 px-2 py-0.5 text-ui-2xs font-medium text-green-700 hover:bg-white"
              >
                {savedManifestL3 ? '已沉淀至 L3' : '沉淀清单至 L3'}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyManifest()}
                data-testid="wiki-copy-manifest-btn"
                className="inline-flex items-center gap-1 rounded border border-green-300 bg-white/80 px-2 py-0.5 text-ui-2xs font-medium text-green-700 hover:bg-white"
              >
                {copiedManifest ? (
                  <>
                    <Check className="h-3 w-3" />
                    已复制清单
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" />
                    复制 Wiki 清单
                  </>
                )}
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-green-600">
            <span>新生成 {result.pagesGenerated} 页</span>
            <span>更新 {result.pagesUpdated} 页</span>
            <span>跳过 {result.pagesSkipped} 页</span>
          </div>
          {result.wikiPaths.length > 0 && (
            <div className="space-y-1">
              <span className="text-xs text-green-700">生成的文件（可一键纳入 L4 受控资料池）：</span>
              <div className="max-h-32 overflow-y-auto space-y-1">
                {result.wikiPaths.map((p, idx) => {
                  const isIngested = ingestedPaths.has(p);
                  return (
                    <div
                      key={p}
                      className="flex items-center justify-between gap-2 text-xs text-green-600"
                    >
                      <div className="flex items-center gap-1 min-w-0">
                        <FileCode2 className="h-3 w-3 shrink-0" />
                        <code className="truncate">{p}</code>
                      </div>
                      <button
                        type="button"
                        disabled={isIngested}
                        onClick={() => void handleIngestToMaterials(p)}
                        data-testid={`wiki-ingest-material-${idx}`}
                        className="shrink-0 inline-flex items-center gap-1 rounded border border-green-300 bg-white/80 px-1.5 py-0.5 text-ui-2xs text-green-700 hover:bg-white disabled:opacity-60"
                      >
                        {isIngested ? (
                          <>
                            <Check className="h-2.5 w-2.5" />
                            已纳入 L4
                          </>
                        ) : (
                          <>
                            <FilePlus2 className="h-2.5 w-2.5" />
                            纳入 L4 资料
                          </>
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {result.errors.length > 0 && (
            <div className="space-y-1">
              <span className="text-xs text-amber-700">错误：</span>
              {result.errors.map((e, i) => (
                <div key={i} className="text-xs text-amber-600">
                  {e}
                </div>
              ))}
            </div>
          )}
          <Button variant="ghost" size="sm" onClick={handleReset}>
            重新生成
          </Button>
        </div>
      )}

      {/* 预览结果 */}
      {phase === 'previewed' && (
        <div className="space-y-3 rounded-md border border-border p-3">
          {/* 文件统计 */}
          <div className="space-y-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-medium">
                <FileCode2 className="h-3.5 w-3.5" />
                扫描到 {files.length} 个源文件
              </div>
              <button
                type="button"
                onClick={() => void handleCopyPreviewSummary()}
                data-testid="wiki-copy-preview-btn"
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
              >
                {copiedPreview ? (
                  <>
                    <Check className="h-3 w-3 text-emerald-500" />
                    已复制摘要
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3 text-primary" />
                    复制扫描摘要
                  </>
                )}
              </button>
            </div>
            {Object.keys(fileCountByLang).length > 0 && (
              <div className="flex flex-wrap gap-1.5" data-testid="wiki-lang-filter-bar">
                <button
                  type="button"
                  data-testid="wiki-lang-filter-all"
                  onClick={() => setFileFilter('')}
                  className={`rounded border px-2 py-0.5 text-ui-2xs ${
                    !fileFilter
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-muted'
                  }`}
                >
                  全部语言 ({files.length})
                </button>
                {Object.entries(fileCountByLang).map(([lang, count]) => (
                  <button
                    key={lang}
                    type="button"
                    data-testid={`wiki-lang-filter-${lang}`}
                    onClick={() => setFileFilter(fileFilter === lang ? '' : lang)}
                    className={`rounded border px-2 py-0.5 text-ui-2xs ${
                      fileFilter === lang
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background text-foreground hover:bg-muted'
                    }`}
                  >
                    {LANGUAGE_LABELS[lang] ?? lang}: {count}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 符号统计与分类筛选 */}
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-medium">
                <Sparkles className="h-3.5 w-3.5" />
                提取到 {symbols.length} 个符号
              </div>
              {symbols.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    data-testid="wiki-save-symbols-profile-btn"
                    disabled={savedSymbolsProfile}
                    onClick={async () => {
                      if (savedSymbolsProfile || typeof projectApi?.confirmKnowledge !== 'function') {
                        return;
                      }
                      const topSyms = symbols
                        .slice(0, 6)
                        .map((s) => `${s.name} (${s.filePath})`)
                        .join(', ');
                      try {
                        await projectApi.confirmKnowledge(projectId, {
                          entries: [
                            {
                              category: 'architecture',
                              content: `M5 符号架构快照：共扫描 ${files.length} 个文件、提取 ${symbols.length} 个符号（核心符号：${topSyms}）`,
                              importance: 8,
                              sourceMessageIds: [],
                              reasoning: 'M5 Wiki 符号提取沉淀',
                            },
                          ],
                        });
                        setSavedSymbolsProfile(true);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-60"
                  >
                    {savedSymbolsProfile ? '已沉淀符号至 L3' : '沉淀符号摘要至 L3'}
                  </button>
                  <button
                    type="button"
                    data-testid="wiki-copy-symbols-btn"
                    onClick={async () => {
                      const list = symbols
                        .filter((s) => symbolKindFilter === 'all' || s.kind === symbolKindFilter)
                        .map((s) => `- [${KIND_LABELS[s.kind] ?? s.kind}] ${s.name} (${s.filePath}:${s.lineno})`);
                      try {
                        await navigator.clipboard?.writeText(list.join('\n'));
                        setCopiedSymbols(true);
                        setTimeout(() => setCopiedSymbols(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    <Copy className="h-3 w-3 text-primary" />
                    {copiedSymbols ? '已复制符号' : '复制符号清单'}
                  </button>
                </div>
              )}
            </div>
            {Object.keys(symbolCountByKind).length > 0 && (
              <div className="flex flex-wrap gap-1.5" data-testid="wiki-symbol-filter-bar">
                <button
                  type="button"
                  data-testid="wiki-symbol-filter-all"
                  onClick={() => setSymbolKindFilter('all')}
                  className={`rounded border px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                    symbolKindFilter === 'all'
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-muted'
                  }`}
                >
                  全部符号 ({symbols.length})
                </button>
                {Object.entries(symbolCountByKind).map(([kind, count]) => (
                  <button
                    key={kind}
                    type="button"
                    data-testid={`wiki-symbol-filter-${kind}`}
                    onClick={() => setSymbolKindFilter(kind)}
                    className={`rounded border px-2 py-0.5 text-ui-2xs font-medium transition-colors ${
                      symbolKindFilter === kind
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {KIND_LABELS[kind] ?? kind}: {count}
                  </button>
                ))}
              </div>
            )}
            {symbols.length > 0 && (
              <div
                className="max-h-24 overflow-y-auto rounded bg-muted/40 p-2 space-y-0.5 text-ui-2xs font-mono"
                data-testid="wiki-symbol-preview-list"
              >
                {symbols
                  .filter((s) => symbolKindFilter === 'all' || s.kind === symbolKindFilter)
                  .slice(0, 8)
                  .map((s, idx) => (
                    <div key={`${s.filePath}-${s.name}-${idx}`} className="flex items-center justify-between gap-2">
                      <span className="truncate text-foreground">
                        [{KIND_LABELS[s.kind] ?? s.kind}] {s.name}
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="text-muted-foreground">
                          {s.filePath}:{s.lineno}
                        </span>
                        <button
                          type="button"
                          data-testid={`wiki-symbol-to-constraint-${idx}`}
                          onClick={async () => {
                            if (guardedSymbolIndices.has(idx)) return;
                            setGuardedSymbolIndices((prev) => new Set(prev).add(idx));
                            if (typeof projectApi?.createConstraint === 'function') {
                              try {
                                await projectApi.createConstraint(projectId, {
                                  category: 'architecture',
                                  content: `核心符号契约保护：${s.name} (${s.filePath})`,
                                  triggerPattern: s.filePath,
                                  priority: 8,
                                });
                              } catch {
                                // ignore in test/offline mode
                              }
                            }
                          }}
                          className="rounded border border-border bg-background px-1 py-0 text-ui-2xs text-primary hover:bg-primary/10"
                        >
                          {guardedSymbolIndices.has(idx) ? '已护栏' : '+L2'}
                        </button>
                        <button
                          type="button"
                          data-testid={`wiki-symbol-to-milestone-${idx}`}
                          onClick={async () => {
                            if (milestoneSymbolIndices.has(idx)) return;
                            setMilestoneSymbolIndices((prev) => new Set(prev).add(idx));
                            if (typeof projectApi?.createMilestone === 'function') {
                              try {
                                await projectApi.createMilestone(projectId, {
                                  title: `[符号文档审校] ${s.name} (${s.filePath})`,
                                  description: `补齐 ${s.kind} ${s.name} 的契约说明与单元测试`,
                                  status: 'pending',
                                });
                              } catch {
                                // ignore in test/offline mode
                              }
                            }
                          }}
                          className="rounded border border-border bg-background px-1 py-0 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {milestoneSymbolIndices.has(idx) ? '已建里程碑' : '+里程碑'}
                        </button>
                        <button
                          type="button"
                          data-testid={`wiki-symbol-to-l3-${idx}`}
                          onClick={async () => {
                            if (l3SymbolIndices.has(idx)) return;
                            setL3SymbolIndices((prev) => new Set(prev).add(idx));
                            if (typeof projectApi?.confirmKnowledge === 'function') {
                              try {
                                await projectApi.confirmKnowledge(projectId, {
                                  entries: [
                                    {
                                      category: 'architecture',
                                      content: `核心符号 [${KIND_LABELS[s.kind] ?? s.kind}] ${s.name} (${s.filePath}:${s.lineno})`,
                                      importance: 7,
                                      sourceMessageIds: [],
                                      reasoning: 'M5 Wiki 单条核心符号沉淀至 L3 画像',
                                    },
                                  ],
                                });
                              } catch {
                                // ignore in test/offline mode
                              }
                            }
                          }}
                          className="rounded border border-border bg-background px-1 py-0 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {l3SymbolIndices.has(idx) ? '已存L3' : '+L3'}
                        </button>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>

          {/* 文件列表（支持按路径或语言筛选，最多显示 10 个） */}
          {files.length > 0 && (
            <div className="space-y-1.5">
              <div className="relative">
                <Search className="h-3 w-3 text-muted-foreground absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={fileFilter}
                  onChange={(e) => setFileFilter(e.target.value)}
                  placeholder="按文件路径或语言筛选预览文件..."
                  data-testid="wiki-preview-filter-input"
                  className="w-full rounded border border-input bg-background pl-6 pr-2 py-1 text-ui-2xs"
                />
              </div>
              <div className="max-h-24 overflow-y-auto rounded bg-muted/50 p-2">
                {filteredFiles.slice(0, 10).map((f) => (
                  <div key={f.path} className="flex items-center justify-between text-xs">
                    <code className="truncate">{f.path}</code>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-muted-foreground">
                        {(f.sizeBytes / 1024).toFixed(1)} KB
                      </span>
                      <button
                        type="button"
                        data-testid={`wiki-file-to-l4-${f.path}`}
                        onClick={async () => {
                          if (ingestedPaths.has(f.path)) return;
                          setIngestedPaths((prev) => new Set(prev).add(f.path));
                          if (typeof projectApi?.addMaterialFromFile === 'function') {
                            try {
                              await projectApi.addMaterialFromFile(projectId, f.path);
                            } catch {
                              // ignore in test/offline mode
                            }
                          }
                        }}
                        className="rounded border border-border bg-background px-1 py-0 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        {ingestedPaths.has(f.path) ? '已入库L4' : '+L4'}
                      </button>
                    </div>
                  </div>
                ))}
                {filteredFiles.length > 10 && (
                  <div className="text-xs text-muted-foreground">
                    ... 另有 {filteredFiles.length - 10} 个文件
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 增量更新 + 生成按钮 */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
                data-testid="wiki-incremental-checkbox"
                className="h-3.5 w-3.5"
              />
              增量更新（仅重新生成变化的文件）
            </label>
          </div>

          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => void handleGenerate()}
              data-testid="wiki-generate-btn"
            >
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
              生成 Wiki
            </Button>
            <Button variant="ghost" size="sm" onClick={handleReset}>
              取消
            </Button>
          </div>
        </div>
      )}

      {/* 加载状态 */}
      {(phase === 'previewing' || phase === 'generating') && (
        <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>{phase === 'previewing' ? '正在扫描文件并提取符号...' : '正在调用 LLM 生成 Wiki 页面...'}</span>
        </div>
      )}

      {/* 空闲态：预览按钮 */}
      {phase === 'idle' && (
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void handlePreview()}
          data-testid="wiki-preview-btn"
        >
          <FileCode2 className="mr-1.5 h-3.5 w-3.5" />
          扫描并预览项目结构
        </Button>
      )}
    </div>
  );
}
