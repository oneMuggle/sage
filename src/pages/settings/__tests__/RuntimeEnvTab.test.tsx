/**
 * r111: RuntimeEnvTab UI 测试——探测/诊断/试跑三段状态机。
 *
 * runtimeApi 以 vi.mock 替身注入；组件挂载即自动探测+诊断（useEffect），
 * 文案为组件内硬编码中文（无 i18n 依赖）。
 *
 * 注意：探测成功 → 自动选中推荐运行时 → runProbe/runDiagnose 依赖变化触发
 * effect 重跑，面板会在 loading 与 ok 间闪断一次。所有动态断言一律用
 * findBy*（轮询到出现为止，默认 1s 不够时显式给 timeout），不用同步 getByText。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const probeMock = vi.fn();
const diagnoseMock = vi.fn();
const execMock = vi.fn();

vi.mock('../../../shared/api/runtimeApi', () => ({
  runtimeApi: {
    probe: (...args: unknown[]) => probeMock(...args),
    diagnose: (...args: unknown[]) => diagnoseMock(...args),
    exec: (...args: unknown[]) => execMock(...args),
  },
}));

import { RuntimeEnvTab } from '../RuntimeEnvTab';

const RUNTIME = {
  language: 'python',
  name: 'CPython',
  path: 'C:/py/python.exe',
  version: '3.11.5',
  source: 'system',
  is_default: true,
  is_compatible: true,
  compatibility_notes: [],
  capabilities: {
    can_execute: true,
    can_package_check: false,
    supports_stdin_source: true,
    supports_tempfile_source: true,
    notes: '',
  },
  diagnostics: [],
};

const OK_PROBE = {
  success: true,
  output: { runtimes: [RUNTIME], recommended: RUNTIME.path, errors: [] },
};
const OK_DIAGNOSE = {
  success: true,
  output: {
    manifests: [{ language: 'python' }],
    level: 'satisfied',
    recommended_runtime: RUNTIME.path,
    diagnostics: [{ code: 'PY_OK', severity: 'info', message: '就绪', remediation: '' }],
    probe_errors: [],
  },
};
const OK_EXEC = {
  success: true,
  output: {
    stdout: 'hello from Sage',
    stderr: '',
    exit_code: 0,
    timed_out: false,
    duration_seconds: 0.42,
    error: null,
    output_truncated: false,
    command: ['python', '-c', 'print(1)'],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  probeMock.mockResolvedValue(OK_PROBE);
  diagnoseMock.mockResolvedValue(OK_DIAGNOSE);
  execMock.mockResolvedValue(OK_EXEC);
});

describe('RuntimeEnvTab 探测面板', () => {
  it('加载中显示正在探测', () => {
    probeMock.mockReturnValue(new Promise(() => {}));
    render(<RuntimeEnvTab />);
    expect(screen.getByText('正在探测…')).toBeInTheDocument();
  });

  it('探测成功列出运行时并自动选中推荐项', async () => {
    render(<RuntimeEnvTab />);
    expect(await screen.findByText('3.11.5', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(await screen.findByText('推荐', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('C:/py/python.exe')).toBeInTheDocument();
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe(RUNTIME.path);
  });

  it('空运行时显示未探测到提示与错误详情', async () => {
    probeMock.mockResolvedValue({
      success: true,
      output: { runtimes: [], recommended: null, errors: ['py launcher missing'] },
    });
    render(<RuntimeEnvTab />);
    expect(await screen.findByText(/未探测到任何运行时/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/py launcher missing/)).toBeInTheDocument();
  });

  it('探测异常显示失败信息与重试按钮', async () => {
    probeMock.mockRejectedValue(new Error('ipc down'));
    render(<RuntimeEnvTab />);
    expect(await screen.findByText('探测失败: ipc down', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('重试')).toBeInTheDocument();
  });
});

describe('RuntimeEnvTab 诊断面板', () => {
  it('诊断成功显示满足度与诊断项', async () => {
    render(<RuntimeEnvTab />);
    expect(await screen.findByText('✓ 全部满足', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(await screen.findByText('PY_OK', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('推荐运行时: C:/py/python.exe')).toBeInTheDocument();
  });

  it('诊断失败显示失败信息', async () => {
    diagnoseMock.mockRejectedValue(new Error('diagnose down'));
    render(<RuntimeEnvTab />);
    expect(await screen.findByText('诊断失败: diagnose down', {}, { timeout: 5000 })).toBeInTheDocument();
  });
});

describe('RuntimeEnvTab 试跑', () => {
  it('探测成功后执行按钮可用', async () => {
    render(<RuntimeEnvTab />);
    const button = await screen.findByText('执行');
    await waitFor(() => expect(button).toBeEnabled());
  });

  it('执行成功展示退出码与 stdout', async () => {
    render(<RuntimeEnvTab />);
    const button = await screen.findByText('执行');
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByText(/退出码 0/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('hello from Sage')).toBeInTheDocument();
  });

  it('执行进入 running 态显示等待批准', async () => {
    execMock.mockReturnValue(new Promise(() => {}));
    render(<RuntimeEnvTab />);
    const button = await screen.findByText('执行');
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByText('等待用户批准…', {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it('权限拒绝显示拒绝文案', async () => {
    execMock.mockResolvedValue({ success: false, error: '权限拒绝: 需要 exec 审批' });
    render(<RuntimeEnvTab />);
    const button = await screen.findByText('执行');
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByText(/权限被拒绝:/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/需要 exec 审批/)).toBeInTheDocument();
  });

  it('exec 透传语言与运行时路径', async () => {
    render(<RuntimeEnvTab />);
    const button = await screen.findByText('执行');
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(execMock).toHaveBeenCalled());
    expect(execMock).toHaveBeenCalledWith(
      expect.objectContaining({ language: 'python', runtime_path: 'C:/py/python.exe' }),
    );
  });
});
