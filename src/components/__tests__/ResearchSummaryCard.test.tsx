/**
 * ResearchSummaryCard.test.tsx — 调研报告展示组件测试（2026-10-28）。
 *
 * 覆盖：
 * - 渲染 header（主题 + 充分度进度条 + 工作量）
 * - 渲染 findings 列表（含相关性图标）
 * - 渲染 meta 信息（findings 数 / sources 数）
 * - synthesis 折叠/展开交互
 * - sources 折叠/展开交互
 * - "基于调研生成 Plan" 按钮点击 → onGeneratePlan
 * - "补充调研" 按钮 disabled（当 onResearchMore 未提供）
 * - "补充调研" 按钮可用（当 onResearchMore 提供）
 * - "放弃" 按钮点击 → onDismiss
 * - confidence 颜色阈值（≥70% green / ≥40% yellow / <40% red）
 * - 空 findings 时不渲染"关键发现"区
 * - 空 sources 时不渲染"参考来源"区
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ResearchSummaryCard, type ResearchReport } from '../ResearchSummaryCard';

afterEach(cleanup);

// ── Fixtures ───────────────────────────────────────────────────────────────────

function makeReport(overrides: Partial<ResearchReport> = {}): ResearchReport {
  return {
    topic: '认证系统',
    findings: [
      {
        title: 'OAuth 2.0',
        summary: '标准授权协议',
        relevance: 'high',
        sources: ['https://oauth.net/2'],
      },
      {
        title: 'JWT Token',
        summary: '无状态令牌方案',
        relevance: 'medium',
        sources: ['https://jwt.io'],
      },
    ],
    sources: [
      { url: 'https://oauth.net/2', title: 'OAuth 2.0', snippet: '标准协议' },
      { url: 'https://jwt.io', title: 'JWT', snippet: '令牌格式' },
    ],
    confidence: 0.75,
    estimated_effort: '高',
    synthesis: '## 综合报告\nOAuth 2.0 是推荐方案。',
    ...overrides,
  };
}

// ── Rendering ──────────────────────────────────────────────────────────────────

describe('ResearchSummaryCard', () => {
  it('渲染 header（主题 + 充分度 + 工作量）', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    expect(screen.getByTestId('research-summary-card')).toBeInTheDocument();
    expect(screen.getByText(/调研报告: 认证系统/)).toBeInTheDocument();
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.getByText('预估工作量: 高')).toBeInTheDocument();
  });

  it('渲染 findings 列表', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    expect(screen.getByText('关键发现')).toBeInTheDocument();
    expect(screen.getByText('OAuth 2.0')).toBeInTheDocument();
    expect(screen.getByText('JWT Token')).toBeInTheDocument();
    expect(screen.getByText('标准授权协议')).toBeInTheDocument();
  });

  it('渲染 meta 信息（findings 数 + sources 数）', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    expect(screen.getByText('发现: 2 条')).toBeInTheDocument();
    expect(screen.getByText('来源: 2 个')).toBeInTheDocument();
  });

  it('渲染相关性图标（high=🔴, medium=🟡）', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    // 🔴 对应 high relevance, 🟡 对应 medium
    expect(screen.getByText('🔴')).toBeInTheDocument();
    expect(screen.getByText('🟡')).toBeInTheDocument();
  });

  it('confidence 进度条宽度正确', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ confidence: 0.6 })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const bar = screen.getByTestId('confidence-bar');
    expect(bar.style.width).toBe('60%');
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  // ── Collapse/Expand ───────────────────────────────────────────────────────

  it('synthesis 默认折叠，点击展开', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    // 综合报告内容默认不可见
    expect(screen.queryByTestId('synthesis-content')).not.toBeInTheDocument();

    // 点击展开
    fireEvent.click(screen.getByTestId('synthesis-toggle'));
    expect(screen.getByTestId('synthesis-content')).toBeInTheDocument();
    expect(screen.getByText(/OAuth 2.0 是推荐方案/)).toBeInTheDocument();

    // 点击收起
    fireEvent.click(screen.getByTestId('synthesis-toggle'));
    expect(screen.queryByTestId('synthesis-content')).not.toBeInTheDocument();
  });

  it('sources 默认折叠，点击展开', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    // 来源列表默认不可见
    expect(screen.queryByText('标准协议')).not.toBeInTheDocument();

    // 点击展开
    fireEvent.click(screen.getByTestId('sources-toggle'));
    expect(screen.getByText('标准协议')).toBeInTheDocument();
    expect(screen.getByText('令牌格式')).toBeInTheDocument();
  });

  // ── Actions ───────────────────────────────────────────────────────────────

  it('"基于调研生成 Plan" 按钮触发 onGeneratePlan', () => {
    const onGeneratePlan = vi.fn();
    render(
      <ResearchSummaryCard
        report={makeReport()}
        onGeneratePlan={onGeneratePlan}
        onDismiss={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('research-generate-plan'));
    expect(onGeneratePlan).toHaveBeenCalledOnce();
  });

  it('"放弃" 按钮触发 onDismiss', () => {
    const onDismiss = vi.fn();
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={onDismiss} />,
    );

    fireEvent.click(screen.getByTestId('research-dismiss'));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('"补充调研" 按钮 disabled 当 onResearchMore 未提供', () => {
    render(
      <ResearchSummaryCard report={makeReport()} onGeneratePlan={vi.fn()} onDismiss={vi.fn()} />,
    );

    const btn = screen.getByTestId('research-more');
    expect(btn).toBeDisabled();
  });

  it('"补充调研" 按钮 enabled 当 onResearchMore 提供', () => {
    const onResearchMore = vi.fn();
    render(
      <ResearchSummaryCard
        report={makeReport()}
        onGeneratePlan={vi.fn()}
        onResearchMore={onResearchMore}
        onDismiss={vi.fn()}
      />,
    );

    const btn = screen.getByTestId('research-more');
    expect(btn).not.toBeDisabled();

    fireEvent.click(btn);
    expect(onResearchMore).toHaveBeenCalledOnce();
  });

  // ── Edge cases ────────────────────────────────────────────────────────────

  it('空 findings 时不渲染"关键发现"区', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ findings: [] })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.queryByText('关键发现')).not.toBeInTheDocument();
  });

  it('空 sources 时不渲染"参考来源"区', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ sources: [] })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('sources-toggle')).not.toBeInTheDocument();
  });

  it('空 synthesis 时不渲染"综合报告"区', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ synthesis: '' })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.queryByTestId('synthesis-toggle')).not.toBeInTheDocument();
  });

  it('confidence < 40% 使用红色进度条', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ confidence: 0.2 })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const bar = screen.getByTestId('confidence-bar');
    expect(bar.className).toContain('bg-red-500');
    expect(screen.getByText('20%')).toBeInTheDocument();
  });

  it('confidence ≥ 70% 使用绿色进度条', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ confidence: 0.85 })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const bar = screen.getByTestId('confidence-bar');
    expect(bar.className).toContain('bg-green-500');
  });

  it('confidence 40%-69% 使用黄色进度条', () => {
    render(
      <ResearchSummaryCard
        report={makeReport({ confidence: 0.5 })}
        onGeneratePlan={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const bar = screen.getByTestId('confidence-bar');
    expect(bar.className).toContain('bg-yellow-500');
  });
});
