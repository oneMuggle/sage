/**
 * M4.2 (2026-11-23): canonical run 目录 store —— 统一运行视图的真相层投影。
 *
 * 数据源：``GET /api/v1/orch/runs/directory?scope=all``（跨会话 orch_runs +
 * orch_tasks 批量快照）。此前 TaskCenter 的子任务行只来自渲染进程内存
 * ``chatStreamStore.taskBoard``：会话从未在本窗口加载过时 run 不可见。
 * 本 store 由 ``TaskCenterRuntimeHost`` 每 3s 轮询，作为 canonical 侧输入，
 * 由 ``useUnifiedTasks`` 与内存条目合并（canonical 定状态、内存补实时细节）。
 */
import { create } from 'zustand';

import { orchRunClient, type DirectoryRun } from '../../shared/api/orchRunClient';

/** 目录一次最多覆盖 50 个 run；与任务中心全量视图的规模假设一致。 */
export const RUN_DIRECTORY_LIMIT = 50;

interface RunDirectoryState {
  runs: DirectoryRun[];
  /** 后端生成快照的时刻（epoch ms）；未拉取过为 null。 */
  generatedAt: number | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export const useRunDirectoryStore = create<RunDirectoryState>((set, get) => ({
  runs: [],
  generatedAt: null,
  loading: false,
  error: null,

  async refresh() {
    // 并发保护：轮询与首屏刷新重叠时不重复发请求
    if (get().loading) return;
    set({ loading: true });
    try {
      const resp = await orchRunClient.listRunDirectory('all', RUN_DIRECTORY_LIMIT);
      set({
        runs: resp.runs,
        generatedAt: resp.generated_at,
        loading: false,
        error: null,
      });
    } catch (err) {
      // 任务中心是增强视图：保留上一轮数据，仅记录错误
      set({
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  },
}));

/**
 * 会话的活跃 run（running，新→旧取第一条）。后端按 created_at DESC 返回，
 * 右栏进度在内存 taskBoard 缺失时用其合成兜底任务板。
 */
export function findActiveRunForSession(
  runs: readonly DirectoryRun[],
  sessionId: string | null | undefined,
): DirectoryRun | null {
  if (!sessionId) return null;
  return runs.find((r) => r.session_id === sessionId && r.status === 'running') ?? null;
}
