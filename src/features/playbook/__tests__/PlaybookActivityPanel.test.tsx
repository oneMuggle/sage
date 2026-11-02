// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { PlaybookEvent, PlaybookEventAggregate } from '../../../shared/api/playbookApi';
import { PlaybookActivityPanel } from '../PlaybookActivityPanel';

const events: PlaybookEvent[] = [
  {
    id: 1,
    project_id: 'p1',
    event: 'audit',
    stage: 'proposal',
    payload: {},
    created_at: 1793500000000,
  },
  {
    id: 2,
    project_id: 'p1',
    event: 'bind',
    stage: null,
    payload: {},
    created_at: 1793400000000,
  },
];

const aggregate: PlaybookEventAggregate = {
  days: 7,
  project_id: 'p1',
  counts: { audit: 5, bind: 2, export_json: 1 },
  total: 8,
};

describe('PlaybookActivityPanel', () => {
  it('空态显示无活动记录', () => {
    const onClose = vi.fn();
    render(<PlaybookActivityPanel events={[]} aggregate={null} onClose={onClose} />);
    expect(screen.getByTestId('playbook-activity')).toBeInTheDocument();
    expect(screen.getByText(/暂无活动记录/)).toBeInTheDocument();
  });

  it('按时间倒序渲染事件列表并翻译事件名', () => {
    const onClose = vi.fn();
    render(<PlaybookActivityPanel events={events} aggregate={aggregate} onClose={onClose} />);
    expect(screen.getByTestId('playbook-activity-event-1')).toBeInTheDocument();
    expect(screen.getByTestId('playbook-activity-event-2')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('playbook-activity-event-1')).getByText(/完整性检查/),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('playbook-activity-event-2')).getByText('绑定规程'),
    ).toBeInTheDocument();
  });

  it('聚合计数按频次降序展示', () => {
    const onClose = vi.fn();
    render(<PlaybookActivityPanel events={events} aggregate={aggregate} onClose={onClose} />);
    expect(screen.getByTestId('playbook-activity-summary')).toHaveTextContent(/8/);
    const chips = [
      screen.getByTestId('playbook-activity-count-audit'),
      screen.getByTestId('playbook-activity-count-bind'),
      screen.getByTestId('playbook-activity-count-export_json'),
    ];
    expect(chips[0]).toHaveTextContent(/× 5/);
    expect(chips[1]).toHaveTextContent(/× 2/);
    expect(chips[2]).toHaveTextContent(/× 1/);
  });

  it('未识别事件名降级为「未识别操作」', () => {
    const unknownEvents: PlaybookEvent[] = [
      { id: 9, project_id: 'p1', event: 'mystery_action', stage: null, payload: {}, created_at: 1 },
    ];
    const onClose = vi.fn();
    render(<PlaybookActivityPanel events={unknownEvents} aggregate={null} onClose={onClose} />);
    expect(screen.getByText('未识别操作')).toBeInTheDocument();
  });

  it('关闭按钮触发 onClose', () => {
    const onClose = vi.fn();
    render(<PlaybookActivityPanel events={events} aggregate={aggregate} onClose={onClose} />);
    fireEvent.click(screen.getByTestId('playbook-activity-close'));
    expect(onClose).toHaveBeenCalled();
  });
});
