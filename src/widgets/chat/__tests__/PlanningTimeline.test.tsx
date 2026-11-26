import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { PlanningTimeline } from '../PlanningTimeline';

function seed() {
  const store = useChatStreamStore.getState();
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
    const { container } = render(<PlanningTimeline sessionId="s1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('渲染阶段、耗时与最近行', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" />);
    expect(screen.getByTestId('planning-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent(
      '评估任务复杂度',
    );
    expect(screen.getByTestId('planning-stage-complexity_classify')).toHaveTextContent('1.2s');
    expect(screen.getByTestId('planning-stage-scout')).toHaveTextContent('read_file');
    expect(screen.getByTestId('planning-timeline')).toHaveTextContent('规划中');
  });

  it('可折叠', () => {
    seed();
    render(<PlanningTimeline sessionId="s1" />);
    fireEvent.click(screen.getByTestId('planning-timeline-toggle'));
    expect(screen.queryByTestId('planning-stage-scout')).not.toBeInTheDocument();
  });
});
