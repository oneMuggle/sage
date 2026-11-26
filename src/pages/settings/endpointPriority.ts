import type { EndpointConfig } from '../../entities/setting/types';

/**
 * 2026-11-26: 上移/下移端点并重排优先级（1..N）。
 *
 * 纯函数：越界时仅把现有 priority 归一化为 1..N，不改变顺序。
 */
export function moveEndpoint(
  endpoints: EndpointConfig[],
  index: number,
  direction: -1 | 1,
): EndpointConfig[] {
  const target = index + direction;
  const renumber = (list: EndpointConfig[]) =>
    list.map((ep, i) => ({ ...ep, priority: i + 1 }));
  if (index < 0 || index >= endpoints.length || target < 0 || target >= endpoints.length) {
    return renumber(endpoints);
  }
  const next = [...endpoints];
  const moved = next[index];
  next[index] = next[target];
  next[target] = moved;
  return renumber(next);
}
