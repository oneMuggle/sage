// electron/runtime-check.ts

/**
 * Win32 runtime environment detection — Win7 SP1 闪退根因防御层 (2026-09-17).
 *
 * 内网部分 Win7 机器闪退的同一根因触发两个症状:
 *   1) 用户报告的「浏览器内核版本低」 —— 高版本 Chromium 装不上/白屏
 *   2) Sage 启动时 Electron 自带的 Chromium 106 找不到运行库 → 主进程/子
 *      进程启动失败 → 闪退/白屏
 *
 * 启动失败有两类不同根因, 本次检测同时覆盖:
 *
 * (A) 补丁 / VC++ 运行库缺失 — 微软官方下载链接, 用户手动装:
 *   - Visual C++ 2015–2022 Redistributable (x64) — Electron / Chromium 必备
 *   - KB3033929 (SHA-256 证书支持补丁, wintrust.dll ≥ 6.1.7601.18741)
 *   - KB4474419 (SHA-2 签名支持)
 *   - KB4490628 (Servicing Stack Update)
 *   - KB2670838 (DirectWrite / D3D11) — recommended
 *
 * (B) 企业组策略 / 管控软件禁用关键服务 — splash 后白屏 / 消失:
 *   - TrustedInstaller (Windows Modules Installer)
 *   - wuauserv (Windows Update)
 *   修复资源打包在 resources/win7-fix/ (sage-win7-fix.md + fix.bat),
 *   对话框引导用户在资源管理器定位 fix.bat, 右键以管理员身份运行。
 *
 * 设计要点:
 *   - 每个 check < 2s 完成, 8 个 check 通过 Promise.all 并行跑
 *   - 注册表/wmic/sc 不可用时 fallback 到文件存在性 (弱信号, 转 warn 而非 critical)
 *   - 任何 check 出错都不会 throw, 只会返回 severity='warn'/'critical'
 *   - 非 Win32 平台直接返回 ok 占位
 *
 * 调用方: electron/main.ts 的 app.whenReady() 阶段, 在 runDoctorCheck() 之前
 * 同步调用 runRuntimeChecks()。如有 critical, 弹 showRuntimeMissingDialog 提示。
 * 对话框按钮按 missing 项类型动态增减 (补丁路径 / 服务禁用路径), fail-open:
 * 用户选「仍要启动」则继续。
 */

import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { dialog, shell, app } from 'electron';
import { logger } from './logger';
import { getLogDir } from './logPaths';

// 2026-09-17: 惰性求值 execFileP, 不在模块顶层 promisify(execFile)。
// vitest mock `electron` / `node:child_process` 时不会注入 execFile, 模块
// 顶层求值会抛 TypeError("original must be of type function"). 放到函数内
// 第一次调用时再 promisify, 让 mock 测试可以顺利 import 本模块而不报错.
// 生产环境下 execFile 永远存在, 单次 promisify 开销可忽略.
let execFilePCached:
  | ((file: string, args: string[], opts: unknown) => Promise<{ stdout: string }>)
  | null = null;
function execFileP(file: string, args: string[], opts: unknown): Promise<{ stdout: string }> {
  if (!execFilePCached) execFilePCached = promisify(execFile);
  return execFilePCached(file, args, opts);
}

/**
 * TEST-ONLY: 注入自定义 execFileP 实现, 绕过真实 child_process + promisify 链.
 * 仅当 NODE_ENV === 'test' 或 VITEST 环境变量存在时生效, 生产构建是 no-op.
 * 这样单测不需要跟 Node CJS/ESM 互操作搏斗, 直接注入 mock 函数即可.
 * vitest factory 对 Node 内建模块 (child_process/util) 的拦截在 C++ 层级
 * 不能替换原始引用 (execFile 的真实 C++ 实现绕过 ESM namespace mock); 直接
 * 在模块级暴露注入点是绕开此限制的最稳手段.
 */
export function _setExecFilePForTesting(
  fn: ((file: string, args: string[], opts: unknown) => Promise<{ stdout: string }>) | null,
): void {
  if (process.env.NODE_ENV !== 'test' && !process.env.VITEST) return;
  execFilePCached = fn;
}

const DOWNLOAD_URLS = {
  vc_redist_x64: 'https://aka.ms/vc14/vc_redist.x64.exe',
  vc_redist_x86: 'https://aka.ms/vc14/vc_redist.x86.exe',
  kb3033929: 'https://www.catalog.update.microsoft.com/Search.aspx?q=KB3033929',
  kb4474419: 'https://www.catalog.update.microsoft.com/Search.aspx?q=KB4474419',
  kb4490628: 'https://www.catalog.update.microsoft.com/Search.aspx?q=KB4490628',
  kb2670838: 'https://www.catalog.update.microsoft.com/Search.aspx?q=KB2670838',
} as const;

export interface RuntimeCheckResult {
  name: string;
  severity: 'ok' | 'warn' | 'critical';
  message: string;
  fix_hint: string;
  detected: boolean;
  download_url?: string; // 补丁缺失: 微软官方下载链接
  doc_path?: string; // 服务禁用: 修复文档磁盘路径 (打包后 resources/win7-fix/)
  fix_script_path?: string; // 服务禁用: 修复脚本磁盘路径 (打包后 resources/win7-fix/fix.bat)
}

// ── helpers ──────────────────────────────────────────────────────────────────

function systemRoot(): string {
  return process.env.SystemRoot ?? process.env.WINDIR ?? 'C:\\Windows';
}

function system32(file: string): string {
  return join(systemRoot(), 'System32', file);
}

function syswow64(file: string): string {
  return join(systemRoot(), 'SysWOW64', file);
}

function ok(name: string, message: string): RuntimeCheckResult {
  return { name, severity: 'ok', message, fix_hint: '', detected: true };
}

function warn(name: string, message: string, fix_hint: string): RuntimeCheckResult {
  return { name, severity: 'warn', message, fix_hint, detected: false };
}

function critical(
  name: string,
  message: string,
  fix_hint: string,
  download_url: string,
): RuntimeCheckResult {
  return { name, severity: 'critical', message, fix_hint, detected: false, download_url };
}

/** 版本号字符串比较 ("6.1.7601.18741"). 返回 -1/0/1. */
function compareVersions(a: string, b: string): number {
  const parse = (s: string): number[] =>
    s.split('.').map((n) => {
      const x = parseInt(n, 10);
      return Number.isFinite(x) ? x : 0;
    });
  const va = parse(a);
  const vb = parse(b);
  const len = Math.max(va.length, vb.length);
  for (let i = 0; i < len; i += 1) {
    const x = va[i] ?? 0;
    const y = vb[i] ?? 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/** PowerShell 调用, 2s 超时. 出错返回 null. */
async function tryPowerShell(script: string): Promise<string | null> {
  try {
    const { stdout } = await execFileP(
      'powershell',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      { timeout: 2000, windowsHide: true },
    );
    return stdout.trim();
  } catch {
    return null;
  }
}

// ── individual checks ────────────────────────────────────────────────────────

async function checkVCppRedistX64(): Promise<RuntimeCheckResult> {
  const name = 'vc_redist_x64';
  const url = DOWNLOAD_URLS.vc_redist_x64;
  if (existsSync(system32('vcruntime140.dll'))) {
    return ok(name, 'Visual C++ 2015–2022 Redistributable (x64) 已安装');
  }
  const reg = await tryPowerShell(
    "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64' -ErrorAction SilentlyContinue).Version",
  );
  if (reg && reg.length > 0) {
    return ok(name, 'Visual C++ 2015–2022 Redistributable (x64) 已安装');
  }
  return critical(
    name,
    'Visual C++ 2015–2022 Redistributable (x64) 未安装',
    '下载并安装 vc_redist.x64.exe 后重启 Sage',
    url,
  );
}

async function checkVCppRedistX86(): Promise<RuntimeCheckResult> {
  const name = 'vc_redist_x86';
  if (existsSync(syswow64('vcruntime140.dll'))) {
    return ok(name, 'Visual C++ 2015–2022 Redistributable (x86) 已安装');
  }
  const reg = await tryPowerShell(
    "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Wow6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86' -ErrorAction SilentlyContinue).Version",
  );
  if (reg && reg.length > 0) {
    return ok(name, 'Visual C++ 2015–2022 Redistributable (x86) 已安装');
  }
  return warn(
    name,
    'Visual C++ 2015–2022 Redistributable (x86) 未安装 (Sage 启动非必需, 但部分 Windows 组件需要)',
    '建议下载 vc_redist.x86.exe 安装',
  );
}

async function checkKB3033929(): Promise<RuntimeCheckResult> {
  const name = 'kb3033929';
  const url = DOWNLOAD_URLS.kb3033929;
  const ver = await tryPowerShell(
    "(Get-Item 'C:\\Windows\\System32\\wintrust.dll').VersionInfo.FileVersion",
  );
  if (ver === null) {
    if (existsSync(system32('wintrust.dll'))) {
      return warn(
        name,
        '无法确认 KB3033929 (wintrust.dll 版本查询失败)',
        '如果 Sage 启动失败 / 显示证书错误, 请从 Microsoft Update Catalog 安装 KB3033929',
      );
    }
    return critical(
      name,
      'wintrust.dll 缺失 (KB3033929 未安装)',
      '从 Microsoft Update Catalog 安装 KB3033929',
      url,
    );
  }
  if (compareVersions(ver, '6.1.7601.18741') >= 0) {
    return ok(name, `KB3033929 已安装 (wintrust.dll ${ver})`);
  }
  return critical(
    name,
    `KB3033929 未安装 (wintrust.dll 版本过低: ${ver}, 需要 ≥ 6.1.7601.18741)`,
    '从 Microsoft Update Catalog 安装 KB3033929',
    url,
  );
}

async function checkKB4474419(): Promise<RuntimeCheckResult> {
  return checkKBInstalled('kb4474419', 'KB4474419', DOWNLOAD_URLS.kb4474419);
}

async function checkKB4490628(): Promise<RuntimeCheckResult> {
  return checkKBInstalled('kb4490628', 'KB4490628', DOWNLOAD_URLS.kb4490628);
}

/** 通过 wmic qfe 查询特定 KB 是否已安装. 受内网管控软件禁用 wmic 时返回 warn. */
async function checkKBInstalled(
  name: string,
  kbNumber: string,
  url: string,
): Promise<RuntimeCheckResult> {
  try {
    const { stdout } = await execFileP('wmic', ['qfe', 'list', '/format:list'], {
      timeout: 5000,
      windowsHide: true,
    });
    if (stdout.includes(kbNumber)) {
      return ok(name, `${kbNumber} 已安装`);
    }
    return critical(
      name,
      `${kbNumber} 未安装`,
      `从 Microsoft Update Catalog 安装 ${kbNumber}`,
      url,
    );
  } catch {
    return warn(
      name,
      `无法确认 ${kbNumber} (wmic 不可用或被禁用)`,
      `如果 Sage 启动失败, 请从 Microsoft Update Catalog 安装 ${kbNumber}`,
    );
  }
}

async function checkKB2670838(): Promise<RuntimeCheckResult> {
  const name = 'kb2670838';
  const dwriteExists = existsSync(system32('dwrite.dll'));
  const d2d1Exists = existsSync(system32('d2d1.dll'));
  if (dwriteExists && d2d1Exists) {
    return ok(name, 'KB2670838 已安装 (DirectWrite / D3D11)');
  }
  return warn(
    name,
    `KB2670838 可能未安装 (dwrite.dll=${dwriteExists}, d2d1.dll=${d2d1Exists})`,
    'Sage 已自动禁用 GPU 加速, 此项非必需; 但若浏览器内核仍有问题, 请安装 KB2670838',
  );
}

// ── Win7 服务禁用检测 (内网企业组策略禁用 TrustedInstaller / wuauserv 路径) ──

/**
 * 服务禁用修复资源目录 (打包后 vs dev 模式).
 * 沿用 main.ts:1534-1536 读 CHANGELOG.md 的 __dirname 惯用模式:
 *   - packaged: process.resourcesPath → <install>/resources
 *   - dev:      __dirname = dist-electron/, 向上两级到项目根
 * 不引入 getResourcesDir() helper (项目里无此先例).
 */
function win7FixDir(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'win7-fix')
    : join(__dirname, '..', '..', 'resources', 'win7-fix');
}

/**
 * 通用 Windows 服务状态检测. sc query 不要求管理员权限 (只读).
 * 解析 STATE 字段数值避免本地化 (中文 Windows "RUNNING" → "正在运行").
 *   STATE=4 RUNNING / STATE=1 STOPPED / STATE=2 START_PENDING / STATE=3 STOP_PENDING
 *
 * @param extra 仅服务禁用路径用, 填 doc_path / fix_script_path 指向打包的修复文档+脚本
 */
async function checkWindowsService(
  serviceName: string,
  displayName: string,
  extra?: Pick<RuntimeCheckResult, 'doc_path' | 'fix_script_path'>,
): Promise<RuntimeCheckResult> {
  if (process.platform !== 'win32') {
    return ok(serviceName, `N/A (非 Win32 平台)`);
  }
  try {
    const { stdout } = await execFileP('sc', ['query', serviceName], {
      timeout: 2000,
      windowsHide: true,
    });
    const m = stdout.match(/STATE\s*:\s*(\d+)/);
    const state = m ? parseInt(m[1], 10) : -1;
    if (state === 4) {
      return ok(serviceName, `${displayName} 服务正在运行 (STATE=4)`);
    }
    if (state === 1 || state === 2 || state === 3) {
      // STATE=1 STOPPED / STATE=2 START_PENDING / STATE=3 STOP_PENDING 都视为"未运行"
      // 启动期如果处于 START_PENDING 也算异常 (正常应迅速转 STATE=4)
      return {
        name: serviceName,
        severity: 'critical',
        message: `${displayName} 服务未运行 (STATE=${state})`,
        fix_hint: '以管理员身份运行安装包内 win7-fix/fix.bat, 然后重启电脑',
        detected: false,
        ...extra,
      };
    }
    return warn(
      serviceName,
      `${displayName} 服务状态未知 (STATE=${state})`,
      '查看安装包内 win7-fix/sage-win7-fix.md 修复文档',
    );
  } catch {
    return warn(
      serviceName,
      `无法查询 ${displayName} (sc 不可用或被管控软件拦截)`,
      '查看安装包内 win7-fix/sage-win7-fix.md 修复文档',
    );
  }
}

function checkTrustedInstallerService(): Promise<RuntimeCheckResult> {
  return checkWindowsService('TrustedInstaller', 'Windows Modules Installer', {
    doc_path: join(win7FixDir(), 'sage-win7-fix.md'),
    fix_script_path: join(win7FixDir(), 'fix.bat'),
  });
}

function checkWuauservService(): Promise<RuntimeCheckResult> {
  return checkWindowsService('wuauserv', 'Windows Update', {
    doc_path: join(win7FixDir(), 'sage-win7-fix.md'),
    fix_script_path: join(win7FixDir(), 'fix.bat'),
  });
}

// ── public API ───────────────────────────────────────────────────────────────

/**
 * 同步阻塞运行所有 Win32 运行时检测. 非 Win32 平台直接返回 ok.
 * 任何 check 异常都被 swallow, 整个调用不会 throw.
 */
export async function runRuntimeChecks(): Promise<RuntimeCheckResult[]> {
  if (process.platform !== 'win32') {
    return [
      {
        name: 'platform',
        severity: 'ok',
        message: `当前平台 ${process.platform} — 无需运行时检测`,
        fix_hint: '',
        detected: true,
      },
    ];
  }
  const startedAt = Date.now();
  const results = await Promise.all([
    checkVCppRedistX64(),
    checkVCppRedistX86(),
    checkKB3033929(),
    checkKB4474419(),
    checkKB4490628(),
    checkKB2670838(),
    // Win7 服务禁用路径 (内网企业组策略常见): TrustedInstaller / wuauserv
    // 被禁用时 Sage 启动 splash 后白屏 / 消失。critical 时对话框引导用户
    // 在资源管理器定位到打包的 win7-fix/fix.bat, 右键以管理员身份运行。
    checkTrustedInstallerService(),
    checkWuauservService(),
  ]);
  const elapsedMs = Date.now() - startedAt;
  for (const r of results) {
    logger.info(`runtime-check:${r.name}`, {
      severity: r.severity,
      detected: r.detected,
      message: r.message,
    });
  }
  const missing = results.filter((r) => r.severity === 'critical').length;
  logger.info('runtime-check:summary', {
    total: results.length,
    critical: missing,
    warn: results.filter((r) => r.severity === 'warn').length,
    elapsedMs,
  });
  return results;
}

// ── user prompt ──────────────────────────────────────────────────────────────

export type RuntimeMissingChoice =
  | 'open-downloads'
  | 'open-fix-script'
  | 'open-fix-doc'
  | 'open-logs'
  | 'continue'
  | 'quit';

/**
 * 当 runRuntimeChecks 返回 critical 项时, 弹窗告诉用户去装什么 / 修什么.
 *
 * 对话框按钮按 missing 项类型动态增减:
 *   - 任一项有 download_url  → 出现「打开下载页」(补丁路径)
 *   - 任一项有 fix_script_path → 出现「打开修复脚本」+「查看修复文档」(服务禁用路径)
 *   - 固定按钮: 「查看日志目录」「仍要启动」「退出」
 *
 * CRITICAL: logger.error(...) 必须在 dialog.showMessageBox 之前调用, 这样即使
 * 对话框本身崩溃, 失败也已被记录.
 */
export async function showRuntimeMissingDialog(
  missing: RuntimeCheckResult[],
): Promise<RuntimeMissingChoice> {
  // CRITICAL: log before dialog (so even if dialog crashes the failure is captured)
  logger.error('main: runtime missing, showing dialog', {
    missing: missing.map((m) => ({
      name: m.name,
      message: m.message,
      url: m.download_url,
      doc: m.doc_path,
      script: m.fix_script_path,
    })),
  });

  const logDir = getLogDir();

  // 按 missing 项逐条拼展示行 (补丁带下载 URL, 服务禁用带修复脚本路径)
  const lines: string[] = [];
  for (const m of missing) {
    lines.push(`❌ ${m.message}`);
    if (m.download_url) lines.push(`   下载: ${m.download_url}`);
    if (m.fix_script_path) {
      lines.push(`   修复: 右键以管理员身份运行 ${m.fix_script_path}`);
    }
    lines.push('');
  }

  // 动态按钮 (按检测到的问题类型增减)
  const hasDownloads = missing.some((m) => m.download_url);
  const hasFixScript = missing.some((m) => m.fix_script_path);
  const buttons: string[] = [];
  if (hasDownloads) buttons.push('打开下载页');
  if (hasFixScript) buttons.push('打开修复脚本');
  if (hasFixScript) buttons.push('查看修复文档');
  buttons.push('查看日志目录', '仍要启动', '退出');

  const defaultId = 0;
  const cancelId = buttons.length - 1; // 永远「退出」

  const detailPatches = hasDownloads
    ? '补丁缺失: 点击「打开下载页」下载并安装, 完成后重启 Sage。\n'
    : '';
  const detailServices = hasFixScript
    ? '服务被禁用: 点击「打开修复脚本」在资源管理器定位 fix.bat, 右键以管理员身份运行, 然后重启电脑。\n'
    : '';

  const detail =
    '缺少运行组件或被企业管控禁用了关键服务, 会导致 Sage 启动失败、闪退或显示白屏。\n\n' +
    detailPatches +
    detailServices +
    '如果仍有问题, 点击「查看日志目录」获取诊断详情并附在反馈中。\n\n' +
    `日志目录: ${logDir}`;

  const message =
    hasDownloads && hasFixScript
      ? `Sage 启动检查发现您的系统存在 ${missing.length} 个问题：`
      : hasFixScript
        ? `Sage 启动检查发现关键 Windows 服务被禁用 (${missing.length} 项)：`
        : `Sage 启动检查发现您的系统缺少 ${missing.length} 个关键运行环境组件：`;

  const result = await dialog.showMessageBox({
    type: 'error',
    title: 'Sage 启动检查发现问题',
    message,
    detail: `${lines.join('\n')}\n${detail}`,
    buttons,
    defaultId,
    cancelId,
    noLink: true,
  });

  // 把按钮索引映射回 RuntimeMissingChoice (按钮数组是动态拼的, 索引需按类型推)
  let idx = 0;
  const idxOpenDownloads = hasDownloads ? idx++ : -1;
  const idxOpenFixScript = hasFixScript ? idx++ : -1;
  const idxOpenFixDoc = hasFixScript ? idx++ : -1;
  const idxOpenLogs = idx++;
  const idxContinue = idx++;
  // idxQuit = buttons.length - 1 (永远「退出」), 但 choice 分支走 default ': quit',
  // 无需显式匹配 → 不赋值避免 no-unused-vars

  const choice: RuntimeMissingChoice =
    result.response === idxOpenDownloads
      ? 'open-downloads'
      : result.response === idxOpenFixScript
        ? 'open-fix-script'
        : result.response === idxOpenFixDoc
          ? 'open-fix-doc'
          : result.response === idxOpenLogs
            ? 'open-logs'
            : result.response === idxContinue
              ? 'continue'
              : 'quit';

  if (choice === 'open-downloads') {
    const urls = missing.map((m) => m.download_url).filter((u): u is string => !!u);
    logger.info('main: user chose open-downloads after runtime missing', { urls });
    for (const url of urls) {
      Promise.resolve(shell.openExternal(url)).catch((err: unknown) =>
        logger.error('main: shell.openExternal failed', { url, err: String(err) }),
      );
    }
  } else if (choice === 'open-fix-script') {
    // 取第一个带 fix_script_path 的项 (所有服务 critical 项共享同一脚本路径)
    const scriptPath = missing.find((m) => m.fix_script_path)?.fix_script_path;
    if (scriptPath) {
      logger.info('main: user chose open-fix-script after runtime missing', { scriptPath });
      Promise.resolve(shell.showItemInFolder(scriptPath)).catch((err: unknown) =>
        logger.error('main: shell.showItemInFolder failed', {
          scriptPath,
          err: String(err),
        }),
      );
    }
  } else if (choice === 'open-fix-doc') {
    // 取第一个带 doc_path 的项 (所有服务 critical 项共享同一文档路径)
    const docPath = missing.find((m) => m.doc_path)?.doc_path;
    if (docPath) {
      logger.info('main: user chose open-fix-doc after runtime missing', { docPath });
      Promise.resolve(shell.openPath(docPath)).catch((err: unknown) =>
        logger.error('main: shell.openPath failed', { docPath, err: String(err) }),
      );
    }
  } else if (choice === 'open-logs') {
    logger.info('main: user chose open-logs after runtime missing');
    Promise.resolve(shell.openPath(logDir)).catch((err: unknown) =>
      logger.error('main: shell.openPath failed', { err: String(err) }),
    );
  } else if (choice === 'continue') {
    logger.warn('main: user chose continue despite runtime missing', {
      missing: missing.map((m) => m.name),
    });
  } else {
    logger.info('main: user chose quit after runtime missing');
    app.quit();
  }
  return choice;
}
