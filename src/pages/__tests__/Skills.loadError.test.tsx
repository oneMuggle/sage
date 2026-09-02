/**
 * Skills 页面 — 错误展示（不再吞掉）
 *
 * 背景：之前 Skills.tsx 的 loadSkills() 用裸 `catch {}` 把任何错误简化为
 * 固定字符串"加载技能列表失败"，401/500/网络断全部显示同一句话，用户无
 * 法区分"后端未启动"、"授权失效"、"内部异常"。本次修复要求：
 *
 * 1. 401（LocalAuthMiddleware 拒绝）→ 显示带状态码的明确提示，提示与
 *    记忆面板/编排看板的 401 文案区分（不再说"本地授权凭据无效或缺失"
 *    的后端内部文案，对用户用友好版本），便于用户识别为"凭据问题，请重启"。
 * 2. 其他错误 → 保留原始 message（含后端 detail），不再吞。
 * 3. 错误必须可见（无论是首次加载的整页 ErrorState 还是顶部 banner）。
 *
 * Skills.tsx 此前 catch 块直接 `setError('加载技能列表失败')` + `setSkills([])`。
 * 测试断言在修复后不再出现该字面字符串。
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import Skills from '../Skills';

const listMock = vi.fn();

vi.mock('../../shared/api', () => ({
  skillsApi: {
    list: () => listMock(),
    toggle: vi.fn(),
    execute: vi.fn(),
    listSlashCommands: vi.fn().mockResolvedValue([]),
    delete: vi.fn(),
    archive: vi.fn(),
    rescan: vi.fn(),
    importFiles: vi.fn(),
  },
}));

function renderSkills() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <Skills />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe('Skills page — surfaces real load error (不再吞掉)', () => {
  afterEach(() => {
    listMock.mockReset();
  });

  it('401 时不再吞掉错误, 显示带 HTTP 401 的友好提示（含"加载"语义 + 状态码）', async () => {
    // 模拟 main 进程抛的错误形态：message 含 "→ <code>: <detail>"
    // desktopInvoke 内部会用 STATUS_RE 解析出 status_code=401，
    // 然后 skillsApi.list() 的 catch 把 error 经 handleApiError 包成
    // ApiException（保留 message 字符串）。
    listMock.mockRejectedValueOnce(
      new Error(
        'Backend GET http://127.0.0.1:8765/api/v1/skills → 401: {"detail":"本地授权凭据无效或缺失"}',
      ),
    );

    renderSkills();

    // 错误必须可见：等待加载结束 + 错误态出现
    await waitFor(() => {
      const alert = screen.queryByRole('alert');
      expect(alert).not.toBeNull();
    });

    const alert = screen.getByRole('alert');
    const text = alert.textContent ?? '';

    // 关键回归点：之前的"加载技能列表失败"四字孤零零、无信息量
    expect(text).not.toBe('加载技能列表失败');
    // 新合约
    expect(text).toMatch(/401/);
    expect(text).toMatch(/加载/); // 仍然是"加载"语义,不是后端内部文案"本地授权凭据"
    expect(text).not.toMatch(/本地授权凭据/); // 不暴露后端内部 detail 给用户
  });

  it('非 401 错误保留原始 message（含后端 detail）', async () => {
    listMock.mockRejectedValueOnce(
      new Error(
        'Backend GET http://127.0.0.1:8765/api/v1/skills → 500: {"detail":"internal error: db pool exhausted"}',
      ),
    );

    renderSkills();

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeNull();
    });

    const alert = screen.getByRole('alert');
    const text = alert.textContent ?? '';
    expect(text).not.toBe('加载技能列表失败');
    expect(text).toMatch(/500/);
    expect(text).toMatch(/db pool exhausted/); // 后端 detail 必须保留
  });
});
