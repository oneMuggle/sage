// src/widgets/task-center/DeliveryDrawerHost.tsx
/**
 * A4: 全局交付抽屉宿主 —— 挂在 Layout（TaskCenterWidget 旁），按
 * taskCenterStore.delivery 渲染 lane / office 交付抽屉。
 * lane 行从 laneBoardStore 按 id 解析（决议后行更新自动透传）；
 * office 坐标从条目的 deliveryRef 解析（条目/坐标缺失则不渲染）。
 */
import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { OfficeDeliveryDrawer } from '../../features/office/OfficeDeliveryDrawer';
import { useTaskCenterStore } from '../../features/task-center/taskCenterStore';
import { LaneDetailDrawer } from '../orchestration/LaneDetailDrawer';

export function DeliveryDrawerHost() {
  const delivery = useTaskCenterStore((s) => s.delivery);
  const closeDelivery = useTaskCenterStore((s) => s.closeDelivery);
  const lanes = useLaneBoardStore((s) => s.lanes);
  const tasks = useTaskCenterStore((s) => s.tasks);

  if (!delivery) {
    return null;
  }

  if (delivery.kind === 'lane') {
    const lane = lanes.find((l) => l.lane_id === delivery.laneId) ?? null;
    if (!lane) return null;
    return <LaneDetailDrawer lane={lane} open onClose={closeDelivery} />;
  }

  const ref = delivery.ref ?? tasks[delivery.entryId]?.deliveryRef;
  if (!ref) return null;
  return (
    <OfficeDeliveryDrawer
      entryId={delivery.entryId}
      workspacePath={ref.workspacePath}
      filePath={ref.filePath}
      formatSpec={ref.formatSpec}
      open
      onClose={closeDelivery}
    />
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
