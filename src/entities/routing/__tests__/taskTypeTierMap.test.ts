// src/entities/routing/__tests__/taskTypeTierMap.test.ts
//
// Task 11 (2026-10-28) 智能路由：设置页只读映射表的**防漂移**守卫。
//
// 映射的源在服务端 —— 本测试直接读 backend/routing/routing_engine.py 的
// `TASK_TYPE_TO_TIER` 字典并与前端副本比对。抽取失败（格式变了 / 文件没了）
// 必须显式抛错，绝不静默跳过：静默跳过会让漂移永久隐身。

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { ROUTING_TASK_TYPES } from '../taskType';
import { TASK_TYPE_LABELS, TASK_TYPE_TIER_MAP, TIER_LABELS } from '../taskTypeTierMap';

const ROUTING_ENGINE_PATH = resolve(process.cwd(), 'backend/routing/routing_engine.py');

/**
 * 从 Python 源码里抽出 `TASK_TYPE_TO_TIER: Dict[str, str] = { "k": "v", ... }`。
 *
 * 任一环节解析不出东西都直接抛错 —— 这是防漂移测试，宁可红也不能假绿。
 */
function parseBackendTaskTypeToTier(): Record<string, string> {
  const source = readFileSync(ROUTING_ENGINE_PATH, 'utf-8');
  const block = source.match(/TASK_TYPE_TO_TIER\s*(?::[^=\n]*)?=\s*\{([\s\S]*?)\}/);
  if (!block) {
    throw new Error(
      `未能在 ${ROUTING_ENGINE_PATH} 中定位 TASK_TYPE_TO_TIER 字典 —— 防漂移测试失效`,
    );
  }

  const parsed: Record<string, string> = {};
  for (const pair of block[1].matchAll(/"([^"]+)"\s*:\s*"([^"]+)"/g)) {
    parsed[pair[1]] = pair[2];
  }
  if (Object.keys(parsed).length === 0) {
    throw new Error('TASK_TYPE_TO_TIER 块内未解析出任何键值对 —— 防漂移测试失效');
  }
  return parsed;
}

describe('taskTypeTierMap', () => {
  it('covers all nine task types with a legal tier', () => {
    expect(Object.keys(TASK_TYPE_TIER_MAP)).toHaveLength(9);
    for (const tier of Object.values(TASK_TYPE_TIER_MAP)) {
      expect(['fast', 'balanced', 'powerful']).toContain(tier);
    }
  });

  it('keeps the exact same key set as ROUTING_TASK_TYPES', () => {
    expect(Object.keys(TASK_TYPE_TIER_MAP).sort()).toEqual([...ROUTING_TASK_TYPES].sort());
  });

  it('does not drift from backend TASK_TYPE_TO_TIER', () => {
    expect(parseBackendTaskTypeToTier()).toEqual(TASK_TYPE_TIER_MAP);
  });

  it('provides a non-empty Chinese label for every task type and tier', () => {
    for (const taskType of ROUTING_TASK_TYPES) {
      expect(TASK_TYPE_LABELS[taskType].length).toBeGreaterThan(0);
    }
    expect(Object.keys(TIER_LABELS).sort()).toEqual(['balanced', 'fast', 'powerful']);
    for (const label of Object.values(TIER_LABELS)) {
      expect(label.length).toBeGreaterThan(0);
    }
  });
});
