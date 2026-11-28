import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import type { ScoutFactsMeta } from '../../../shared/api/types/chatAndEventTypes';
import { FactReconBlock } from '../FactReconBlock';

const PERSISTED: ScoutFactsMeta = {
  facts: [
    { text: '落库事实甲的完整正文', source: '文档 A' },
    { text: '落库事实乙的完整正文', source: '' },
  ],
  fact_count: 2,
  truncated: false,
};

function seedLive(
  messageId = 'm1',
  opts: { status?: 'started' | 'progress' | 'done'; facts?: unknown[]; lines?: number } = {},
) {
  const store = useChatStreamStore.getState();
  store.startStream('s1', messageId);
  if (opts.lines) {
    for (let i = 0; i < opts.lines; i += 1) {
      store.setPlanProgress('s1', {
        stage: 'scout',
        status: 'progress',
        kind: 'thinking',
        text: `过程行 ${i}`,
      });
    }
  }
  store.setPlanProgress('s1', {
    stage: 'scout',
    status: opts.status ?? 'done',
    kind: 'message',
    text: '侦察完成',
    elapsed_ms: 12300,
    ...(opts.facts ? { detail: { facts: opts.facts, fact_count: opts.facts.length } } : {}),
  });
}

describe('FactReconBlock', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('无任何数据时不渲染', () => {
    const { container } = render(<FactReconBlock sessionId="s1" messageId="m1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('落库清单渲染折叠头与条数', () => {
    render(<FactReconBlock sessionId="s1" messageId="m1" persistedFacts={PERSISTED} />);
    expect(screen.getByTestId('fact-recon-block')).toBeInTheDocument();
    expect(screen.getByTestId('fact-recon-count')).toHaveTextContent('2 条事实');
    // 落库态默认折叠
    expect(screen.getByTestId('fact-recon-toggle')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('fact-recon-list')).not.toBeInTheDocument();
  });

  it('展开后逐条显示事实全文（不截断，4000 字上限内完整保留）', () => {
    // 4000 = 后端 SCOUT_FACT_MAX_CHARS = 上游 raw 上限 —— 合法载荷的最大长度。
    const long = '事实'.repeat(2000);
    expect(long).toHaveLength(4000);
    render(
      <FactReconBlock
        sessionId="s1"
        messageId="m1"
        persistedFacts={{ facts: [{ text: long, source: '' }], fact_count: 1 }}
      />,
    );
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    const item = screen.getByTestId('fact-recon-item-0');
    expect(item.textContent).toContain(long);
  });

  it('来源以 chip 形式展示；无来源则不渲染 chip', () => {
    render(<FactReconBlock sessionId="s1" messageId="m1" persistedFacts={PERSISTED} />);
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    const sources = screen.getAllByTestId('fact-recon-source');
    expect(sources).toHaveLength(1);
    expect(sources[0]).toHaveTextContent('来源：文档 A');
  });

  it('侦察进行中自动展开，完成后保持展开（facts 只在 done 时到达）', () => {
    seedLive('m1', { status: 'progress', facts: [{ text: '实时事实', source: '' }] });
    render(<FactReconBlock sessionId="s1" messageId="m1" />);
    expect(screen.getByTestId('fact-recon-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('fact-recon-list')).toBeInTheDocument();

    // scout 阶段 done → 保持展开（若此刻收起，用户会看到"刚填满就收起"）
    act(() => {
      useChatStreamStore.getState().setPlanProgress('s1', {
        stage: 'scout',
        status: 'done',
        kind: 'message',
        text: '侦察完成',
      });
    });
    expect(screen.getByTestId('fact-recon-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('fact-recon-list')).toBeInTheDocument();
  });

  it('done 后用户可手动收起', () => {
    seedLive('m1', { status: 'progress', facts: [{ text: '实时事实', source: '' }] });
    render(<FactReconBlock sessionId="s1" messageId="m1" />);
    act(() => {
      useChatStreamStore.getState().setPlanProgress('s1', {
        stage: 'scout',
        status: 'done',
        kind: 'message',
        text: '侦察完成',
      });
    });
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-toggle')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('fact-recon-list')).not.toBeInTheDocument();
  });

  it('用户手动展开后不被自动策略覆盖', () => {
    seedLive('m1', { status: 'done', facts: [{ text: '实时事实', source: '' }] });
    render(<FactReconBlock sessionId="s1" messageId="m1" />);
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('fact-recon-list')).toBeInTheDocument();
  });

  it('实时清单优先于落库清单', () => {
    seedLive('m1', { facts: [{ text: '实时事实唯一', source: '' }] });
    render(<FactReconBlock sessionId="s1" messageId="m1" persistedFacts={PERSISTED} />);
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-list').textContent).toContain('实时事实唯一');
    expect(screen.getByTestId('fact-recon-list').textContent).not.toContain('落库事实甲');
    expect(screen.getByTestId('fact-recon-count')).toHaveTextContent('1 条事实');
  });

  it('非流式气泡不吃实时数据（避免历史气泡重复渲染）', () => {
    seedLive('m1', { facts: [{ text: '实时事实唯一', source: '' }] });
    render(<FactReconBlock sessionId="s1" messageId="other" persistedFacts={PERSISTED} />);
    expect(screen.getByTestId('fact-recon-count')).toHaveTextContent('2 条事实');
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-list').textContent).not.toContain('实时事实唯一');
  });

  it('侦察过程是二级折叠，默认随侦察进行中展开', () => {
    seedLive('m1', { status: 'progress', lines: 3 });
    render(<FactReconBlock sessionId="s1" messageId="m1" />);
    const toggle = screen.getByTestId('fact-recon-process-toggle');
    // 3 条 seed 过程行 + 收尾的「侦察完成」消息行 = 4
    expect(toggle).toHaveTextContent('侦察过程（4）');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByTestId('fact-recon-process-line')).toHaveLength(4);
  });

  it('侦察过程可独立折叠', () => {
    seedLive('m1', { status: 'progress', lines: 2 });
    render(<FactReconBlock sessionId="s1" messageId="m1" />);
    fireEvent.click(screen.getByTestId('fact-recon-process-toggle'));
    expect(screen.queryByTestId('fact-recon-process')).not.toBeInTheDocument();
  });

  it('后端截断时给出提示', () => {
    render(
      <FactReconBlock
        sessionId="s1"
        messageId="m1"
        persistedFacts={{
          facts: [{ text: '事实', source: '' }],
          fact_count: 1,
          truncated: true,
        }}
      />,
    );
    fireEvent.click(screen.getByTestId('fact-recon-toggle'));
    expect(screen.getByTestId('fact-recon-truncated')).toBeInTheDocument();
  });
});
