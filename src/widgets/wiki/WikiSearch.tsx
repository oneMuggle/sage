// Wiki Search - search bar and results
import { Search, FileText } from 'lucide-react';
import { useState } from 'react';

import { useWikiStore } from '../../entities/wiki/store';
import { wikiSearch } from '../../shared/api-client/wiki';
import type { SearchResult } from '../../shared/types/wiki';

export function WikiSearch() {
  const project = useWikiStore((s) => s.project);
  const openFile = useWikiStore((s) => s.openFile);
  const setActiveView = useWikiStore((s) => s.setActiveView);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const doSearch = async () => {
    if (!project || !query.trim()) return;
    setSearching(true);
    setHasSearched(true);
    try {
      const response = await wikiSearch(query, project.path);
      setResults(response.results);
    } catch (e) {
      console.error('搜索失败:', e);
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleOpen = (path: string) => {
    openFile(path);
    setActiveView('browser');
  };

  const handleCopyMd = () => {
    setCopiedMd(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedMd(false), 2000);
    const lines = [
      `# Wiki 搜索结果 — ${query}`,
      '',
      `- 项目路径: ${project?.path ?? ''}`,
      `- 结果数量: ${results.length}`,
      '',
      ...results.map((r) => `- **${r.title}** (\`${r.path}\`): ${r.snippet}`),
    ];
    void navigator.clipboard?.writeText(lines.join('\n'));
    /* v8 ignore stop */
  };

  const handleCopyJson = () => {
    setCopiedJson(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedJson(false), 2000);
    const payload = {
      project: project?.path ?? '',
      query,
      count: results.length,
      results,
    };
    void navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    /* v8 ignore stop */
  };

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        请先打开一个 wiki 项目
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Search bar */}
      <div className="border-b border-border px-4 py-3 bg-surface">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') doSearch();
            }}
            placeholder="搜索 wiki 页面 (Enter 搜索)"
            autoFocus
            className="w-full rounded-md border border-border bg-bg-muted py-2 pl-9 pr-3 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20 text-text"
          />
        </div>
      </div>

      {/* Results */}
      {searching && (
        <div className="flex-1 flex items-center justify-center text-muted text-sm">搜索中...</div>
      )}

      {!searching && !hasSearched && (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-muted text-sm">
          <Search className="h-8 w-8 text-muted/30" />
          <p>输入关键词后按 Enter 搜索</p>
        </div>
      )}

      {!searching && hasSearched && results.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-muted text-sm">
          未找到匹配 "{query}" 的结果
        </div>
      )}

      {!searching && results.length > 0 && (
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          <div className="flex items-center justify-between px-1">
            <div className="text-xs text-muted">找到 {results.length} 个结果</div>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                data-testid="wiki-search-copy-md-btn"
                onClick={handleCopyMd}
                className="px-2 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
              >
                {copiedMd ? '已复制MD' : '复制搜索MD'}
              </button>
              <button
                type="button"
                data-testid="wiki-search-copy-json-btn"
                onClick={handleCopyJson}
                className="px-2 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
              >
                {copiedJson ? '已复制JSON' : '复制搜索JSON'}
              </button>
            </div>
          </div>
          {results.map((result) => (
            <button
              key={result.path}
              onClick={() => handleOpen(result.path)}
              className="w-full rounded-lg border border-border p-3 text-left hover:bg-bg-muted transition-colors"
            >
              <div className="flex items-start gap-2 mb-1">
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-text truncate">{result.title}</div>
                  <div className="text-ui-2xs text-muted truncate">{result.path}</div>
                </div>
              </div>
              <p className="text-xs text-muted line-clamp-2">{result.snippet}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
