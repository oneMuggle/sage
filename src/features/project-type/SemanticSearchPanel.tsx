/**
 * M4: 语义检索面板 (2026-10-12)
 *
 * 嵌入 StudioMaterialsTabPanel，提供语义检索入口：
 * - 输入框：输入查询文本
 * - 搜索按钮：调用后端语义检索 API
 * - 结果展示：显示匹配的 chunks（按相关性排序）
 * - 索引状态：显示索引统计信息
 */

import { Search, Loader2, FileText, AlertCircle } from 'lucide-react';
import { useState, useCallback } from 'react';

import { projectApi } from '../../shared/api';
import type { SemanticSearchHit, IndexingStats } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface SemanticSearchPanelProps {
  projectId: string;
}

export function SemanticSearchPanel({ projectId }: SemanticSearchPanelProps) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SemanticSearchHit[] | null>(null);
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** 执行语义检索 */
  const handleSearch = useCallback(async () => {
    if (!query.trim() || searching) return;
    setSearching(true);
    setError(null);
    setResults(null);
    try {
      const result = await projectApi.semanticSearchMaterials(projectId, query.trim(), 10);
      setResults(result.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : '语义检索失败');
    } finally {
      setSearching(false);
    }
  }, [projectId, query, searching]);

  /** 加载索引统计 */
  const loadStats = useCallback(async () => {
    try {
      const s = await projectApi.getMaterialIndexingStats(projectId);
      setStats(s);
    } catch {
      // 静默失败（统计非关键）
    }
  }, [projectId]);

  /** Enter 键触发搜索 */
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      void handleSearch();
    }
  };

  /** 面板挂载时加载统计 */
  useState(() => {
    void loadStats();
  });

  return (
    <div className="space-y-3" data-testid="semantic-search-panel">
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium">语义检索</span>
        <Badge variant="default">M4</Badge>
      </div>

      <p className="text-xs text-muted-foreground">
        基于向量相似度搜索项目资料库，找到最相关的文本片段。
      </p>

      {/* 索引状态 */}
      {stats && (
        <div className="rounded-md border border-border bg-muted/30 p-2 text-xs">
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

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* 搜索框 */}
      <div className="flex gap-2">
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
      {results !== null && (
        <div className="space-y-2">
          {results.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
              未找到相关内容
            </div>
          ) : (
            <>
              <div className="text-xs text-muted-foreground">找到 {results.length} 个相关片段</div>
              <div className="max-h-80 space-y-2 overflow-y-auto">
                {results.map((hit, idx) => (
                  <div
                    key={`${hit.materialId}-${hit.chunkIndex}-${idx}`}
                    className="rounded-md border border-border bg-card p-3 text-xs"
                  >
                    <div className="mb-1.5 flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5 text-blue-500" />
                        <span className="font-medium">
                          材料 {hit.materialId.slice(0, 8)}... (chunk #{hit.chunkIndex})
                        </span>
                      </div>
                      <Badge variant="outline" className="text-xs">
                        相似度: {(hit.score * 100).toFixed(1)}%
                      </Badge>
                    </div>
                    <div className="max-h-32 overflow-y-auto rounded bg-muted/50 p-2 font-mono text-xs whitespace-pre-wrap">
                      {hit.content}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
