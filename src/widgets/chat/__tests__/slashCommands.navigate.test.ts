import { describe, expect, it } from 'vitest';

import { filterCommands, getCommand, slashCommands } from '../slashCommands';

describe('slashCommands — navigate mode (S3)', () => {
  it('defines the five page-direct commands with routes', () => {
    const expected: Record<string, string> = {
      // 2026-11 IA restructure: /office 的子分区用 URL query 表达，
      // /journal 落到「文档生成」tab（JournalPanel 收在该 tab 的折叠区）。
      office: '/office?tab=documents',
      journal: '/office?tab=generate',
      schedule: '/scheduled',
      wiki: '/knowledge',
      memory: '/memory',
    };
    for (const [name, route] of Object.entries(expected)) {
      const cmd = getCommand(name);
      expect(cmd?.mode).toBe('navigate');
      expect(cmd?.route).toBe(route);
    }
  });

  it('is discoverable via filterCommands', () => {
    expect(filterCommands('sched').map((c) => c.name)).toContain('schedule');
    expect(filterCommands('wiki').map((c) => c.name)).toContain('wiki');
  });

  it('keeps command names unique', () => {
    const names = slashCommands.map((c) => c.name);
    expect(new Set(names).size).toBe(names.length);
  });
});
