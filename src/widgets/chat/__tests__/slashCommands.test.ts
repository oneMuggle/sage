/**
 * Tests for Path B + Path C: mergeSlashCommands merges static slash commands
 * with dynamically-loaded SKILL.md skill metadata. SKILL.md commands (dynamic)
 * take priority on name collision; static commands that share a name with a
 * SKILL.md command are dropped (the SKILL.md skill is authoritative for that
 * name). Real SKILL.md descriptions are passed through to the menu (truncated
 * to ~80 chars to keep the menu compact).
 */
import { describe, expect, it } from 'vitest';

import { mergeSlashCommands, slashCommands } from '../slashCommands';

describe('mergeSlashCommands', () => {
  it('returns the 6 static commands unchanged when dynamic list is empty', () => {
    const result = mergeSlashCommands([]);
    // Static set has 6 entries; merge with nothing must be a no-op.
    expect(result).toHaveLength(slashCommands.length);
    expect(result.map((c) => c.name)).toEqual(slashCommands.map((c) => c.name));
  });

  it('prepends a SKILL.md-style command and preserves static commands', () => {
    const result = mergeSlashCommands([
      { commandName: '/aihot', description: 'AI HOT 资讯查询' },
    ]);
    const names = result.map((c) => c.name);
    // Dynamic SKILL.md entry comes first; static /search through /compact still present.
    expect(names[0]).toBe('aihot');
    expect(result[0].mode).toBe('skill');
    expect(result[0].skillName).toBe('aihot');
    expect(result[0].label).toBe('/aihot');
    expect(result[0].description).toBe('AI HOT 资讯查询');
    // Static set follows in order.
    expect(names).toEqual(
      expect.arrayContaining(['help', 'clear', 'search', 'summarize', 'translate', 'compact']),
    );
  });

  it('does NOT duplicate on collision (SKILL.md wins, static is dropped)', () => {
    // Backend returns "/search" (a SKILL.md skill with the same name as the
    // static command). Per design, the dynamic SKILL.md command wins because
    // the user explicitly loaded that skill from disk.
    const result = mergeSlashCommands([
      { commandName: '/search', description: 'Custom search' },
    ]);
    const searchEntries = result.filter((c) => c.name === 'search');
    expect(searchEntries).toHaveLength(1);
    expect(searchEntries[0].mode).toBe('skill');
    expect(searchEntries[0].skillName).toBe('search');
    expect(searchEntries[0].description).toBe('Custom search');
    // Total length: 1 dynamic (search) + 5 remaining static (search dropped).
    expect(result).toHaveLength(slashCommands.length); // 6 = 1 dynamic (search) + 5 static
  });

  it('strips multiple leading slashes correctly', () => {
    const result = mergeSlashCommands([
      { commandName: '//foo', description: 'foo skill' },
      { commandName: '/bar', description: 'bar skill' },
    ]);
    const names = result.map((c) => c.name);
    expect(names).toContain('foo');
    expect(names).toContain('bar');
    expect(result.find((c) => c.name === 'foo')).toBeDefined();
    expect(result.find((c) => c.name === 'bar')?.label).toBe('/bar');
  });

  it('passes through real description (truncated to ~80 chars)', () => {
    const longDesc =
      'AI HOT (aihot.virxact.com) 中文 AI 资讯查询 Skill. 当用户想知道"今天 AI 圈有什么"、"AI 日报"、"AI HOT"、"AI 资讯"、"AI 热点" 等任何中文 AI 资讯查询时使用。';
    const result = mergeSlashCommands([{ commandName: '/aihot', description: longDesc }]);
    const aihot = result.find((c) => c.name === 'aihot');
    expect(aihot).toBeDefined();
    // Description is truncated to <= 80 chars
    expect(aihot!.description.length).toBeLessThanOrEqual(80);
    // Ends with ellipsis if truncated
    expect(aihot!.description.endsWith('…')).toBe(true);
  });

  it('keeps short description as-is', () => {
    const result = mergeSlashCommands([
      { commandName: '/short', description: 'Brief' },
    ]);
    expect(result[0].description).toBe('Brief');
  });
});
