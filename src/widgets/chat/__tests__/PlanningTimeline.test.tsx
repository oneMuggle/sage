import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { PlanningTimeline } from '../PlanningTimeline';

function seed(messageId = 'm1') {
  const store = useChatStreamStore.getState();
  // 规划进度只挂在当前流式消息气泡上 —— 必须先开一条流再累积阶段。
  store.startStream('s1', messageId);
  store.setPlanProgress('s1', {
    stage: 'complexity_classify',
    status: 'done',
    kind: 'message',
    text: 'medium',
    elapsed_ms: 1200,
  });
  store.setPlanProgress('s1', {
    stage: 'scout',
    status: 'progress',
    kind: 'tool_call',
    text: 'read_file',
  });
}

describe('PlanningTimeline', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} });
  });

  it('无进度时不渲染', () => {
    const { container } = render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('渲染阶段、耗时与最近行', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent(
      '评估任务复杂度',
    );
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent('1.2s');
    // 非 scout 阶段仍展示最近行
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent('medium');
    // 2026-11-27: scout 阶段的过程行移交「事实侦察」区块（FactReconBlock），
    // 时间线不再重复渲染同一内容。
    expect(screen.getByTestId('planning-stage-scout')).not.toHaveTextContent('read_file');
    expect(screen.getByTestId('planning-timeline')).toHaveTextContent('规划中');
  });

  it('scout 阶段的过程行不在时间线渲染（移交事实侦察区块）', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    expect(screen.getByTestId('planning-stage-scout')).toHaveTextContent('事实侦察');
    expect(screen.getByTestId('planning-stage-scout')).not.toHaveTextContent('read_file');
  });

  it('可折叠', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    fireEvent.click(screen.getByTestId('planning-timeline-toggle'));
    expect(screen.queryByTestId('planning-stage-scout')).not.toBeInTheDocument();
  });

  it('仅当前流式消息气泡渲染（非流式 / id 不匹配时不渲染）', () => {
    seed('m1');
    const mismatch = render(<PlanningTimeline sessionId="s1" messageId="other" />);
    expect(mismatch.container).toBeEmptyDOMElement();
    mismatch.unmount();

    render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
  });

  it('有失败阶段且无进行中时标题显示「规划失败」', () => {
    const store = useChatStreamStore.getState();
    store.startStream('s1', 'm1');
    store.setPlanProgress('s1', {
      stage: 'scout',
      status: 'failed',
      kind: 'error',
      text: 'boom',
    });
    render(<PlanningTimeline sessionId="s1" messageId="m1" />);
    const timeline = screen.getByTestId('planning-timeline');
    expect(timeline).toHaveTextContent('规划失败');
    expect(timeline).not.toHaveTextContent('规划完成');
  });
});
