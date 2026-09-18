/** Conservative staging evidence. Preview only: this module never removes files. */
import { lstat, open, readdir, realpath, writeFile } from 'node:fs/promises';
import path from 'node:path';

import type { OfficeStagingReport, OfficeStagingStatus } from '../src/shared/types/electron-api';

export const STAGING_MARKER = '.sage-import-v1.json';
export const COMPLETED_MARKER = '.sage-import-completed';
export const STAGING_REVIEW_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_ENTRIES = 1000;
const DOC_TYPES = ['ppt', 'word', 'excel', 'pdf'] as const;

interface ImportEvidence {
  version: 1;
  token: string;
  filename: string;
  createdAt: number;
  ownerPid: number;
}

/** Exclusive creation: existing metadata, including links, is never overwritten. */
export async function recordStagedImport(
  directory: string,
  token: string,
  filename: string,
): Promise<void> {
  const evidence: ImportEvidence = {
    version: 1,
    token,
    filename,
    createdAt: Date.now(),
    ownerPid: process.pid,
  };
  await writeFile(path.join(directory, STAGING_MARKER), JSON.stringify(evidence), {
    flag: 'wx',
    mode: 0o600,
  });
}

/** An immutable completion sentinel survives restart; failure must not trigger discard. */
export async function recordCompletedImport(directory: string): Promise<void> {
  try {
    await writeFile(path.join(directory, COMPLETED_MARKER), 'completed', {
      flag: 'wx',
      mode: 0o600,
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
  }
}

function ownerMayBeAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ESRCH';
  }
}

async function readEvidence(directory: string, token: string): Promise<ImportEvidence | null> {
  const marker = path.join(directory, STAGING_MARKER);
  const stat = await lstat(marker);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 4096) return null;
  const file = await open(marker, 'r');
  try {
    const buffer = Buffer.alloc(4097);
    const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 4096) return null;
    const data: unknown = JSON.parse(buffer.subarray(0, bytesRead).toString('utf8'));
    if (!data || typeof data !== 'object') return null;
    const e = data as Partial<ImportEvidence>;
    if (
      e.version !== 1 ||
      e.token !== token ||
      typeof e.filename !== 'string' ||
      path.basename(e.filename) !== e.filename ||
      !e.filename ||
      !Number.isSafeInteger(e.createdAt) ||
      (e.createdAt ?? -1) < 0 ||
      !Number.isSafeInteger(e.ownerPid) ||
      (e.ownerPid ?? 0) <= 0
    )
      return null;
    return e as ImportEvidence;
  } finally {
    await file.close();
  }
}

/** Missing/unknown/linked/unreadable paths are retained, never inferred orphaned.
 * A dead-owner, old import is ONLY a review candidate: backend commit may have
 * succeeded without the renderer sending complete-import. PID reuse retains it.
 */
export async function previewOfficeStaging(
  workspacePath: string,
  activeTokens: ReadonlySet<string> = new Set(),
  options: { now?: number; ownerAlive?: (pid: number) => boolean } = {},
): Promise<OfficeStagingReport> {
  if (!workspacePath || !path.isAbsolute(workspacePath))
    throw new Error('Absolute workspace path required');
  const root = await realpath(workspacePath);
  const report: OfficeStagingReport = { readOnly: true, items: [], truncated: false };
  const office = path.join(root, 'office');
  try {
    if ((await lstat(office)).isSymbolicLink()) return report;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return report;
    throw error;
  }
  const now = options.now ?? Date.now();
  for (const docType of DOC_TYPES) {
    const group = path.join(office, docType);
    let entries;
    try {
      if ((await lstat(group)).isSymbolicLink()) continue;
      entries = await readdir(group, { withFileTypes: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue;
      throw error;
    }
    for (const entry of entries) {
      if (report.items.length >= MAX_ENTRIES) {
        report.truncated = true;
        return report;
      }
      if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
      let status: OfficeStagingStatus = 'untracked';
      let createdAt: number | undefined;
      const directory = path.join(group, entry.name);
      try {
        if (
          !entry.isSymbolicLink() &&
          !(await lstat(directory)).isSymbolicLink() &&
          path.dirname(await realpath(directory)) === (await realpath(group))
        ) {
          let completed = false;
          try {
            await lstat(path.join(directory, COMPLETED_MARKER));
            completed = true;
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
          }
          if (completed) status = 'completed';
          else if (activeTokens.has(entry.name)) status = 'active';
          else {
            const evidence = await readEvidence(directory, entry.name);
            if (evidence) {
              createdAt = evidence.createdAt;
              if ((options.ownerAlive ?? ownerMayBeAlive)(evidence.ownerPid)) status = 'active';
              else if (now - createdAt < STAGING_REVIEW_AGE_MS) status = 'recent';
              else status = 'review';
            }
          }
        }
      } catch (error) {
        status = (error as NodeJS.ErrnoException).code === 'ENOENT' ? 'untracked' : 'unreadable';
      }
      report.items.push({
        documentId: entry.name,
        docType,
        status,
        ...(createdAt === undefined ? {} : { createdAt }),
      });
    }
  }
  return report;
}
