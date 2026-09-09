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

describe('demo office update preview + export (parity batch 2)', () => {
  it('office_update_preview turns each composed op into a change entry', () => {
    const res = demoInvoke('office_update_preview', {
      ops: [
        { op: 'replace_text', find: '大模型', replace: 'LLM' },
        { op: 'set_cells', sheet: 'Sheet1', cells: [{ addr: 'B2', value: '10' }] },
        { op: 'set_slide_title', index: 2, title: '新标题' },
        { op: 'freeze_panes', sheet: 'Sheet1', cell: 'B2' },
      ],
    });

    expect(res.hit).toBe(true);
    const value = res.value as {
      ok: boolean;
      truncated: boolean;
      changes: { op: string; target?: string; before?: string; after?: string }[];
    };
    expect(value.ok).toBe(true);
    expect(value.truncated).toBe(false);
    expect(value.changes).toHaveLength(4);
    expect(value.changes[0]).toMatchObject({ op: 'replace_text', before: '大模型', after: 'LLM' });
    expect(value.changes[1]).toMatchObject({ op: 'set_cells', target: 'Sheet1!B2', after: '10' });
    expect(value.changes[2]).toMatchObject({ op: 'set_slide_title', target: 'slide[2]' });
    // Unknown op shapes fall through to a generic summary entry.
    expect(value.changes[3]).toMatchObject({ op: 'freeze_panes' });
  });

  it('office_update_preview caps the demo change list at 200 and flags truncation', () => {
    const ops = Array.from({ length: 260 }, (_, i) => ({ op: 'replace_text', find: `f${i}`, replace: 'x' }));
    const res = demoInvoke('office_update_preview', { ops });
    const value = res.value as { truncated: boolean; changes: unknown[] };
    expect(value.truncated).toBe(true);
    expect(value.changes).toHaveLength(200);
  });

  it('office_export_pdf derives <stem>.pdf next to the source', () => {
    const res = demoInvoke('office_export_pdf', {
      filePath: '/ws/office/word/of-1/report.docx',
    });
    expect(res.hit).toBe(true);
    expect(res.value).toMatchObject({
      ok: true,
      method: 'libreoffice',
      output_path: '/ws/office/word/of-1/report.pdf',
    });
  });
});
