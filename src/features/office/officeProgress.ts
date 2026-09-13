// src/features/office/officeProgress.ts
//
// P7 (2026-09-14): office 长任务进度轮询。后端在生成/导出的阶段边界
// 写入进程内进度注册表（backend/office/progress.py），前端以 500ms
// 间隔经 IPC 桥轮询 GET /api/v1/office/progress/{task_id}，把阶段与
// 百分比喂给全局任务中心。active=false（任务结束）自动停止。

import { officeApi } from '../../shared/api/officeApi';

export interface OfficeProgressTick {
  stage: string | null;
  percent: number | null;
}

/** 轮询进度；返回 stop()。onTick 只在任务活跃时回调。 */
export function pollOfficeProgress(
  taskId: string,
  onTick: (tick: OfficeProgressTick) => void,
): () => void {
  const state = { stopped: false };

  const tick = async (): Promise<void> => {
    if (state.stopped) return;
    try {
      const p = await officeApi.getOfficeProgress(taskId);
      if (state.stopped) return;
      if (!p.active) {
        state.stopped = true;
        return;
      }
      onTick({ stage: p.stage, percent: p.percent });
    } catch {
      // 单次轮询失败（后端重启/网络抖动）静默——下一 tick 继续
    }
  };

  void tick();
  const timer = setInterval(tick, 500);
  return () => {
    state.stopped = true;
    clearInterval(timer);
  };
}
