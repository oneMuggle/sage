// @vitest-environment jsdom
/**
 * SkillsTab 单元测试 — T-3 技能脚本执行开关（fail-closed）+ T-4a 技能目录
 *
 * 测试范围：
 * 1. 渲染（标签 / 描述 / 控件 testid）
 * 2. 读取口径：仅 "1" 开启；null / "0" / 其它值 / 读取异常一律关闭
 * 3. 写入口径：开启写 "1"，关闭写 "0"；技能目录写去空白后的路径
 * 4. 保存回执：写入失败时开关不翻转、错误可见（不再静默吞掉）
 * 5. 审计快照 / JSON helper
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { SkillsTab, formatSkillsTabAuditJson, formatSkillsTabAuditSnapshot } from '../SkillsTab';

// ==================== Mocks ====================

const mocks = vi.hoisted(() => ({
  getPreferenceStrict: vi.fn(),
  setPreferenceStrict: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../../shared/api/settingsClient', () => ({
  LOAD_TIMEOUT_MS: 5000,
  settingsClient: {
    getPreferenceStrict: (...args: unknown[]) => mocks.getPreferenceStrict(...args),
    setPreferenceStrict: (...args: unknown[]) => mocks.setPreferenceStrict(...args),
  },
}));

/** 按 key 返回不同值，便于逐个断言 fail-closed 分支。 */
function stubPreferences(scriptValue: string | null, dirValue: string | null): void {
  mocks.getPreferenceStrict.mockImplementation((key: string) =>
    Promise.resolve(key === 'allow_skill_scripts' ? scriptValue : dirValue),
  );
}

function renderTab(): void {
  render(
    <I18nProvider>
      <SkillsTab />
    </I18nProvider>,
  );
}

function toggle(): HTMLButtonElement {
  return screen.getByTestId('settings-skill-script-toggle') as HTMLButtonElement;
}

function dirInput(): HTMLInputElement {
  return screen.getByTestId('settings-skills-dir-input') as HTMLInputElement;
}

beforeEach(() => {
  mocks.getPreferenceStrict.mockReset();
  mocks.setPreferenceStrict.mockClear();
  mocks.setPreferenceStrict.mockResolvedValue(undefined);
  stubPreferences(null, null);
});

// ==================== Tests ====================

describe('SkillsTab — 渲染', () => {
  it('渲染脚本执行开关与技能目录控件', async () => {
    renderTab();

    expect(screen.getByText('允许执行技能脚本')).toBeTruthy();
    expect(screen.getByText(/SKILL.md 中的脚本/)).toBeTruthy();
    expect(screen.getByText('技能目录')).toBeTruthy();

    await waitFor(() => {
      expect(toggle()).toBeTruthy();
      expect(dirInput()).toBeTruthy();
    });
  });

  it('audit copy controls moved to the audit export tab (P3)', () => {
    // P3: 页内「复制审计快照/JSON」按钮已收敛到「审计导出」tab —— SkillsTab 不再渲染这两枚按钮。
    // formatXxxAuditSnapshot / formatXxxAuditJson 由 settingsAuditExports.ts 集中消费,
    // 其实在 AuditExportTab 单元测试里断言。
  });
});

describe('SkillsTab — T-3 读取口径（fail-closed）', () => {
  it('值为 "1" 时开关为开启态', async () => {
    stubPreferences('1', null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('true');
    });
  });

  it('值为 null 时开关为关闭态（缺省关闭）', async () => {
    stubPreferences(null, null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });
  });

  it('值为 "0" 时开关为关闭态', async () => {
    stubPreferences('0', null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });
  });

  it('值为其它字符串（如 "true"）时开关为关闭态', async () => {
    stubPreferences('true', null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });
  });

  it('读取抛错时开关为关闭态（fail-closed）', async () => {
    mocks.getPreferenceStrict.mockRejectedValue(new Error('boom'));
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });
    // 读取失败对用户可见（不是静默吞掉）；两个偏好都读失败 → 两条告警
    await waitFor(() => {
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
    });
  });
});

describe('SkillsTab — T-3 写入口径', () => {
  it('关闭态点击开关写入 "1"', async () => {
    stubPreferences('0', null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });

    fireEvent.click(toggle());

    await waitFor(() => {
      expect(mocks.setPreferenceStrict).toHaveBeenCalledWith('allow_skill_scripts', '1', 'ui');
    });
    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('true');
    });
  });

  it('开启态点击开关写入 "0"', async () => {
    stubPreferences('1', null);
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('true');
    });

    fireEvent.click(toggle());

    await waitFor(() => {
      expect(mocks.setPreferenceStrict).toHaveBeenCalledWith('allow_skill_scripts', '0', 'ui');
    });
    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });
  });

  it('写入失败时开关不翻转且错误可见', async () => {
    stubPreferences('0', null);
    mocks.setPreferenceStrict.mockRejectedValue(new Error('backend down'));
    renderTab();

    await waitFor(() => {
      expect(toggle().getAttribute('aria-checked')).toBe('false');
    });

    fireEvent.click(toggle());

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy();
    });
    // 后端未确认 → UI 不得显示已开启
    expect(toggle().getAttribute('aria-checked')).toBe('false');
  });
});

describe('SkillsTab — T-4a 技能目录', () => {
  it('回显已保存的目录', async () => {
    stubPreferences(null, '/opt/skills');
    renderTab();

    await waitFor(() => {
      expect(dirInput().value).toBe('/opt/skills');
    });
  });

  it('修改目录时写入去空白后的路径', async () => {
    stubPreferences(null, '');
    renderTab();

    await waitFor(() => {
      expect(dirInput().value).toBe('');
    });

    fireEvent.change(dirInput(), { target: { value: '  /opt/skills  ' } });
    fireEvent.blur(dirInput());

    await waitFor(() => {
      expect(mocks.setPreferenceStrict).toHaveBeenCalledWith(
        'skills_dir',
        '/opt/skills',
        'general',
      );
    });
    await waitFor(() => {
      expect(dirInput().value).toBe('/opt/skills');
    });
  });

  it('逐键输入不写后端，失焦时才提交一次', async () => {
    stubPreferences(null, '');
    renderTab();

    await waitFor(() => {
      expect(dirInput().value).toBe('');
    });

    fireEvent.change(dirInput(), { target: { value: '/opt' } });
    fireEvent.change(dirInput(), { target: { value: '/opt/skills' } });

    // 中间态不落库
    expect(mocks.setPreferenceStrict).not.toHaveBeenCalled();

    fireEvent.blur(dirInput());

    await waitFor(() => {
      expect(mocks.setPreferenceStrict).toHaveBeenCalledTimes(1);
    });
    expect(mocks.setPreferenceStrict).toHaveBeenCalledWith('skills_dir', '/opt/skills', 'general');
  });

  it('回车提交目录改动', async () => {
    stubPreferences(null, '');
    renderTab();

    await waitFor(() => {
      expect(dirInput().value).toBe('');
    });

    fireEvent.change(dirInput(), { target: { value: '/opt/skills' } });
    fireEvent.keyDown(dirInput(), { key: 'Enter' });

    await waitFor(() => {
      expect(mocks.setPreferenceStrict).toHaveBeenCalledWith(
        'skills_dir',
        '/opt/skills',
        'general',
      );
    });
  });
});

describe('SkillsTab — 审计导出 helper', () => {
  it('formatSkillsTabAuditSnapshot 反映开关与目录', () => {
    const snapshot = formatSkillsTabAuditSnapshot({
      allow_skill_scripts: true,
      skills_dir: '/opt/skills',
    });
    expect(snapshot).toContain('# 技能设置审计快照');
    expect(snapshot).toContain('允许执行技能脚本: 开启');
    expect(snapshot).toContain('技能目录: /opt/skills');
  });

  it('formatSkillsTabAuditSnapshot 对空目录显示缺省路径', () => {
    const snapshot = formatSkillsTabAuditSnapshot({
      allow_skill_scripts: false,
      skills_dir: '',
    });
    expect(snapshot).toContain('允许执行技能脚本: 关闭');
    expect(snapshot).toContain('缺省 (~/.sage/skills)');
  });

  it('formatSkillsTabAuditJson 输出可解析 JSON', () => {
    const json = JSON.parse(
      formatSkillsTabAuditJson({ allow_skill_scripts: true, skills_dir: '/opt/skills' }),
    );
    expect(json).toEqual({
      allow_skill_scripts: true,
      skills_dir: '/opt/skills',
    });
  });

  it('formatSkillsTabAuditJson 对空目录输出空字符串', () => {
    const json = JSON.parse(
      formatSkillsTabAuditJson({ allow_skill_scripts: false, skills_dir: '' }),
    );
    expect(json).toEqual({ allow_skill_scripts: false, skills_dir: '' });
  });
});
