/**
 * Settings 页面 - 诊断与日志卡片
 *
 * T13 (2026-07-02): 让用户查看 / 管理 Sage 本地日志文件。
 * - 列出 logs/ 目录下所有 sage-YYYY-MM-DD.ndjson 文件
 * - 4 个按钮:打开日志目录 / 复制路径 / 立即清理 / 刷新
 * - 日志级别选择 (debug/info/warn/error) → IPC 写入 process.env.SAGE_LOG_LEVEL
 */

import { useEffect, useState } from 'react';

import type { LogLevel } from '../../shared/log/levels';

interface LogFile {
  name: string;
  sizeBytes: number;
  mtimeMs: number;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(ms: number): string {
  const d = new Date(ms);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('zh-CN');
}

export function DiagnosticsCard() {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [level, setLevel] = useState<LogLevel>('info');

  useEffect(() => {
    window.electronAPI
      ?.listLogFiles?.()
      .then((r) => setFiles(r ?? []))
      .finally(() => setLoading(false));
  }, []);

  const refresh = () => {
    setLoading(true);
    window.electronAPI
      ?.listLogFiles?.()
      .then((r) => setFiles(r ?? []))
      .finally(() => setLoading(false));
  };

  const handleLevelChange = async (newLevel: LogLevel) => {
    setLevel(newLevel);
    await window.electronAPI?.setLogLevel?.(newLevel);
  };

  const handleCleanup = async () => {
    await window.electronAPI?.cleanupLogs?.();
    refresh();
  };

  return (
    <section className="rounded-lg border border-border bg-card p-4" data-testid="diagnostics-card">
      <h2 className="text-lg font-semibold mb-3">诊断与日志</h2>

      <div className="mb-4">
        <div className="text-sm text-muted-foreground mb-2">日志目录(由系统管理,无需记忆)</div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => window.electronAPI?.openLogDir?.()}
            className="px-3 py-1 rounded border"
          >
            打开日志目录
          </button>
          <button
            onClick={() => window.electronAPI?.copyLogPath?.()}
            className="px-3 py-1 rounded border"
          >
            复制路径
          </button>
          <button onClick={handleCleanup} className="px-3 py-1 rounded border">
            立即清理旧日志
          </button>
          <button onClick={refresh} className="px-3 py-1 rounded border" disabled={loading}>
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      <div className="mb-4">
        <label htmlFor="log-level" className="text-sm text-muted-foreground mr-2">
          日志级别:
        </label>
        <select
          id="log-level"
          aria-label="日志级别"
          value={level}
          onChange={(e) => handleLevelChange(e.target.value as LogLevel)}
          className="border rounded px-2 py-1"
        >
          <option value="debug">debug</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
      </div>

      <div>
        <div className="text-sm text-muted-foreground mb-2">最近日志文件:</div>
        {loading && files.length === 0 ? (
          <div className="text-sm">加载中…</div>
        ) : files.length === 0 ? (
          <div className="text-sm text-muted-foreground">暂无日志文件</div>
        ) : (
          <ul className="text-sm space-y-1">
            {files.map((f) => (
              <li key={f.name} className="flex justify-between gap-4 font-mono">
                <span>{f.name}</span>
                <span className="text-muted-foreground">
                  {formatSize(f.sizeBytes)} · {formatTime(f.mtimeMs)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
