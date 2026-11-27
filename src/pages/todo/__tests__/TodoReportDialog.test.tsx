/**
 * TodoReportDialog 日报/周报弹窗测试（P3）。
 *
 * 覆盖四个行为契约：
 * - 打开即拉历史并预览最近一份存档（**不自动生成**）；
 * - 点「生成并存档」调 `reportClient.generate` 并渲染正文；
 * - 历史抽屉可回看旧报告；
 * - 复制 / 导出两个动作只在有报告时可点。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Report } from '../../../shared/api/types';
import { TodoReportDialog } from '../TodoReportDialog';

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  copyToClipboard: vi.fn(),
  downloadMarkdownFile: vi.fn(),
}));

vi.mock('../../../shared/api/reportClient', () => ({
  reportClient: {
    generate: mocks.generate,
    list: mocks.list,
    get: mocks.get,
  },
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  downloadMarkdownFile: mocks.downloadMarkdownFile,
}));

/** 合成报告记录（日期为合成值，非生产数据）。 */
function makeReport(overrides: Partial<Report> = {}): Report {
  return {
    id: 1,
    title: '日报 · 2026-11-27',
    report_type: 'daily',
    period_start: '2026-11-27',
    period_end: '2026-11-27',
    content: '# 日报\n\n## 完成\n- 处理逾期项',
    stats: {
      ai_generated: true,
      worklogs: { total: 5, by_kind: { done: 3, progress: 2 }, sessions: 2 },
      todos: {
        completed: ['处理逾期项'],
        completed_count: 1,
        pending_high: ['补测试'],
        overdue: ['修登录'],
        pending_count: 4,
      },
    },
    created_at: '2026-11-27T20:30:00.123456',
    updated_at: '2026-11-27T20:30:00.123456',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  mocks.generate.mockResolvedValue(makeReport());
  mocks.copyToClipboard.mockResolvedValue(true);
});

describe('TodoReportDialog', () => {
  it('loads history on open and previews the latest archived report', async () => {
    mocks.list.mockResolvedValue({
      items: [makeReport({ id: 7, title: '日报 · 2026-11-26' })],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<TodoReportDialog isOpen mode="daily" onClose={vi.fn()} />);

    expect(await screen.findByTestId('report-content')).toHaveTextContent('处理逾期项');
    expect(mocks.list).toHaveBeenCalledWith({ report_type: 'daily', limit: 50 });
    // 打开不自动生成 —— 免得每开一次弹窗就往库里塞一条记录。
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it('does not call the backend while closed', () => {
    render(<TodoReportDialog isOpen={false} mode="daily" onClose={vi.fn()} />);

    expect(mocks.list).not.toHaveBeenCalled();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it('generates and archives a report for the selected window', async () => {
    render(<TodoReportDialog isOpen mode="daily" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByTestId('report-generate'));

    await waitFor(() => {
      expect(mocks.generate).toHaveBeenCalledTimes(1);
    });
    const arg = mocks.generate.mock.calls[0][0] as {
      report_type: string;
      period_start: string;
      period_end: string;
    };
    expect(arg.report_type).toBe('daily');
    expect(arg.period_start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(arg.period_end).toBe(arg.period_start);
    expect(await screen.findByTestId('report-content')).toHaveTextContent('处理逾期项');
  });

  it('surfaces generation failures inline', async () => {
    mocks.generate.mockRejectedValue(new Error('后端不可用'));

    render(<TodoReportDialog isOpen mode="weekly" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByTestId('report-generate'));

    expect(await screen.findByTestId('report-error')).toHaveTextContent('后端不可用');
    expect(mocks.generate).toHaveBeenCalledWith(
      expect.objectContaining({ report_type: 'weekly' }),
    );
  });

  it('shows the frozen statistics snapshot of the generated report', async () => {
    render(<TodoReportDialog isOpen mode="daily" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByTestId('report-generate'));

    const stats = await screen.findByTestId('report-stats');
    await waitFor(() => {
      expect(stats).toHaveTextContent('工作日志');
    });
    expect(stats).toHaveTextContent('5');
    expect(stats).toHaveTextContent('AI 生成');
  });

  it('replays an archived report from the history drawer', async () => {
    mocks.list.mockResolvedValue({
      items: [
        makeReport({ id: 7, title: '日报 · 2026-11-26', content: '# 旧日报' }),
        makeReport({ id: 8, title: '日报 · 2026-11-27', content: '# 新日报' }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });

    render(<TodoReportDialog isOpen mode="daily" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByTestId('report-history-toggle'));
    fireEvent.click(await screen.findByTestId('report-history-item-7'));

    expect(await screen.findByTestId('report-content')).toHaveTextContent('旧日报');
  });

  it('copies and exports the report body', async () => {
    render(<TodoReportDialog isOpen mode="daily" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByTestId('report-generate'));
    await screen.findByTestId('report-content');

    fireEvent.click(screen.getByTestId('report-copy'));
    await waitFor(() => {
      expect(mocks.copyToClipboard).toHaveBeenCalledWith(
        expect.stringContaining('处理逾期项'),
        expect.objectContaining({ successMessage: expect.any(String) }),
      );
    });

    fireEvent.click(screen.getByTestId('report-export'));
    await waitFor(() => {
      expect(mocks.downloadMarkdownFile).toHaveBeenCalledWith(
        expect.stringContaining('处理逾期项'),
        '日报-2026-11-27.md',
      );
    });
  });
});
