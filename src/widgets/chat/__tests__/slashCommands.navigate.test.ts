import { describe, expect, it } from 'vitest';

import { filterCommands, getCommand, slashCommands } from '../slashCommands';

describe('slashCommands — navigate mode (S3)', () => {
  it('defines the five page-direct commands with routes', () => {
    const expected: Record<string, string> = {
      office: '/office',
      journal: '/office',
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
