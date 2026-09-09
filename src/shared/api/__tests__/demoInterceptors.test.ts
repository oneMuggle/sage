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

describe('demo office doc update apply (parity round 2, R1)', () => {
  it('office_doc_update echoes ok + self_check and marks the demo row edited', () => {
    const before = demoInvoke('office_list_documents', {}).value as {
      documents: Array<{ id: string; updated_at: number; status: string }>;
    };
    const target = before.documents.find((d) => d.id === 'of-1')!;
    // demoOfficeDocs rows are shared object references — snapshot the
    // primitive, otherwise the mutation below "updates" the baseline too.
    const updatedAtBefore = target.updated_at;

    const res = demoInvoke('office_doc_update', {
      docId: 'of-1',
      ops: [{ op: 'replace_text', find: '大模型', replace: 'LLM' }],
    });

    expect(res.hit).toBe(true);
    const value = res.value as {
      ok: boolean;
      summary: { id: string; status: string; updated_at: number };
      self_check: { ok: boolean; summary?: Record<string, unknown>; error?: string | null };
    };
    expect(value.ok).toBe(true);
    expect(value.summary.id).toBe('of-1');
    // Apply mutates the demo row: status → edited, updated_at refreshed.
    expect(value.summary.status).toBe('edited');
    expect(value.summary.updated_at).toBeGreaterThan(updatedAtBefore);
    // Self-check echoes a plausible re-read report.
    expect(value.self_check.ok).toBe(true);
    expect(value.self_check.summary).toMatchObject({ ops_applied: 1, re_read: true });
  });

  it('office_doc_update counts the forwarded ops in self_check', () => {
    const res = demoInvoke('office_doc_update', {
      docId: 'of-2',
      ops: [
        { op: 'set_cells', sheet: 'Sheet1', cells: [{ addr: 'B2', value: '10' }] },
        { op: 'set_cells', sheet: 'Sheet1', cells: [{ addr: 'B3', value: '11' }] },
      ],
    });
    const value = res.value as {
      summary: { id: string };
      self_check: { summary?: Record<string, unknown> };
    };
    expect(value.summary.id).toBe('of-2');
    expect(value.self_check.summary).toMatchObject({ ops_applied: 2 });
  });
});

describe('demo office template library (parity batch 3, item 3.2; round-3 N2)', () => {
  it('office_list_templates returns builtin templates covering word/excel/ppt', () => {
    const res = demoInvoke('office_list_templates', { workspacePath: '/ws' });
    expect(res.hit).toBe(true);
    const value = res.value as { templates: Array<Record<string, unknown>> };
    // Round-3 N2: 2 word + 1 excel + 1 ppt builtin entries.
    expect(value.templates).toHaveLength(4);
    expect(value.templates.map((tpl) => tpl.doc_type).sort()).toEqual([
      'excel',
      'ppt',
      'word',
      'word',
    ]);
    for (const tpl of value.templates) {
      expect(tpl).toMatchObject({ source: 'builtin' });
      expect(typeof tpl.id).toBe('string');
      expect(Array.isArray(tpl.placeholders)).toBe(true);
    }
  });

  it('office_templates_instantiate persists a word doc row and returns the fill-template shape', () => {
    const before = demoInvoke('office_list_documents', {}).value as { documents: unknown[] };
    const res = demoInvoke('office_templates_instantiate', {
      workspacePath: '/ws',
      templateId: 'weekly_report',
      filename: '周报模板-2026-09-10.docx',
      data: { author: '张三', report_date: '', logo: '' },
    });
    expect(res.hit).toBe(true);
    expect(res.value).toMatchObject({
      output_path: '/ws/周报模板-2026-09-10.docx',
      filename: '周报模板-2026-09-10.docx',
      file_size_bytes: expect.any(Number),
      filled_count: 1,
      unfilled_placeholders: [],
    });
    const after = demoInvoke('office_list_documents', {}).value as { documents: Array<Record<string, unknown>>; total: number };
    expect(after.total).toBe(before.documents.length + 1);
    expect(after.documents[0]).toMatchObject({
      doc_type: 'word',
      status: 'generated',
      generated_filename: '周报模板-2026-09-10.docx',
    });
  });

  it('office_templates_instantiate infers doc_type from the output extension (round-3 N2)', () => {
    const res = demoInvoke('office_templates_instantiate', {
      workspacePath: '/ws',
      templateId: 'project_review',
      filename: '项目评审模板-2026-09-10.pptx',
      data: { project: 'Atlas' },
    });
    expect(res.hit).toBe(true);
    const after = demoInvoke('office_list_documents', {}).value as {
      documents: Array<Record<string, unknown>>;
    };
    expect(after.documents[0]).toMatchObject({
      doc_type: 'ppt',
      status: 'generated',
      generated_filename: '项目评审模板-2026-09-10.pptx',
    });
  });
});
