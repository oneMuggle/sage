import { describe, expect, it } from 'vitest';

import { demoInvoke, searchDemoMemories } from '../demoInterceptors';

describe('demo skill lifecycle state', () => {
  it('archive_skill excludes a skill from slash commands and restores its stale lifecycle', () => {
    const before = demoInvoke('list_slash_commands', {});
    expect(before.value).toEqual({
      commands: ['/office_create', '/schedule_task', '/memory_search'],
    });
    const archived = demoInvoke('archive_skill', { name: 'office_create', archived: true });

    expect(archived.value).toEqual(
      expect.objectContaining({
        name: 'office_create',
        enabled: true,
        lifecycle: 'archived',
      }),
    );
    expect(demoInvoke('list_slash_commands', {}).value).toEqual({
      commands: ['/schedule_task', '/memory_search'],
    });

    const restored = demoInvoke('archive_skill', { name: 'office_create', archived: false });
    expect(restored.value).toEqual(
      expect.objectContaining({
        name: 'office_create',
        enabled: true,
        lifecycle: 'stale',
      }),
    );
    expect(demoInvoke('list_slash_commands', {}).value).toEqual({
      commands: ['/office_create', '/schedule_task', '/memory_search'],
    });
  });
});

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
