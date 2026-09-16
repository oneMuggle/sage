// @vitest-environment node
import { mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  COMPLETED_MARKER,
  previewOfficeStaging,
  recordCompletedImport,
  recordStagedImport,
  STAGING_MARKER,
  STAGING_REVIEW_AGE_MS,
} from '../officeStaging';

let root: string;
beforeEach(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), 'sage-staging-'));
});
afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});
async function entry(token: string) {
  const dir = path.join(root, 'office', 'word', token);
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, 'document.docx'), 'KEEP');
  return dir;
}

async function oldImport(token: string) {
  const dir = await entry(token);
  await writeFile(
    path.join(dir, STAGING_MARKER),
    JSON.stringify({
      version: 1,
      token,
      filename: 'document.docx',
      createdAt: 1,
      ownerPid: 12345,
    }),
  );
  return dir;
}

describe('read-only staging evidence', () => {
  it('retains unknown/formal directories and never deletes an old review candidate', async () => {
    const unknown = await entry('formal-document');
    const old = await oldImport('old');
    const report = await previewOfficeStaging(root, new Set(), {
      now: STAGING_REVIEW_AGE_MS + 2,
      ownerAlive: () => false,
    });
    expect(report.readOnly).toBe(true);
    expect(report.items.find((i) => i.documentId === 'formal-document')?.status).toBe('untracked');
    expect(report.items.find((i) => i.documentId === 'old')?.status).toBe('review');
    expect(await readFile(path.join(unknown, 'document.docx'), 'utf8')).toBe('KEEP');
    expect(await readFile(path.join(old, 'document.docx'), 'utf8')).toBe('KEEP');
    expect(await readdir(unknown)).toEqual(['document.docx']);
  });

  it('retains active in-process imports, live owners and completed imports after restart', async () => {
    await oldImport('pending');
    await oldImport('live');
    const completed = await oldImport('completed');
    await recordCompletedImport(completed);
    await recordCompletedImport(completed);
    let report = await previewOfficeStaging(root, new Set(['pending']), {
      now: STAGING_REVIEW_AGE_MS + 2,
      ownerAlive: () => false,
    });
    expect(report.items.find((i) => i.documentId === 'pending')?.status).toBe('active');
    expect(report.items.find((i) => i.documentId === 'completed')?.status).toBe('completed');
    report = await previewOfficeStaging(root, new Set(), {
      now: STAGING_REVIEW_AGE_MS + 2,
      ownerAlive: () => true,
    });
    expect(report.items.find((i) => i.documentId === 'live')?.status).toBe('active');
    expect(await readFile(path.join(completed, COMPLETED_MARKER), 'utf8')).toBe('completed');
  });

  it('records exclusive ownership metadata without changing the imported file', async () => {
    const dir = await entry('new');
    await recordStagedImport(dir, 'new', 'document.docx');
    await expect(recordStagedImport(dir, 'other', 'document.docx')).rejects.toThrow();
    const evidence = JSON.parse(await readFile(path.join(dir, STAGING_MARKER), 'utf8'));
    expect(evidence.ownerPid).toBe(process.pid);
    expect(evidence.token).toBe('new');
    const report = await previewOfficeStaging(root, new Set(), { ownerAlive: () => false });
    expect(report.items[0].status).toBe('recent');
  });

  it('does not follow links outside the workspace', async () => {
    const outside = await mkdtemp(path.join(os.tmpdir(), 'sage-staging-outside-'));
    try {
      await writeFile(path.join(outside, 'KEEP'), 'safe');
      await mkdir(path.join(root, 'office', 'word'), { recursive: true });
      await symlink(outside, path.join(root, 'office', 'word', 'link'), 'junction');
      const report = await previewOfficeStaging(root);
      expect(report.items[0].status).toBe('untracked');
      expect(await readdir(outside)).toEqual(['KEEP']);
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it('retains malformed, wrong-token and oversized metadata', async () => {
    for (const [id, content] of [
      ['bad', '{'],
      ['large', 'x'.repeat(5000)],
      ['wrong', JSON.stringify({ version: 1, token: 'other' })],
    ]) {
      const dir = await entry(id);
      await writeFile(path.join(dir, STAGING_MARKER), content);
    }
    const report = await previewOfficeStaging(root, new Set(), { ownerAlive: () => false });
    expect(report.items.every((i) => ['untracked', 'unreadable'].includes(i.status))).toBe(true);
    expect(report.items).toHaveLength(3);
  });

  it('an empty workspace remains empty, and a relative root is rejected', async () => {
    expect((await previewOfficeStaging(root)).items).toEqual([]);
    expect(await readdir(root)).toEqual([]);
    await expect(previewOfficeStaging('.')).rejects.toThrow('Absolute workspace');
  });
});
