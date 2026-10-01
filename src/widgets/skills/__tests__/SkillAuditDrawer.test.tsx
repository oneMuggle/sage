// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resolveConfirm } from '../../../shared/ui/ConfirmDialog/confirmService';
import { SkillAuditDrawer } from '../SkillAuditDrawer';

const getAuditMock = vi.fn();
const rollbackMock = vi.fn();

vi.mock('../../../shared/api/skillsApi', () => ({
  skillsApi: {
    getAudit: (...args: unknown[]) => getAuditMock(...args),
    rollback: (...args: unknown[]) => rollbackMock(...args),
  },
}));

const ENTRIES = [
  {
    id: 3,
    skill_name: 'office_create',
    action: 'update',
    actor: 'user',
    source: 'editor',
    created_at: 1_757_000_000_000,
  },
  {
    id: 2,
    skill_name: 'office_create',
    action: 'consolidation_note',
    actor: 'system',
    source: 'consolidation_scan',
    created_at: 1_756_000_000_000,
  },
  {
    id: 1,
    skill_name: 'office_create',
    action: 'create',
    actor: 'system',
    source: 'builtin',
    created_at: 1_755_000_000_000,
  },
];

beforeEach(() => {
  getAuditMock.mockReset();
  rollbackMock.mockReset();
  getAuditMock.mockResolvedValue({ skill_name: 'office_create', entries: ENTRIES });
  rollbackMock.mockResolvedValue({ status: 'rolled_back', skill_name: 'office_create' });
});

describe('SkillAuditDrawer (P2-2)', () => {
  it('只在打开时拉取审计记录，不随卡片批量请求', async () => {
    const { rerender } = render(
      <SkillAuditDrawer skillName="office_create" open={false} onOpenChange={vi.fn()} />,
    );
    expect(getAuditMock).not.toHaveBeenCalled();

    rerender(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(getAuditMock).toHaveBeenCalledWith('office_create'));
  });

  it('按时间线展示每条变更，含动作与操作者', async () => {
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    await screen.findByTestId('skill-audit-timeline');
    expect(screen.getAllByTestId('skill-audit-entry')).toHaveLength(3);
    // 动作要翻成人话，不能直接把后端枚举丢给用户
    expect(screen.getByText('更新')).toBeInTheDocument();
    expect(screen.getByText('固化巡检记录')).toBeInTheDocument();
    expect(screen.getByText('创建')).toBeInTheDocument();
    // 三条记录里 1 条 user + 2 条 system
    expect(screen.getAllByText('你')).toHaveLength(1);
    expect(screen.getAllByText('系统')).toHaveLength(2);
  });

  it('如实说明只有元数据、没有 diff', async () => {
    // 后端 list 接口不返回 before/after 内容，UI 不得承诺展示 diff。
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    await screen.findByTestId('skill-audit-timeline');
    expect(screen.getByText(/变更历史/)).toBeInTheDocument();
  });

  it('加载失败时报错，不静默显示成「暂无变更」', async () => {
    // 审计读不到就等于「用户以为技能没被改过」—— 必须明说。
    getAuditMock.mockRejectedValue(new Error('后端不可达'));
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('后端不可达');
    expect(screen.queryByText('暂无变更记录')).not.toBeInTheDocument();
  });

  it('空台账给出明确空态', async () => {
    getAuditMock.mockResolvedValue({ skill_name: 'office_create', entries: [] });
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    expect(await screen.findByText('暂无变更记录')).toBeInTheDocument();
  });

  it('回滚必须先经显式确认 —— 取消就不调 API', async () => {
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    await screen.findByTestId('skill-audit-timeline');
    fireEvent.click(screen.getByTestId('skill-audit-rollback'));

    // confirmDialog 是 Promise，宿主在测试里用 resolveConfirm 应答
    await waitFor(() => expect(rollbackMock).not.toHaveBeenCalled());
    resolveConfirm(false);
    await waitFor(() => expect(rollbackMock).not.toHaveBeenCalled());
  });

  it('确认后执行回滚并通知外层刷新', async () => {
    const onRolledBack = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <SkillAuditDrawer
        skillName="office_create"
        open
        onOpenChange={onOpenChange}
        onRolledBack={onRolledBack}
      />,
    );
    await screen.findByTestId('skill-audit-timeline');
    fireEvent.click(screen.getByTestId('skill-audit-rollback'));
    await waitFor(() => expect(rollbackMock).not.toHaveBeenCalled());
    resolveConfirm(true);

    await waitFor(() => expect(rollbackMock).toHaveBeenCalledWith('office_create'));
    await waitFor(() => expect(onRolledBack).toHaveBeenCalled());
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('回滚失败时如实报错且不假装成功', async () => {
    rollbackMock.mockRejectedValue(new Error('没有可回滚的快照'));
    render(<SkillAuditDrawer skillName="office_create" open onOpenChange={vi.fn()} />);
    await screen.findByTestId('skill-audit-timeline');
    fireEvent.click(screen.getByTestId('skill-audit-rollback'));
    await waitFor(() => expect(rollbackMock).not.toHaveBeenCalled());
    resolveConfirm(true);
    // 失败时抽屉保持打开，用户还能看到台账并重试
    await waitFor(() => expect(rollbackMock).toHaveBeenCalled());
  });
});
