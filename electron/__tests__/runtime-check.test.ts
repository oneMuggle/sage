// electron/__tests__/runtime-check.test.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { RuntimeCheckResult } from '../runtime-check';

/**
 * Win7 启动失败防御层单测 — 重点覆盖 PR feat/win7-service-fix 新增:
 *   - checkWindowsService (通用 sc query, STATE 数值解析, 避免本地化坑)
 *   - checkTrustedInstallerService / checkWuauservService (critical 时带
 *     doc_path / fix_script_path, 指向打包的 win7-fix/ 修复文档 + 脚本)
 *   - showRuntimeMissingDialog 动态按钮 (按 missing 项有无 download_url /
 *     fix_script_path 增减「打开下载页」「打开修复脚本」「查看修复文档」)
 *
 * 既有 6 个补丁 check (VC++/KB*) 沿用既有路径, 本文件只覆盖非 win32 平台
 * 占位分支; 补丁分支的细测留给后续扩展, 不在本次范围.
 *
 * Mock 策略 (2026-09 最终版):
 *   - vi.mock('electron'): 顶层 vi.fn() 占位, 与 showStartupFailureDialog.test.ts 同款.
 *   - _setExecFilePForTesting (runtime-check.ts 暴露的 TEST-ONLY 注入点):
 *     直接注入 mock 函数到模块内 execFilePCached, 完全绕过 Node 内建
 *     child_process + util.promisify 的 CJS/ESM 互操作层. vitest factory
 *     拦截 Node 内建模块时, factory 返回值替换了 ESM namespace, 但真实
 *     child_process.execFile 的 C++ 引用绕过 mock 链 (已用诊断确认 mock
 *     函数从未被调用). 注入点是避开此坑的最干净手段.
 *   - vi.mock('node:fs'): 只替换 existsSync, importOriginal 保留完整模块形态.
 *   - vi.spyOn(process, 'platform', 'get'): 切换平台. afterEach 必须恢复.
 */

// ── electron mock ──────────────────────────────────────────────────────────

const mockShowMessageBox = vi.fn();
const mockOpenExternal = vi.fn();
const mockShowItemInFolder = vi.fn();
const mockOpenPath = vi.fn();
const mockQuit = vi.fn();
// isPackaged 通过 getter 响应式控制, 与 userDataPaths.test.ts 同款.
// 本测试未触发 win7FixDir() (服务 STATE=4 不拼 doc_path; STATE=1 的
// doc_path/fix_script_path 由测试直接构造 mock missing 项传入 dialog).
// 保留 isPackagedRef 是为未来 checkWindowsService 路径测试预留.
let isPackagedRef = false;

vi.mock('electron', () => ({
  dialog: { showMessageBox: mockShowMessageBox },
  shell: {
    openExternal: mockOpenExternal,
    showItemInFolder: mockShowItemInFolder,
    openPath: mockOpenPath,
  },
  app: {
    quit: mockQuit,
    get isPackaged() {
      return isPackagedRef;
    },
  },
}));

// ── execFileP mock (注入式, 绕过 Node CJS/ESM 互操作坑) ────────────────────
// 用顶层 vi.fn, 每个测试前 _setExecFilePForTesting(mock) 把 mock 注入到
// runtime-check.ts 内 execFilePCached. 测试期间 NODE_ENV='test' 由 vitest
// 自动设置, _setExecFilePForTesting 不会在生产环境被误触发.

const execFileMock = vi.fn<(...args: unknown[]) => Promise<unknown>>();

// ── node:fs mock (existsSync 在补丁 check 中被调用) ────────────────────────
// importOriginal 保留完整模块形态, 只替换 existsSync.

const existsSyncMock = vi.fn<(...args: unknown[]) => boolean>();
vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  return {
    ...actual,
    existsSync: (...args: unknown[]) => existsSyncMock(...args),
    default: actual,
  };
});

// ── logger mock (静默, 不写盘) ─────────────────────────────────────────────

vi.mock('../logger', () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

// ── logPaths mock ──────────────────────────────────────────────────────────

vi.mock('../logPaths', () => ({
  getLogDir: () => '/mock/log/dir',
}));

// ── 测试环境准备 ───────────────────────────────────────────────────────────

let platformGetter: ReturnType<typeof vi.spyOn>;

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  execFileMock.mockReset();
  existsSyncMock.mockReturnValue(false);
  isPackagedRef = false;
  // 默认 pin 为 win32; 非 win32 测试单独覆盖.
  platformGetter = vi.spyOn(process, 'platform', 'get').mockReturnValue('win32');
  // 每个测试开始都重新注入 execFileMock 到模块内 cached execFileP.
  // vi.resetModules() 后需要重新 import 才能拿到新模块实例并注入.
  const { _setExecFilePForTesting } = await import('../runtime-check');
  _setExecFilePForTesting((file: string, args: string[], opts: unknown) =>
    Promise.resolve(execFileMock(file, args, opts) as Promise<{ stdout: string }>),
  );
});

afterEach(() => {
  platformGetter.mockRestore();
});

// ── runRuntimeChecks: 平台 + 服务检测 ───────────────────────────────────────

describe('runRuntimeChecks', () => {
  it('returns platform=ok on non-win32 (linux) without running any service check', async () => {
    platformGetter.mockReturnValue('linux');
    const { runRuntimeChecks } = await import('../runtime-check');
    const results = await runRuntimeChecks();
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({
      name: 'platform',
      severity: 'ok',
      detected: true,
    });
    // 任何 child_process 调用都不该发生 (sc / wmic / powershell 全部跳过)
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it('returns platform=ok on non-win32 (darwin)', async () => {
    platformGetter.mockReturnValue('darwin');
    const { runRuntimeChecks } = await import('../runtime-check');
    const results = await runRuntimeChecks();
    expect(results[0]).toMatchObject({ name: 'platform', severity: 'ok' });
  });

  describe('checkTrustedInstallerService (via runRuntimeChecks on win32)', () => {
    it('STATE=4 (RUNNING) → severity=ok, 文案包含 STATE=4', async () => {
      execFileMock.mockResolvedValue({
        stdout: '\nSTATE              : 4 RUNNING\n',
      });
      const { runRuntimeChecks } = await import('../runtime-check');
      const results = await runRuntimeChecks();
      const ti = results.find((r) => r.name === 'TrustedInstaller');
      expect(ti).toBeDefined();
      expect(ti!.severity).toBe('ok');
      expect(ti!.message).toContain('STATE=4');
      expect(ti!.message).toContain('Windows Modules Installer');
    });

    it('STATE=1 (STOPPED) → severity=warn, 带 doc_path + fix_script_path', async () => {
      execFileMock.mockResolvedValue({
        stdout: '\nSTATE              : 1 STOPPED\n',
      });
      const { runRuntimeChecks } = await import('../runtime-check');
      const results = await runRuntimeChecks();
      const ti = results.find((r) => r.name === 'TrustedInstaller');
      expect(ti).toBeDefined();
      expect(ti!.severity).toBe('warn');
      expect(ti!.message).toContain('STATE=1');
      expect(ti!.fix_hint).toContain('win7-fix/fix.bat');
      // 关键字段: 服务禁用路径必须指向打包资源
      expect(ti!.doc_path).toMatch(/win7-fix[/\\]sage-win7-fix\.md$/);
      expect(ti!.fix_script_path).toMatch(/win7-fix[/\\]fix\.bat$/);
      // 服务 check 不应带 download_url (那是补丁 check 用的)
      expect(ti!.download_url).toBeUndefined();
    });

    it('STATE=2 (START_PENDING) → severity=warn, 不误判运行库缺失', async () => {
      execFileMock.mockResolvedValue({
        stdout: '\nSTATE              : 2 START_PENDING\n',
      });
      const { runRuntimeChecks } = await import('../runtime-check');
      const results = await runRuntimeChecks();
      const wu = results.find((r) => r.name === 'wuauserv');
      expect(wu).toBeDefined();
      expect(wu!.severity).toBe('warn');
      expect(wu!.message).toContain('STATE=2');
    });
  });

  describe('checkWuauservService (via runRuntimeChecks on win32)', () => {
    it('STATE unknown (STATE=-1) → severity=warn (不阻断启动)', async () => {
      // stdout 没有 STATE 行 → parseInt 返回 NaN → 走 warn 分支
      execFileMock.mockResolvedValue({ stdout: 'SERVICE_NAME: wuauserv\n' });
      const { runRuntimeChecks } = await import('../runtime-check');
      const results = await runRuntimeChecks();
      const wu = results.find((r) => r.name === 'wuauserv');
      expect(wu).toBeDefined();
      expect(wu!.severity).toBe('warn');
      expect(wu!.message).toContain('状态未知');
      expect(wu!.fix_hint).toContain('sage-win7-fix.md');
    });

    it('sc throws (管控软件拦截 / sc 不可用) → severity=warn, fail-open', async () => {
      execFileMock.mockRejectedValue(new Error('Access is denied'));
      const { runRuntimeChecks } = await import('../runtime-check');
      const results = await runRuntimeChecks();
      const wu = results.find((r) => r.name === 'wuauserv');
      const ti = results.find((r) => r.name === 'TrustedInstaller');
      expect(wu!.severity).toBe('warn');
      expect(ti!.severity).toBe('warn');
      expect(wu!.message).toContain('无法查询');
      // 服务被拦截不该升级为 critical (避免误报阻断启动)
      expect(wu!.detected).toBe(false);
    });
  });
});

// ── showRuntimeMissingDialog: 动态按钮 ──────────────────────────────────────

describe('showRuntimeMissingDialog', () => {
  // 构造补丁 check critical 项 (旧路径, 带 download_url)
  const missingPatches: RuntimeCheckResult[] = [
    {
      name: 'vc_redist_x64',
      severity: 'critical',
      message: 'VC++ 未安装',
      fix_hint: '装',
      detected: false,
      download_url: 'https://aka.ms/vc14/vc_redist.x64.exe',
    },
  ];

  // 构造服务禁用 critical 项 (新路径, 带 doc_path + fix_script_path)
  const missingServices: RuntimeCheckResult[] = [
    {
      name: 'TrustedInstaller',
      severity: 'critical',
      message: 'Windows Modules Installer 服务未运行 (STATE=1)',
      fix_hint: '以管理员身份运行 win7-fix/fix.bat',
      detected: false,
      doc_path: '/install/resources/win7-fix/sage-win7-fix.md',
      fix_script_path: '/install/resources/win7-fix/fix.bat',
    },
    {
      name: 'wuauserv',
      severity: 'critical',
      message: 'Windows Update 服务未运行 (STATE=1)',
      fix_hint: '以管理员身份运行 win7-fix/fix.bat',
      detected: false,
      doc_path: '/install/resources/win7-fix/sage-win7-fix.md',
      fix_script_path: '/install/resources/win7-fix/fix.bat',
    },
  ];

  it('patches-only missing → 按钮含「打开下载页」不含「打开修复脚本」/「查看修复文档」', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    await showRuntimeMissingDialog(missingPatches);

    expect(mockShowMessageBox).toHaveBeenCalledTimes(1);
    const call = mockShowMessageBox.mock.calls[0][0];
    expect(call.buttons).toEqual(['打开下载页', '查看日志目录', '仍要启动', '退出']);
    expect(call.cancelId).toBe(3); // 永远「退出」(最后一个)
    expect(call.defaultId).toBe(0);
    expect(call.type).toBe('error');
    expect(call.detail).toContain('VC++ 未安装');
    expect(call.detail).toContain('下载:');
    // 补丁路径不该出现「修复」按钮
    expect(call.detail).not.toContain('fix.bat');
  });

  it('services-only missing → 按钮含「打开修复脚本」+「查看修复文档」不含「打开下载页」', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    await showRuntimeMissingDialog(missingServices);

    const call = mockShowMessageBox.mock.calls[0][0];
    // 无 download_url → 没「打开下载页」; 有 fix_script_path → 两个服务按钮
    expect(call.buttons).toEqual([
      '打开修复脚本',
      '查看修复文档',
      '查看日志目录',
      '仍要启动',
      '退出',
    ]);
    expect(call.cancelId).toBe(4);
    // 服务 missing 文案应逐条列 service 状态 + 修复脚本路径
    expect(call.detail).toContain('Windows Modules Installer');
    expect(call.detail).toContain('Windows Update');
    expect(call.detail).toContain('fix.bat');
    // message 走"服务被禁用"分支
    expect(call.message).toContain('Windows 服务被禁用');
  });

  it('both patches + services missing → 动态拼出 6 个按钮 + message 走"存在 N 个问题"', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    await showRuntimeMissingDialog([...missingPatches, ...missingServices]);

    const call = mockShowMessageBox.mock.calls[0][0];
    expect(call.buttons).toEqual([
      '打开下载页', // 0: download
      '打开修复脚本', // 1: fix script
      '查看修复文档', // 2: fix doc
      '查看日志目录', // 3: logs
      '仍要启动', // 4: continue
      '退出', // 5: quit
    ]);
    expect(call.buttons).toHaveLength(6);
    expect(call.cancelId).toBe(5);
    // message 走"存在 N 个问题" (同时有补丁 + 服务)
    expect(call.message).toContain('3 个问题');
    // detail 同时包含补丁下载 URL 和服务修复脚本路径
    expect(call.detail).toContain('下载:');
    expect(call.detail).toContain('右键以管理员身份运行');
  });

  it('click "打开修复脚本" → shell.showItemInFolder(fixScriptPath)', async () => {
    // services-only 布局: [打开修复脚本, 查看修复文档, 查看日志目录, 仍要启动, 退出]
    // "打开修复脚本" 索引 = 0
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    const choice = await showRuntimeMissingDialog(missingServices);

    expect(choice).toBe('open-fix-script');
    expect(mockShowItemInFolder).toHaveBeenCalledWith('/install/resources/win7-fix/fix.bat');
    // 不该误触发其他 shell 动作
    expect(mockOpenExternal).not.toHaveBeenCalled();
    expect(mockOpenPath).not.toHaveBeenCalled();
    expect(mockQuit).not.toHaveBeenCalled();
  });

  it('click "查看修复文档" → shell.openPath(docPath)', async () => {
    // services-only 布局: [打开修复脚本(0), 查看修复文档(1), 查看日志目录(2), 仍要启动(3), 退出(4)]
    mockShowMessageBox.mockResolvedValue({ response: 1 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    const choice = await showRuntimeMissingDialog(missingServices);

    expect(choice).toBe('open-fix-doc');
    expect(mockOpenPath).toHaveBeenCalledWith('/install/resources/win7-fix/sage-win7-fix.md');
    // showItemInFolder 不该被触发 (用户点的是「查看修复文档」, 不是「打开修复脚本」)
    expect(mockShowItemInFolder).not.toHaveBeenCalled();
    expect(mockQuit).not.toHaveBeenCalled();
  });

  it('click "打开下载页" (patches-only 布局 response=0) → shell.openExternal 每个 URL 一次', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    const choice = await showRuntimeMissingDialog(missingPatches);

    expect(choice).toBe('open-downloads');
    expect(mockOpenExternal).toHaveBeenCalledWith('https://aka.ms/vc14/vc_redist.x64.exe');
    // patches-only 布局没「打开修复脚本」按钮, 不该触发 showItemInFolder
    expect(mockShowItemInFolder).not.toHaveBeenCalled();
  });

  it('cancelId (退出) → app.quit()', async () => {
    // services-only 布局: 5 个按钮, cancelId=4 是「退出」
    mockShowMessageBox.mockResolvedValue({ response: 4 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    const choice = await showRuntimeMissingDialog(missingServices);

    expect(choice).toBe('quit');
    expect(mockQuit).toHaveBeenCalled();
  });

  it('logs error BEFORE dialog (崩溃时也有记录)', async () => {
    mockShowMessageBox.mockResolvedValue({ response: 0 });
    const { showRuntimeMissingDialog } = await import('../runtime-check');
    const { logger } = await import('../logger');
    await showRuntimeMissingDialog(missingPatches);

    // logger.error 必须在 dialog.showMessageBox 之前调用 (设计契约)
    expect(logger.error).toHaveBeenCalledWith(
      'main: runtime missing, showing dialog',
      expect.objectContaining({ missing: expect.any(Array) }),
    );
    expect(mockShowMessageBox).toHaveBeenCalled();
    const errorCallOrder = (logger.error as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0];
    const dialogCallOrder = mockShowMessageBox.mock.invocationCallOrder[0];
    expect(errorCallOrder).toBeLessThan(dialogCallOrder);
  });
});
