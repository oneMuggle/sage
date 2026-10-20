/**
 * Settings 页面 - 诊断与日志卡片
 *
 * T13 (2026-07-02): 让用户查看 / 管理 Sage 本地日志文件。
 * - 列出 logs/ 目录下所有 sage-YYYY-MM-DD.ndjson 文件
 * - 4 个按钮:打开日志目录 / 复制路径 / 立即清理 / 刷新
 * - 日志级别选择 (debug/info/warn/error) → IPC 写入 process.env.SAGE_LOG_LEVEL
 */

import { useEffect, useState } from 'react';

import { DEFAULT_LOG_LEVEL } from '../../shared/log/levels';
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
  const [level, setLevel] = useState<LogLevel>(DEFAULT_LOG_LEVEL);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [copiedFileKey, setCopiedFileKey] = useState<string | null>(null);

  useEffect(() => {
    window.electronAPI
      ?.listLogFiles?.()
      .then((r) => setFiles(r ?? []))
      .finally(() => setLoading(false));
  }, []);

  // 2026-09-15: 挂载时从主进程拉取当前生效的级别,避免切走再切回页面时
  // 被 useState 硬编码的默认值覆盖上次选择。
  // 显式检查 getLogLevel 是否存在 — 可选链 ?.()?.then() 在方法缺失时
  // 返回 undefined,再链上 .then 会抛 TypeError。Promise.resolve 兜底
  // 处理 fn() 返回非 Promise (如 vi.fn() 默认返回 undefined) 的测试场景。
  useEffect(() => {
    const fn = window.electronAPI?.getLogLevel;
    if (typeof fn !== 'function') return;
    Promise.resolve(fn())
      .then((l) => {
        if (l) setLevel(l);
      })
      .catch(() => {
        /* 主进程返回失败时保留 DEFAULT_LOG_LEVEL */
      });
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

  /* v8 ignore start */
  const handleCopyMd = async () => {
    const lines = [
      '# 运行日志诊断摘要',
      '',
      `- **当前日志级别**: \`${level}\``,
      `- **日志文件数**: ${files.length}`,
      '',
      '| 文件名 | 大小 | 修改时间 |',
      '| --- | --- | --- |',
      ...files.map((f) => `| ${f.name} | ${formatSize(f.sizeBytes)} | ${formatTime(f.mtimeMs)} |`),
    ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1800);
  };

  const handleCopyJson = async () => {
    const payload = {
      level,
      fileCount: files.length,
      files,
    };
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    setTimeout(() => setCopiedJson(false), 1800);
  };

  const handleCopyFileJson = async (f: LogFile) => {
    setCopiedFileKey(f.name);
    await navigator.clipboard?.writeText(JSON.stringify(f, null, 2));
    setTimeout(() => setCopiedFileKey((prev) => (prev === f.name ? null : prev)), 1800);
  };
  /* v8 ignore stop */

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
          <button
            type="button"
            data-testid="diagnostics-copy-md-btn"
            onClick={() => void handleCopyMd()}
            className="px-3 py-1 rounded border"
          >
            {copiedMd ? '✓ 已复制MD' : '复制诊断MD'}
          </button>
          <button
            type="button"
            data-testid="diagnostics-copy-json-btn"
            onClick={() => void handleCopyJson()}
            className="px-3 py-1 rounded border"
          >
            {copiedJson ? '✓ 已复制JSON' : '复制诊断JSON'}
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
                <span className="text-muted-foreground flex items-center gap-2">
                  <span>
                    {formatSize(f.sizeBytes)} · {formatTime(f.mtimeMs)}
                  </span>
                  <button
                    type="button"
                    data-testid={`diagnostics-file-copy-json-${f.name}`}
                    onClick={() => void handleCopyFileJson(f)}
                    className="px-1.5 py-0.5 rounded border text-xs font-sans"
                  >
                    {copiedFileKey === f.name ? '✓ 已复制' : '复制JSON'}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
