import { useQuery } from '@tanstack/react-query';
import { parseChangelog, generateSummary } from '../../lib/changelogParser';
import { useState } from 'react';

export function ChangelogTab() {
  const [expandedVersions, setExpandedVersions] = useState<Set<string>>(new Set(['current']));

  const {
    data: changelog,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['changelog'],
    queryFn: async () => {
      const content = await window.changelogAPI?.read();
      if (!content) throw new Error('无法读取更新日志');
      return content;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse text-text-secondary">加载更新日志...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-error">
          加载失败: {error instanceof Error ? error.message : String(error)}
        </div>
      </div>
    );
  }

  if (!changelog) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-text-secondary">暂无更新日志</div>
      </div>
    );
  }

  const entries = parseChangelog(changelog);
  const summary = generateSummary(entries);

  const toggleVersion = (version: string) => {
    setExpandedVersions((prev) => {
      const next = new Set(prev);
      if (next.has(version)) {
        next.delete(version);
      } else {
        next.add(version);
      }
      return next;
    });
  };

  return (
    <div className="max-w-4xl mx-auto px-8 py-8">
      {/* Current Version Summary */}
      {summary.currentVersion && (
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-semibold text-text">
              当前版本: v{summary.currentVersion.version}
            </h2>
            <span className="text-sm text-text-secondary">📅 {summary.currentVersion.date}</span>
          </div>

          {/* Major Features */}
          {summary.highlightsByCategory.major.length > 0 && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold mb-3 text-text flex items-center gap-2">
                <span>🚀</span>
                <span>重大功能 ({summary.highlightsByCategory.major.length})</span>
              </h3>
              <ul className="space-y-2">
                {summary.highlightsByCategory.major.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-text">
                    <span className="text-primary mt-1">•</span>
                    <span className="flex-1">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Improvements */}
          {summary.highlightsByCategory.improvements.length > 0 && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold mb-3 text-text flex items-center gap-2">
                <span>✨</span>
                <span>改进 ({summary.highlightsByCategory.improvements.length})</span>
              </h3>
              <ul className="space-y-2">
                {summary.highlightsByCategory.improvements.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-text">
                    <span className="text-primary mt-1">•</span>
                    <span className="flex-1">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Fixes */}
          {summary.highlightsByCategory.fixes.length > 0 && (
            <div className="mb-6">
              <h3 className="text-lg font-semibold mb-3 text-text flex items-center gap-2">
                <span>🐛</span>
                <span>修复 ({summary.highlightsByCategory.fixes.length})</span>
              </h3>
              <ul className="space-y-2">
                {summary.highlightsByCategory.fixes.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-text">
                    <span className="text-primary mt-1">•</span>
                    <span className="flex-1">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* Recent Versions */}
      {summary.recentVersions.length > 0 && (
        <section>
          <h2 className="text-2xl font-semibold mb-4 text-text flex items-center gap-2">
            <span>📜</span>
            <span>历史版本</span>
          </h2>
          <div className="space-y-4">
            {summary.recentVersions.map((entry) => (
              <div
                key={entry.version}
                className="border border-border rounded-radius-sm overflow-hidden"
              >
                <button
                  onClick={() => toggleVersion(entry.version)}
                  className="w-full px-4 py-3 flex items-center justify-between bg-surface hover:bg-bg-hover transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-text-secondary">
                      {expandedVersions.has(entry.version) ? '▼' : '▶'}
                    </span>
                    <span className="font-semibold text-text">v{entry.version}</span>
                    <span className="text-sm text-text-secondary">{entry.date}</span>
                  </div>
                  <div className="flex gap-2 text-xs">
                    {entry.highlights.major.length > 0 && (
                      <span className="px-2 py-1 rounded bg-primary/10 text-primary">
                        {entry.highlights.major.length} 功能
                      </span>
                    )}
                    {entry.highlights.fixes.length > 0 && (
                      <span className="px-2 py-1 rounded bg-success/10 text-success">
                        {entry.highlights.fixes.length} 修复
                      </span>
                    )}
                  </div>
                </button>
                {expandedVersions.has(entry.version) && (
                  <div className="px-4 py-3 bg-bg border-t border-border">
                    {entry.raw && (
                      <pre className="text-xs text-text-secondary whitespace-pre-wrap font-sans">
                        {entry.raw}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* View Full Changelog Link */}
      <div className="mt-8 text-center">
        <a
          href="https://github.com/oneMuggle/sage/blob/main/CHANGELOG.md"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline text-sm"
        >
          查看完整更新日志 →
        </a>
      </div>
    </div>
  );
}
