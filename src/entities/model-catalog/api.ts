/**
 * Model Catalog API 客户端 (Task 6, 2026-09-15)
 *
 * 消费 backend.api.model_catalog_routes 提供的 REST 端点。
 * 与 manage-endpoints/api.ts 同样走 ``backendRequest`` 漏斗 — 经 Electron
 * IPC relay 转发到本地 FastAPI 后端。
 *
 * 约束:
 * - 浏览器不计算费用, 价格始终为字符串
 * - 409 由 backendRequest 抛出, 调用方处理 stale-revision 提示用户重确认
 * - 不在后端做价格优先级算法 — 完全信任后端 effective 端点
 */
import { backendRequest } from '../../shared/api/backendRequest';

import type {
  CatalogListResponse,
  EffectiveModel,
  OverridePatch,
  ProbeResult,
  SnapshotDiff,
  SnapshotMeta,
} from './types';

const BASE = '/api/v1/model-catalog';

interface ListModelsParams {
  limit?: number;
  offset?: number;
  endpointId?: string;
}

/**
 * 分页拉取 catalog 行 (GET /api/v1/model-catalog/models).
 *
 * 返回的 CandidateModel 都是 raw source-only entries;
 * 不要混淆 — 这是 catalog 的"源视图", 真正生效值用 getEffective。
 */
export async function listModels(params: ListModelsParams = {}): Promise<CatalogListResponse> {
  const qs = new URLSearchParams();
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.endpointId) qs.set('endpoint_id', params.endpointId);
  const path = qs.toString() ? `${BASE}/models?${qs.toString()}` : `${BASE}/models`;
  return backendRequest<CatalogListResponse>({ path, method: 'GET' });
}

/**
 * 端点 + 模型 解析后的 effective 值 (GET /api/v1/model-catalog/effective).
 *
 * 这是 catalog 的"语义视图": 后端按 user_override > service_probe >
 * imported_snapshot > builtin > unknown 优先级合并后返回。
 * UI 应优先使用 effective, 仅在管理 catalog 本身时才看 listModels。
 */
export async function getEffective(
  endpointId: string,
  modelId: string,
): Promise<EffectiveModel | null> {
  const qs = new URLSearchParams({ endpoint_id: endpointId, model_id: modelId });
  try {
    return await backendRequest<EffectiveModel>({
      path: `${BASE}/effective?${qs.toString()}`,
      method: 'GET',
    });
  } catch (err) {
    // 404 (无 catalog 项) 视为 null — 未收录, 让调用方走未知态
    if (err instanceof Error && /HTTP\s+404/.test(err.message)) {
      return null;
    }
    throw err;
  }
}

/**
 * 探测单个模型, 由后端读取 endpoint 配置并调用服务探测路径。
 *
 * 后端将结果持久化进 catalog_overrides (revision 递增);
 * UI 可立即重新拉 listModels / effective 看到新值。
 */
export async function probeModel(endpointId: string, modelId: string): Promise<ProbeResult> {
  return backendRequest<ProbeResult>({
    path: `${BASE}/probe`,
    method: 'POST',
    body: { endpoint_id: endpointId, model_id: modelId },
  });
}

/**
 * 写入用户 override (PUT /api/v1/model-catalog/overrides).
 *
 * 后端按 expected_revision 校验乐观锁, 不匹配抛 409 (调用方捕获后
 * 弹"该字段已被修改, 请重确认")。
 */
export async function setOverride(
  endpointId: string,
  modelId: string,
  patch: OverridePatch,
  expectedRevision = 0,
): Promise<{ revision: number }> {
  return backendRequest<{ revision: number }>({
    path: `${BASE}/overrides`,
    method: 'PUT',
    body: {
      endpoint_id: endpointId,
      model_id: modelId,
      patch,
      expected_revision: expectedRevision,
    },
  });
}

/**
 * 删除用户 override, 恢复继承 (DELETE /api/v1/model-catalog/overrides).
 *
 * 后端按 expected_revision 校验乐观锁, 不匹配抛 409.
 * 删除后 effective 值自动回退到下一优先级源.
 */
export async function deleteOverride(
  endpointId: string,
  modelId: string,
  expectedRevision: number,
): Promise<{ revision: number }> {
  const qs = new URLSearchParams({
    endpoint_id: endpointId,
    model_id: modelId,
    expected_revision: String(expectedRevision),
  });
  return backendRequest<{ revision: number }>({
    path: `${BASE}/overrides?${qs.toString()}`,
    method: 'DELETE',
  });
}

/**
 * 列出已 staged 的快照 (GET /api/v1/model-catalog/snapshots).
 */
export async function listSnapshots(): Promise<SnapshotMeta[]> {
  return backendRequest<SnapshotMeta[]>({ path: `${BASE}/snapshots`, method: 'GET' });
}

/**
 * 拉取快照的字段级差异 (GET /api/v1/model-catalog/snapshots/{id}/diff).
 *
 * 后端 diff 项已包含字段级分类 (new / updated / conflict / unchanged);
 * UI 仅做展示与多选, 不重复后端的合并逻辑。
 */
export async function getDiff(snapshotId: string): Promise<SnapshotDiff[]> {
  return backendRequest<SnapshotDiff[]>({
    path: `${BASE}/snapshots/${encodeURIComponent(snapshotId)}/diff`,
    method: 'GET',
  });
}

/**
 * 应用所选字段 (POST .../items/{item_id}/apply).
 *
 * 后端按 expected_revision 校验; 409 时调用方应重新拉 diff 并提示用户重确认。
 */
export async function apply(
  snapshotId: string,
  itemId: string,
  fields: string[],
  expectedRevision: number,
): Promise<{ status: 'applied' }> {
  return backendRequest<{ status: 'applied' }>({
    path: `${BASE}/snapshots/${encodeURIComponent(snapshotId)}/items/${encodeURIComponent(itemId)}/apply`,
    method: 'POST',
    body: { fields, expected_revision: expectedRevision },
  });
}

/**
 * 忽略单项 (POST .../items/{item_id}/ignore).
 */
export async function ignore(snapshotId: string, itemId: string): Promise<{ status: 'ignored' }> {
  return backendRequest<{ status: 'ignored' }>({
    path: `${BASE}/snapshots/${encodeURIComponent(snapshotId)}/items/${encodeURIComponent(itemId)}/ignore`,
    method: 'POST',
  });
}

/**
 * 导入快照 — 后端限制 10 MiB body, 由调用方负责截断 (前端假定传入已校验)。
 */
export async function importSnapshot(
  body: unknown,
): Promise<{ snapshot_id: string; count: number }> {
  return backendRequest<{ snapshot_id: string; count: number }>({
    path: `${BASE}/snapshots/import`,
    method: 'POST',
    body,
  });
}

/**
 * 同步 OpenRouter 公开模型目录 (POST /api/v1/model-catalog/sync/openrouter).
 *
 * 后端做 DNS 校验 + 10 MiB body cap + SSRF 防御;
 * 网络失败返回 502, 调用方捕获后展示"上游同步失败"。
 */
export async function syncOpenRouter(): Promise<{ snapshot_id: string | null; count: number }> {
  return backendRequest<{ snapshot_id: string | null; count: number }>({
    path: `${BASE}/sync/openrouter`,
    method: 'POST',
  });
}

/**
 * 导出快照为可移植 bundle (GET .../snapshots/{id}/export).
 */
export async function exportSnapshot(snapshotId: string): Promise<unknown> {
  return backendRequest<unknown>({
    path: `${BASE}/snapshots/${encodeURIComponent(snapshotId)}/export`,
    method: 'GET',
  });
}
