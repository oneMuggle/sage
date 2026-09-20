/**
 * r90: runtimeApi 单元测试——probe/diagnose/exec 的 camelCase 桥接映射与错误包装。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { runtimeApi } from '../runtimeApi';

beforeEach(() => {
  mockInvoke.mockReset();
});

const envelope = <T,>(data: T) => ({ success: true, data, error: null });

describe('runtimeApi', () => {
  it('probe() fills defaults for omitted request fields', async () => {
    mockInvoke.mockResolvedValueOnce(envelope({ runtimes: [] }));
    await runtimeApi.probe();
    expect(mockInvoke).toHaveBeenCalledWith('runtime_probe', {
      languages: null,
      includeTools: true,
      targetVersion: null,
      includePaths: null,
      workspaceRoot: null,
    });
  });

  it('probe() maps snake_case request fields to bridge keys', async () => {
    mockInvoke.mockResolvedValueOnce(envelope({ runtimes: [] }));
    await runtimeApi.probe({
      languages: ['python'],
      include_tools: false,
      target_version: '3.11',
      include_paths: ['C:/py'],
      workspace_root: 'C:/proj',
    });
    expect(mockInvoke).toHaveBeenCalledWith('runtime_probe', {
      languages: ['python'],
      includeTools: false,
      targetVersion: '3.11',
      includePaths: ['C:/py'],
      workspaceRoot: 'C:/proj',
    });
  });

  it('diagnose() maps project_root to projectRoot', async () => {
    mockInvoke.mockResolvedValueOnce(envelope({ required: [], missing: [] }));
    await runtimeApi.diagnose({ languages: ['node'], project_root: 'C:/proj' });
    expect(mockInvoke).toHaveBeenCalledWith('runtime_diagnose', {
      languages: ['node'],
      includeTools: true,
      targetVersion: null,
      projectRoot: 'C:/proj',
    });
  });

  it('exec() maps runtime_path/env_overrides and passes code', async () => {
    mockInvoke.mockResolvedValueOnce(
      envelope({ stdout: 'ok', stderr: '', exit_code: 0, duration_ms: 5 }),
    );
    await runtimeApi.exec({
      language: 'python',
      runtime_path: 'C:/py/python.exe',
      code: 'print(1)',
      cwd: 'C:/proj',
      timeout: 10,
      env_overrides: { FOO: '1' },
      workspace_root: 'C:/proj',
    });
    expect(mockInvoke).toHaveBeenCalledWith('runtime_exec', {
      language: 'python',
      runtimePath: 'C:/py/python.exe',
      code: 'print(1)',
      cwd: 'C:/proj',
      timeout: 10,
      envOverrides: { FOO: '1' },
      workspaceRoot: 'C:/proj',
    });
  });

  it('exec() omits optional fields when absent', async () => {
    mockInvoke.mockResolvedValueOnce(
      envelope({ stdout: '', stderr: '', exit_code: 0, duration_ms: 1 }),
    );
    await runtimeApi.exec({ language: 'python', runtime_path: 'py', code: 'x' });
    expect(mockInvoke).toHaveBeenCalledWith('runtime_exec', {
      language: 'python',
      runtimePath: 'py',
      code: 'x',
      cwd: null,
      timeout: null,
      envOverrides: null,
      workspaceRoot: null,
    });
  });

  it('wraps invoke rejection via handleApiError', async () => {
    mockInvoke.mockRejectedValueOnce({ message: 'boom', status: 500 });
    await expect(runtimeApi.probe()).rejects.toThrow();
  });
});
