/**
 * M1-E 回归：新建专家向导步骤校验。
 *
 * 修复前 bug：第一步「下一步」按钮同时被第二步的人设校验禁用 —— 新建时
 * 人设六段全空 → `step2Error` 非空 → 第一步永远无法前进（死锁）。
 * 覆盖：按当前步骤禁用、内联错误提示、名称/ID/人设校验、可正常进入第二步。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderWizard() {
  return render(<SpecialistWizard open onOpenChange={vi.fn()} onSaved={vi.fn()} />);
}

function nextButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: '下一步' }) as HTMLButtonElement;
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
