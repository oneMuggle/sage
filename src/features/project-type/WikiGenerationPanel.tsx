/**
 * AI 代码→Wiki 生成面板 (M5, 2026-10-12)
 *
 * 嵌入项目工作台，用户可预览将被扫描的文件与提取的符号，
 * 然后一键调用 LLM 生成 Wiki 文档写入 wiki/ 目录。
 *
 * 流程: idle → previewing → previewed → generating → done
 */

import { BookMarked, Loader2, CheckCircle2, AlertCircle, FileCode2, Sparkles } from 'lucide-react';
import { useState, useCallback } from 'react';

import { projectApi } from '../../shared/api';
import type { ScannedFile, ExtractedSymbol, WikiGenerateResult } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface WikiGenerationPanelProps {
  projectId: string;
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

export function WikiGenerationPanel({ projectId, onGenerated }: WikiGenerationPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [incremental, setIncremental] = useState(false);
  const [files, setFiles] = useState<ScannedFile[]>([]);
  const [symbols, setSymbols] = useState<ExtractedSymbol[]>([]);
  const [result, setResult] = useState<WikiGenerateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** 预览：扫描文件 + 提取符号 */
  const handlePreview = useCallback(async () => {
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

  /** 重置 */
  const handleReset = useCallback(() => {
    setPhase('idle');
    setFiles([]);
    setSymbols([]);
    setResult(null);
    setError(null);
  }, []);

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

  return (
    <div className="space-y-3">
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <BookMarked className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium">AI 代码→Wiki 文档生成</span>
        <Badge variant="default">M5</Badge>
      </div>

      <p className="text-xs text-muted-foreground">
        扫描项目源文件，提取函数/类/方法符号，由 LLM 规划文档结构并逐模块生成 Wiki 页面。
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
          <div className="flex items-center gap-2 text-sm font-medium text-green-700">
            <CheckCircle2 className="h-4 w-4" />
            Wiki 生成完成
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-green-600">
            <span>新生成 {result.pagesGenerated} 页</span>
            <span>更新 {result.pagesUpdated} 页</span>
            <span>跳过 {result.pagesSkipped} 页</span>
          </div>
          {result.wikiPaths.length > 0 && (
            <div className="space-y-1">
              <span className="text-xs text-green-700">生成的文件：</span>
              <div className="max-h-32 overflow-y-auto">
                {result.wikiPaths.map((p) => (
                  <div key={p} className="flex items-center gap-1 text-xs text-green-600">
                    <FileCode2 className="h-3 w-3" />
                    <code>{p}</code>
                  </div>
                ))}
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
            <div className="flex items-center gap-2 text-xs font-medium">
              <FileCode2 className="h-3.5 w-3.5" />
              扫描到 {files.length} 个源文件
            </div>
            {Object.keys(fileCountByLang).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(fileCountByLang).map(([lang, count]) => (
                  <Badge key={lang} variant="secondary" className="text-xs">
                    {LANGUAGE_LABELS[lang] ?? lang}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* 符号统计 */}
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs font-medium">
              <Sparkles className="h-3.5 w-3.5" />
              提取到 {symbols.length} 个符号
            </div>
            {Object.keys(symbolCountByKind).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(symbolCountByKind).map(([kind, count]) => (
                  <Badge key={kind} variant="outline" className="text-xs">
                    {KIND_LABELS[kind] ?? kind}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* 文件列表（最多显示 10 个） */}
          {files.length > 0 && (
            <div className="max-h-24 overflow-y-auto rounded bg-muted/50 p-2">
              {files.slice(0, 10).map((f) => (
                <div key={f.path} className="flex items-center justify-between text-xs">
                  <code className="truncate">{f.path}</code>
                  <span className="shrink-0 text-muted-foreground">
                    {(f.sizeBytes / 1024).toFixed(1)} KB
                  </span>
                </div>
              ))}
              {files.length > 10 && (
                <div className="text-xs text-muted-foreground">
                  ... 另有 {files.length - 10} 个文件
                </div>
              )}
            </div>
          )}

          {/* 增量更新 + 生成按钮 */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              增量更新（仅重新生成变化的文件）
            </label>
          </div>

          <div className="flex gap-2">
            <Button size="sm" onClick={handleGenerate}>
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
        <div className="flex items-center gap-2 rounded-md border border-border p-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {phase === 'previewing' ? '扫描源文件并提取符号中...' : 'LLM 正在生成 Wiki 文档...'}
        </div>
      )}

      {/* 初始状态 */}
      {phase === 'idle' && (
        <Button size="sm" onClick={handlePreview}>
          <FileCode2 className="mr-1.5 h-3.5 w-3.5" />
          预览可生成文档的源文件
        </Button>
      )}
    </div>
  );
}
