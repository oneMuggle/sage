/**
 * T2026-09-24: Backend startup diagnostic collector.
 *
 * When Sage fails to launch on Windows 7 (or any platform), we want a single
 * self-contained plain-text file the user can paste into a GitHub issue.
 *
 * Sections:
 *   1. Provenance  — build-manifest (buildId, commit, branch, version,
 *                    packagingMode, electronVersion, pythonVersion)
 *   2. Platform    — arch, platform, os.release(), isPackaged, app version
 *   3. Plan        — last broken-installer reason / last spawn reason
 *   4. Resources   — resourcesPath tree: bundled python, sage-core, git-bash
 *   5. Env         — relevant SAGE_/PYTHONPATH/NODE env at spawn
 *   6. Process     — backendProc pid/exitCode/signalCode + currentBackend
 *   7. Stderr      — last ~64 KiB captured from proc.stderr via recordBackendStderr()
 *   8. Log tail    — last 100 lines of today's ndjson log
 *   9. Win7 hint   — KB3033929 / SHA-2 advisory (only on Win7)
 *
 * The file is written to `${userData}/diagnostic-YYYYMMDD-HHMMSS[-NN].log`,
 * NEVER to the bundled resources (which are read-only on Program Files).
 *
 * CRITICAL: this module MUST never throw out of `collectAndWriteDiagnostic`.
 * The dialog chain calling it relies on a returned path; failure must fall
 * back to a log entry only.
 */

import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { app } from 'electron';

import { logger } from './logger';
import { getLogDir, getCurrentLogFile } from './logPaths';
import type { BuildManifest } from './buildManifest';

const MAX_STDERR_BUFFER_BYTES = 64 * 1024;
const LOG_TAIL_BYTES = 32 * 1024;

// Rolling ring buffer of the most recent stderr text. ringLen is the number
// of valid bytes at the start of `ring`. When (ringLen + incoming) > capacity
// we shift-left (sliding window). When incoming alone exceeds capacity we
// keep only the tail.
let ring: Buffer = Buffer.alloc(MAX_STDERR_BUFFER_BYTES);
let ringLen = 0;

export function recordBackendStderr(text: string): void {
  if (!text) return;
  const incoming = Buffer.from(text, 'utf8');
  if (incoming.length >= MAX_STDERR_BUFFER_BYTES) {
    ring = incoming.subarray(incoming.length - MAX_STDERR_BUFFER_BYTES);
    ringLen = MAX_STDERR_BUFFER_BYTES;
    return;
  }
  if (ringLen + incoming.length > MAX_STDERR_BUFFER_BYTES) {
    const overflow = ringLen + incoming.length - MAX_STDERR_BUFFER_BYTES;
    ring.copy(ring, 0, overflow, ringLen);
    ringLen -= overflow;
  }
  incoming.copy(ring, ringLen);
  ringLen += incoming.length;
}

function readStderrTail(): string {
  return ring.subarray(0, ringLen).toString('utf8');
}

function timestamp(d: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
  );
}

async function choosePath(userData: string): Promise<string> {
  await mkdir(userData, { recursive: true });
  const base = join(userData, `diagnostic-${timestamp()}.log`);
  for (let i = 0; i < 50; i++) {
    const candidate = i === 0 ? base : base.replace(/\.log$/, `-${i}.log`);
    if (!existsSync(candidate)) return candidate;
  }
  return base;
}

export interface BackendPlanSummary {
  kind: 'spawn' | 'broken-installer';
  reason: string;
  command?: string;
  args?: string[];
  title?: string;
}

export interface BackendProcSummary {
  pid: number | null;
  exitCode: number | null;
  signalCode: NodeJS.Signals | null;
  generation: number | null;
  ownershipToken: string | null;
}

export interface DiagnosticSnapshot {
  manifest: BuildManifest;
  plan: BackendPlanSummary | null;
  proc: BackendProcSummary | null;
  reason: string;
  detail?: string;
}

let lastPlan: BackendPlanSummary | null = null;
export function recordLastPlan(plan: BackendPlanSummary): void {
  lastPlan = plan;
}

function buildResourcesSection(resourcesPath: string | undefined): string[] {
  if (!resourcesPath) return ['  (process.resourcesPath is empty)'];
  const lines: string[] = [`  resourcesPath: ${resourcesPath}`];
  const probe = (rel: string) => {
    const full = join(resourcesPath, rel);
    lines.push(`  ${existsSync(full) ? '✓' : '✗'} ${rel}`);
  };
  probe('python');
  probe(process.platform === 'win32' ? 'python/python.exe' : 'python/bin/python3');
  probe('python/_pth_config');
  probe('backend');
  probe('backend/main.py');
  probe('sage-core');
  probe(process.platform === 'win32' ? 'tools/git-bash/bin/bash.exe' : 'tools/git-bash/bin/bash');
  probe('build-manifest.json');
  return lines;
}

function buildEnvSection(): string[] {
  const keys = [
    'SAGE_BUILD_ID',
    'SAGE_BUILD_VERSION',
    'SAGE_BUILD_BRANCH',
    'SAGE_PROTECT_CODE',
    'SAGE_RUNTIME_PYTHON',
    'SAGE_DB_PATH',
    'SAGE_USER_DATA_DIR',
    'SAGE_LOG_DIR',
    'SAGE_LOG_LEVEL',
    'SAGE_LOG_TIMEZONE',
    'SAGE_SKIP_BACKEND',
    'PYTHONPATH',
    'PYTHON_BACKEND_PORT',
    'NODE_ENV',
  ];
  const lines: string[] = [];
  for (const k of keys) {
    const v = process.env[k];
    if (v === undefined) {
      lines.push(`  ${k}: <unset>`);
      continue;
    }
    if (k === 'SAGE_LOCAL_AUTH_TOKEN') {
      lines.push(`  ${k}=<redacted len=${v.length}>`);
      continue;
    }
    lines.push(`  ${k}=${v}`);
  }
  return lines;
}

function buildLogTailSection(): string[] {
  const logFile = getCurrentLogFile();
  if (!existsSync(logFile)) return ['  (no log file yet)'];
  try {
    const buf = readFileSync(logFile);
    const tail = buf.length > LOG_TAIL_BYTES ? buf.subarray(buf.length - LOG_TAIL_BYTES) : buf;
    const text = tail.toString('utf8');
    const lines = text.split(/\r?\n/);
    if (lines.length > 100) lines.splice(0, lines.length - 100);
    return ['  ' + logFile, ...lines.map((l) => '  | ' + l)];
  } catch (err) {
    return [`  (failed to read log file: ${String(err)})`];
  }
}

function buildWin7Hint(platform: NodeJS.Platform, osRelease: string): string[] {
  if (platform !== 'win32') return [];
  if (!/Windows 7|Windows Server 2008/i.test(osRelease)) return [];
  return [
    '',
    '## Win7 Hint',
    '',
    '- 此机器是 Windows 7 SP1 x64。Sage Win7 LTS 需要安装 KB3033929（SHA-2 代码签名支持）。',
    '- 如果 Sage.exe 启动后立即退出，或弹出 "缺失 api-ms-win-*" 错误，请先安装 KB3033929。',
    '- 内网 / 离线机器：从 https://catalog.s.download.windowsupdate.com 下载 KB3033929 后双击安装。',
    '- Sage 内置 installer 已是源码版（packagingMode=source），与历史 alpha.45 行为一致；如仍失败，',
    '  请改用 alpha.45 备份安装包并附此 diagnostic 文件到 GitHub issue。',
  ];
}

function render(snapshot: DiagnosticSnapshot): string {
  const osRelease = require('node:os').release();
  const arch = require('node:os').arch();
  const userData = app.getPath('userData');
  const logDir = getLogDir();

  const m = snapshot.manifest;
  const sections: string[] = [];

  sections.push('# Sage 启动诊断报告');
  sections.push('');
  sections.push(`Generated: ${new Date().toISOString()}`);
  sections.push(`Reason:    ${snapshot.reason}`);
  if (snapshot.detail) {
    sections.push('Detail:');
    sections.push(`  ${snapshot.detail.replace(/\n/g, '\n  ')}`);
  }
  sections.push('');

  sections.push('## 1. Provenance');
  sections.push('');
  sections.push(`  buildId:          ${m.buildId}`);
  sections.push(`  commit:           ${m.commit}`);
  sections.push(`  branch:           ${m.branch}`);
  sections.push(`  version:          ${m.version}`);
  sections.push(
    `  packagingMode:    ${m.packagingMode ?? 'unknown'}  (source=源码版(推荐), cython=Cython 实验版, unknown=无此字段)`,
  );
  sections.push(`  electronVersion:  ${m.electronVersion}`);
  sections.push(`  pythonVersion:    ${m.pythonVersion}`);
  sections.push(`  manifestVersion:  ${m.manifestVersion}`);
  sections.push('');

  sections.push('## 2. Platform');
  sections.push('');
  sections.push(`  platform:    ${process.platform}`);
  sections.push(`  arch:        ${arch}`);
  sections.push(`  os.release:  ${osRelease}`);
  sections.push(`  isPackaged:  ${app.isPackaged}`);
  sections.push(
    `  app version: ${typeof app.getVersion === 'function' ? app.getVersion() : 'unknown'}`,
  );
  sections.push(`  userData:    ${userData}`);
  sections.push(`  logDir:      ${logDir}`);
  sections.push('');

  sections.push('## 3. Plan');
  sections.push('');
  if (snapshot.plan) {
    sections.push(`  kind:    ${snapshot.plan.kind}`);
    sections.push(`  reason:  ${snapshot.plan.reason}`);
    if (snapshot.plan.kind === 'broken-installer') {
      sections.push(`  title:   ${snapshot.plan.title ?? ''}`);
    } else if (snapshot.plan.kind === 'spawn') {
      sections.push(`  command: ${snapshot.plan.command ?? ''}`);
      sections.push(`  args:    ${(snapshot.plan.args ?? []).join(' ')}`);
    }
  } else {
    sections.push('  (no plan recorded — likely failed before resolveBackendLaunchCommand)');
  }
  sections.push('');

  sections.push('## 4. Resources');
  sections.push('');
  sections.push(...buildResourcesSection(process.resourcesPath));
  sections.push('');

  sections.push('## 5. Environment');
  sections.push('');
  sections.push(...buildEnvSection());
  sections.push('');

  sections.push('## 6. Process');
  sections.push('');
  if (snapshot.proc) {
    const p = snapshot.proc;
    sections.push(`  backendProc.pid:        ${p.pid ?? '<null>'}`);
    sections.push(`  backendProc.exitCode:   ${p.exitCode ?? '<null>'}`);
    sections.push(`  backendProc.signalCode: ${p.signalCode ?? '<null>'}`);
    sections.push(`  currentBackend.gen:     ${p.generation ?? '<null>'}`);
    sections.push(
      `  ownershipToken:         ${p.ownershipToken ? `${p.ownershipToken.slice(0, 8)}…(${p.ownershipToken.length})` : '<null>'}`,
    );
  } else {
    sections.push('  (no process snapshot recorded)');
  }
  sections.push('');

  sections.push('## 7. Backend stderr (most recent)');
  sections.push('');
  const stderrText = readStderrTail();
  if (stderrText.trim().length === 0) {
    sections.push('  (no stderr captured yet — backend may not have written anything)');
  } else {
    sections.push('```');
    sections.push(stderrText.trimEnd());
    sections.push('```');
  }
  sections.push('');

  sections.push('## 8. Today log tail');
  sections.push('');
  sections.push(...buildLogTailSection());
  sections.push('');

  sections.push(...buildWin7Hint(process.platform, osRelease));
  sections.push('');

  sections.push('## End of diagnostic');
  return sections.join('\n');
}

export async function collectAndWriteDiagnostic(snapshot: DiagnosticSnapshot): Promise<string> {
  let userData = '';
  try {
    userData = app.getPath('userData');
  } catch (err) {
    logger.error('diagnostics: app.getPath(userData) failed', { err: String(err) });
  }
  if (!userData) {
    logger.error('diagnostics: cannot resolve userData; writing to log dir only', {
      reason: snapshot.reason,
    });
    return '';
  }
  let path: string;
  try {
    path = await choosePath(userData);
  } catch (err) {
    logger.error('diagnostics: choosePath failed', { err: String(err) });
    return '';
  }
  try {
    const body = render(snapshot);
    await writeFile(path, body, 'utf8');
    logger.warn('diagnostics: wrote startup diagnostic', {
      path,
      reason: snapshot.reason,
      bytes: Buffer.byteLength(body, 'utf8'),
    });
    return path;
  } catch (err) {
    logger.error('diagnostics: writeFile failed', { err: String(err), path });
    return '';
  }
}
