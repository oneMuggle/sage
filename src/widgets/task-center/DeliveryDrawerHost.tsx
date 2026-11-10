// src/widgets/task-center/DeliveryDrawerHost.tsx
/**
 * A4: 全局交付抽屉宿主 —— 挂在 Layout，按 taskCenterStore.delivery 渲染
 * lane / office 交付抽屉；同时接管原 TaskCenterWidget 的后台 shell 输出抽屉。
 * 交付抽屉与 shell 抽屉互斥（store 的 openDelivery/openShellStream 互相清空），
 * 但**独立渲染** —— 不能用早退，否则其中一方的空状态会吞掉另一方。
 */
import type { ReactNode } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { OfficeDeliveryDrawer } from '../../features/office/OfficeDeliveryDrawer';
import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { LaneDetailDrawer } from '../orchestration/LaneDetailDrawer';

import { ShellStreamDrawer } from './ShellStreamDrawer';

export function DeliveryDrawerHost() {
  const delivery = useTaskCenterStore((s) => s.delivery);
  const closeDelivery = useTaskCenterStore((s) => s.closeDelivery);
  const shellStream = useTaskCenterStore((s) => s.shellStream);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const tasks = useTaskCenterStore((s) => s.tasks);

  let deliveryBlock: ReactNode = null;
  if (delivery?.kind === 'lane') {
    const lane = lanes.find((l) => l.lane_id === delivery.laneId) ?? null;
    deliveryBlock = lane ? <LaneDetailDrawer lane={lane} open onClose={closeDelivery} /> : null;
  } else if (delivery?.kind === 'office') {
    const ref = delivery.ref ?? tasks[delivery.entryId]?.deliveryRef;
    deliveryBlock = ref ? (
      <OfficeDeliveryDrawer
        entryId={delivery.entryId}
        workspacePath={ref.workspacePath}
        filePath={ref.filePath}
        formatSpec={ref.formatSpec}
        open
        onClose={closeDelivery}
      />
    ) : null;
  }

  return (
    <>
      {deliveryBlock}
      {shellStream ? <ShellStreamDrawer shellId={shellStream} /> : null}
    </>
  );
}

export interface DeliveryDrawerHostAuditInput {
  isOpen: boolean;
  activeSessionId: string;
  deliverableCount: number;
  hasCloseCallback: boolean;
}

export interface DeliveryDrawerHostAuditReport {
  isOpen: boolean;
  normalizedSessionId: string;
  normalizedDeliverableCount: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateDeliveryDrawerHostGovernanceAudit(
  input: DeliveryDrawerHostAuditInput,
): DeliveryDrawerHostAuditReport {
  const issueCodes: string[] = [];
  const normalizedSessionId = input.activeSessionId.trim();
  if (input.isOpen && !normalizedSessionId) {
    issueCodes.push('DELIVERY_DRAWER_HOST_SESSION_MISSING');
  }
  if (input.deliverableCount < 0) {
    issueCodes.push('DELIVERY_DRAWER_HOST_COUNT_NEGATIVE');
  }
  if (!input.hasCloseCallback) {
    issueCodes.push('DELIVERY_DRAWER_HOST_CLOSE_CALLBACK_MISSING');
  }
  return {
    isOpen: input.isOpen,
    normalizedSessionId,
    normalizedDeliverableCount: Math.max(0, Math.trunc(input.deliverableCount)),
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
