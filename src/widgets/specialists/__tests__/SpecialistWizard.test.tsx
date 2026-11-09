/**
 * M1-E 回归：新建专家向导步骤校验。
 *
 * 修复前 bug：第一步「下一步」按钮同时被第二步的人设校验禁用 —— 新建时
 * 人设六段全空 → `step2Error` 非空 → 第一步永远无法前进（死锁）。
 * 覆盖：按当前步骤禁用、内联错误提示、名称/ID/人设校验、可正常进入第二步。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { defaultSpecialistTools } from '../../../entities/specialist/toolCapabilities';
import type { AgentProfile } from '../../../shared/api';
import { SpecialistWizard } from '../SpecialistWizard';

const mockCreate = vi.fn();
const mockUpdate = vi.fn();
const mockSkillsList = vi.fn();

vi.mock('../../../shared/api', () => ({
  agentsApi: {
    create: (...args: unknown[]) => mockCreate(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
  },
  skillsApi: {
    list: () => mockSkillsList(),
  },
}));

// 高级白名单编辑器会拉插件快照；向导测试不覆盖该面板，固定为空即可。
vi.mock('../../../shared/api/pluginClient', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/pluginClient')>(
    '../../../shared/api/pluginClient',
  );
  return {
    ...actual,
    pluginClient: {
      ...actual.pluginClient,
      runtimeTools: vi.fn().mockResolvedValue([]),
      list: vi.fn().mockResolvedValue([]),
    },
  };
});

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderWizard() {
  return render(<SpecialistWizard open onOpenChange={vi.fn()} onSaved={vi.fn()} />);
}

function renderEditWizard(editingAgent: AgentProfile) {
  return render(
    <SpecialistWizard open onOpenChange={vi.fn()} onSaved={vi.fn()} editingAgent={editingAgent} />,
  );
}

function makeAgent(tools: string[]): AgentProfile {
  return {
    id: 'specialist-legacy',
    name: '旧专家',
    role: 'specialist',
    description: '',
    system_prompt: '## 身份\n旧人设',
    skills: [],
    tools,
    memory_access: [],
    persona_ui: { avatar: '', tagline: '' },
    permission_mode: 'read_only',
  } as unknown as AgentProfile;
}

function nextButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: '下一步' }) as HTMLButtonElement;
}

/** 第一步填名称 → 第二步填人设 → 停在第三步「能力与权限」。 */
async function reachAbilityStep() {
  fireEvent.change(screen.getByTestId('specialist-wizard-name'), {
    target: { value: '写作专家' },
  });
  fireEvent.click(nextButton());
  const identity = await screen.findByTestId('persona-section-identity');
  fireEvent.change(identity, { target: { value: '你是一位写作助手' } });
  fireEvent.click(nextButton());
  await screen.findByTestId('specialist-wizard-pack-grid');
}

async function advanceToPreviewAndSave(saveLabel: '创建专家' | '保存更改') {
  fireEvent.click(nextButton());
  fireEvent.click(await screen.findByRole('button', { name: saveLabel }));
}

describe('SpecialistWizard 步骤校验（回归）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSkillsList.mockResolvedValue([]);
    mockCreate.mockResolvedValue(undefined);
    mockUpdate.mockResolvedValue(undefined);
  });

  it('第一步不被第二步人设校验误禁用，填名称后可进入第二步', async () => {
    renderWizard();

    // 名称未填 → 第一步自身校验禁用
    expect(nextButton()).toBeDisabled();
    expect(screen.getByTestId('specialist-wizard-step1-error')).toHaveTextContent('请输入专家名称');

    fireEvent.change(screen.getByTestId('specialist-wizard-name'), {
      target: { value: '写作专家' },
    });

    // 关键回归点：人设仍为空，但「下一步」必须可用（此前死锁于此）
    expect(nextButton()).toBeEnabled();
    fireEvent.click(nextButton());

    expect(await screen.findByTestId('persona-section-identity')).toBeInTheDocument();
  });

  it('第二步人设全空时禁用并提示，填写一段后启用', async () => {
    renderWizard();
    fireEvent.change(screen.getByTestId('specialist-wizard-name'), {
      target: { value: '写作专家' },
    });
    fireEvent.click(nextButton());

    const identity = await screen.findByTestId('persona-section-identity');
    expect(nextButton()).toBeDisabled();
    expect(screen.getByTestId('specialist-wizard-step2-error')).toHaveTextContent(
      '至少填写一段人设',
    );

    fireEvent.change(identity, { target: { value: '你是一位写作助手' } });
    expect(nextButton()).toBeEnabled();
  });

  it('非法专家 ID 时禁用第一步并显示内联错误', async () => {
    renderWizard();
    fireEvent.change(screen.getByTestId('specialist-wizard-name'), {
      target: { value: '写作专家' },
    });
    fireEvent.change(screen.getByTestId('specialist-wizard-id'), {
      target: { value: '中文ID' },
    });

    expect(nextButton()).toBeDisabled();
    expect(await screen.findByTestId('specialist-wizard-step1-error')).toHaveTextContent(
      'ID 必须以字母/数字开头',
    );
  });
});

describe('SpecialistWizard 工具选择保存', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSkillsList.mockResolvedValue([]);
    mockCreate.mockResolvedValue(undefined);
    mockUpdate.mockResolvedValue(undefined);
  });

  it('新建专家默认携带开箱可用的工具，而不是空数组', async () => {
    renderWizard();
    await reachAbilityStep();
    await advanceToPreviewAndSave('创建专家');

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const payload = mockCreate.mock.calls[0][0] as { tools: string[] };
    expect(payload.tools).toEqual(defaultSpecialistTools());
    expect(payload.tools.length).toBeGreaterThan(0);
    expect(payload.tools).toContain('read_file');
  });

  it('勾选能力包后保存会把包内工具并入 tools', async () => {
    renderWizard();
    await reachAbilityStep();

    fireEvent.click(screen.getByTestId('specialist-wizard-pack-file-write'));
    await advanceToPreviewAndSave('创建专家');

    const payload = mockCreate.mock.calls[0][0] as { tools: string[] };
    expect(payload.tools).toContain('write_file');
    expect(payload.tools).toContain('edit_file');
    expect(payload.tools).toContain('read_file');
  });

  it('选择「纯对话」后保存 tools 为空数组并提示后果', async () => {
    renderWizard();
    await reachAbilityStep();

    fireEvent.click(screen.getByTestId('specialist-wizard-no-tools'));
    expect(screen.queryByTestId('specialist-wizard-pack-grid')).not.toBeInTheDocument();

    await advanceToPreviewAndSave('创建专家');

    const payload = mockCreate.mock.calls[0][0] as { tools: string[] };
    expect(payload.tools).toEqual([]);
  });

  it('编辑已有专家时原样携带其工具列表', async () => {
    renderEditWizard(makeAgent(['read_file', 'bash']));
    fireEvent.click(await screen.findByRole('button', { name: '下一步' }));
    fireEvent.click(nextButton());
    await screen.findByTestId('specialist-wizard-pack-grid');

    const bashPack = screen.getByTestId('specialist-wizard-pack-file-read');
    expect(bashPack).toBeInTheDocument();

    await advanceToPreviewAndSave('保存更改');

    expect(mockUpdate).toHaveBeenCalledTimes(1);
    const payload = mockUpdate.mock.calls[0][1] as { tools: string[] };
    expect(payload.tools).toEqual(['read_file', 'bash']);
  });

  it('历史上 tools 为空的专家保持纯对话，直到用户显式勾选', async () => {
    renderEditWizard(makeAgent([]));
    fireEvent.click(await screen.findByRole('button', { name: '下一步' }));
    fireEvent.click(nextButton());
    expect(await screen.findByTestId('specialist-wizard-no-tools')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.queryByTestId('specialist-wizard-pack-grid')).not.toBeInTheDocument();

    await advanceToPreviewAndSave('保存更改');

    const payload = mockUpdate.mock.calls[0][1] as { tools: string[] };
    expect(payload.tools).toEqual([]);
  });
});
