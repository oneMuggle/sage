import { describe, expect, it } from 'vitest';

import { demoInvoke, searchDemoMemories } from '../demoInterceptors';

describe('demo memory state', () => {
  it('makes saved memories searchable and removes them after deletion', () => {
    const marker = `demo-memory-${crypto.randomUUID()}`;
    const saved = demoInvoke('save_memory', {
      content: marker,
      memoryType: 'semantic',
      tags: ['demo-test'],
    });

    expect(saved.hit).toBe(true);
    const savedMemory = saved.value as { id: string };
    expect(searchDemoMemories(marker)).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: savedMemory.id })]),
    );

    expect(demoInvoke('delete_memory', { id: savedMemory.id })).toEqual({
      hit: true,
      value: { ok: true },
    });
    expect(searchDemoMemories(marker)).toEqual([]);
  });
});
