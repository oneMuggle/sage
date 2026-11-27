/**
 * TodoReportDialog — 日报 / 周报弹窗（P3）。
 *
 * 待办记「要做什么」，工作日志记「做过了什么」，报告把两者在**一个时间窗内**
 * 聚合成一份可直接发出去的 Markdown。面板分四块：
 *
 * 1. **时间窗** —— 起止日期 + 「生成并存档」；
 * 2. **历史抽屉** —— 已存档报告列表，点一条即回看；
 * 3. **统计块** —— 生成时刻冻结的统计切片（工作日志条数 / 完成数 / 积压数）；
 * 4. **正文预览** —— Markdown 渲染 + 复制 / 导出。
 *
 * **快照语义**：统计块显示的是该份报告生成**当时**的数字，不是实时查询结果 ——
 * 之后工作日志再改，历史报告也不回写（与后端 ``reports.stats_json`` 一致）。
 *
 * 打开时**不自动生成** —— 免得每开一次弹窗就往库里塞一条记录；改为加载历史
 * 并预览最近一份存档，用户点「生成并存档」才落库。
 */
import { Copy, Download, History, Loader2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { reportClient } from '../../shared/api/reportClient';
import { downloadMarkdownFile } from '../../shared/api/sessionApi';
import type { Report, ReportType } from '../../shared/api/types';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { Modal } from '../../shared/ui';
import { Markdown } from '../../widgets/markdown';

/** 历史抽屉一次拉取的条数。 */
const HISTORY_LIMIT = 50;

const TYPE_TITLES: Record<ReportType, string> = {
  daily: '日报',
  weekly: '周报',
};

interface TodoReportDialogProps {
  isOpen: boolean;
  /** 报告类型 —— 日报 / 周报。 */
  mode: ReportType;
  onClose: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** 本地日历日 → `YYYY-MM-DD`（与后端 naive 本地口径一致，不用 UTC）。 */
function dayKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** 默认时间窗 —— 日报 = 今天；周报 = 近 7 天（含今天）。 */
function defaultWindow(mode: ReportType): { start: string; end: string } {
  const now = new Date();
  const end = dayKey(now);
  if (mode === 'daily') return { start: end, end };
  const start = new Date(now.getTime());
  start.setDate(start.getDate() - 6);
  return { start: dayKey(start), end };
}

/** 导出文件名 —— `日报-2026-11-27.md` / `周报-2026-11-21_2026-11-27.md`。 */
function reportFilename(report: Report): string {
  const prefix = TYPE_TITLES[report.report_type] ?? '报告';
  const range =
    report.period_start === report.period_end
      ? report.period_start
      : `${report.period_start}_${report.period_end}`;
  return `${prefix}-${range}.md`;
}

/** 生成时刻（本地 ISO8601）→ `2026-11-27 20:30`。 */
function formatCreatedAt(createdAt: string): string {
  return createdAt.slice(0, 16).replace('T', ' ');
}

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-baseline gap-1 px-2 py-1 rounded bg-bg-muted/60 text-ui-xs">
      <span className="text-text-muted">{label}</span>
      <span className="font-medium text-text">{value}</span>
    </span>
  );
}

export function TodoReportDialog({ isOpen, mode, onClose }: TodoReportDialogProps) {
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [archived, setArchived] = useState<Report[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * 拉历史。``preview`` 给了就预览它（刚生成的那份），否则预览最新一条。
   */
  const loadHistory = useCallback(async (type: ReportType, preview?: Report) => {
    setLoadingHistory(true);
    try {
      const res = await reportClient.list({ report_type: type, limit: HISTORY_LIMIT });
      setArchived(res.items);
      setReport(preview ?? res.items[0] ?? null);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const win = defaultWindow(mode);
    setPeriodStart(win.start);
    setPeriodEnd(win.end);
    setError(null);
    void loadHistory(mode);
  }, [isOpen, mode, loadHistory]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const created = await reportClient.generate({
        report_type: mode,
        period_start: periodStart,
        period_end: periodEnd,
      });
      await loadHistory(mode, created);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setGenerating(false);
    }
  }, [mode, periodStart, periodEnd, loadHistory]);

  const handleCopy = useCallback(async () => {
    if (!report) return;
    await copyToClipboard(report.content, {
      successMessage: '报告已复制到剪贴板',
      errorMessage: '复制失败，请手动选中文本复制',
    });
  }, [report]);

  const handleExport = useCallback(() => {
    if (!report) return;
    downloadMarkdownFile(report.content, reportFilename(report));
  }, [report]);

  const stats = report?.stats ?? null;
  const worklogs = stats?.worklogs ?? null;
  const todos = stats?.todos ?? null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={TYPE_TITLES[mode]}
      size="lg"
      footer={
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleCopy()}
              disabled={!report}
              data-testid="report-copy"
              className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover disabled:opacity-40"
            >
              <Copy className="w-3 h-3" />
              复制
            </button>
            <button
              type="button"
              onClick={handleExport}
              disabled={!report}
              data-testid="report-export"
              className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border rounded-radius-sm hover:bg-bg-hover disabled:opacity-40"
            >
              <Download className="w-3 h-3" />
              导出 Markdown
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover"
          >
            关闭
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-3 max-h-[65vh] overflow-y-auto">
        {/* 时间窗 */}
        <section className="flex flex-wrap items-end gap-2 rounded-radius-sm border border-border bg-ui-card p-3">
          <label className="flex flex-col gap-1 text-ui-xs text-text-muted">
            开始
            <input
              type="date"
              value={periodStart}
              onChange={(e) => setPeriodStart(e.target.value)}
              data-testid="report-period-start"
              className="rounded border border-border bg-transparent px-2 py-1 text-sm text-text focus:border-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1 text-ui-xs text-text-muted">
            结束
            <input
              type="date"
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
              data-testid="report-period-end"
              className="rounded border border-border bg-transparent px-2 py-1 text-sm text-text focus:border-primary focus:outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={generating || !periodStart || !periodEnd}
            data-testid="report-generate"
            className="flex items-center gap-1 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed ml-auto"
          >
            {generating ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Sparkles className="w-3 h-3" />
            )}
            生成并存档
          </button>
        </section>

        {error && (
          <div
            className="px-3 py-2 bg-red-50 text-red-700 text-sm rounded"
            role="alert"
            data-testid="report-error"
          >
            {error}
          </div>
        )}

        {/* 历史抽屉 */}
        <section className="rounded-radius-sm border border-border bg-ui-card p-3">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            aria-expanded={showHistory}
            data-testid="report-history-toggle"
            className="flex items-center gap-1.5 text-ui-xs text-text-muted hover:text-text"
          >
            <History className="w-3.5 h-3.5" />
            历史存档（{archived.length}）
          </button>
          {showHistory && (
            <div className="mt-2">
              {loadingHistory && (
                <div
                  className="flex items-center gap-2 text-ui-xs text-text-muted py-2"
                  role="status"
                >
                  <Loader2 className="w-3 h-3 animate-spin" />
                  加载历史…
                </div>
              )}
              {!loadingHistory && archived.length === 0 && (
                <p className="text-ui-xs text-text-muted py-2" data-testid="report-history-empty">
                  还没有存档报告。
                </p>
              )}
              {!loadingHistory && archived.length > 0 && (
                <ul className="flex flex-col gap-1" data-testid="report-history">
                  {archived.map((item) => (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => setReport(item)}
                        className={`w-full text-left px-2 py-1.5 rounded border text-ui-xs ${
                          report?.id === item.id
                            ? 'border-primary text-primary'
                            : 'border-border text-text hover:border-primary'
                        }`}
                        data-testid={`report-history-item-${item.id}`}
                      >
                        <span className="block">{item.title}</span>
                        <span className="block text-ui-2xs text-text-muted">
                          {item.period_start} ~ {item.period_end} ·{' '}
                          {formatCreatedAt(item.created_at)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        {/* 统计块 —— 快照值，不是实时查询 */}
        <section
          className="rounded-radius-sm border border-border bg-ui-card p-3"
          data-testid="report-stats"
        >
          {report ? (
            <>
              <div className="flex flex-wrap items-center gap-1.5">
                <StatChip label="工作日志" value={worklogs?.total ?? 0} />
                <StatChip label="涉及会话" value={worklogs?.sessions ?? 0} />
                <StatChip label="完成待办" value={todos?.completed_count ?? 0} />
                <StatChip label="未完成" value={todos?.pending_count ?? 0} />
                <StatChip label="高优先级" value={todos?.pending_high?.length ?? 0} />
                <StatChip label="已逾期" value={todos?.overdue?.length ?? 0} />
                <span
                  className="px-2 py-1 rounded text-ui-xs bg-bg-muted/60 text-text-muted"
                  data-testid="report-ai-badge"
                >
                  {stats?.ai_generated ? 'AI 生成' : '模板生成'}
                </span>
              </div>
              <p className="mt-2 text-ui-2xs text-text-muted">
                统计为 {report.period_start} ~ {report.period_end} 生成时刻的快照，之后不随日志变动。
              </p>
            </>
          ) : (
            <p className="text-ui-xs text-text-muted">还没有报告。选好时间窗后点「生成并存档」。</p>
          )}
        </section>

        {/* 正文预览 */}
        <section className="rounded-radius-sm border border-border bg-ui-card p-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-ui-xs text-text-muted">{report ? report.title : '正文预览'}</h3>
            {report && (
              <span className="text-ui-2xs text-text-muted">
                生成于 {formatCreatedAt(report.created_at)}
              </span>
            )}
          </div>
          {report ? (
            <div className="text-sm text-text leading-relaxed" data-testid="report-content">
              <Markdown
                content={report.content}
                tier="minimal"
                headingAnchorPrefix={`report-${report.id}`}
              />
            </div>
          ) : (
            <p className="text-ui-xs text-text-muted py-4 text-center" data-testid="report-empty">
              还没有内容 —— 生成一份，或从历史存档里挑一份回看。
            </p>
          )}
        </section>
      </div>
    </Modal>
  );
}
