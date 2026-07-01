import { test, expect } from '@playwright/test';

/**
 * 守卫 PR #88 (Sidebar 加 /skills 入口) 与 PR #91 (Skills 页 refresh + delete + auto-refresh)。
 * 验证：(1) Sidebar 渲染 "技能" link (2) 点击导航到 /skills (3) /skills 页加载 skill cards + 新增的 Refresh / toggle 控件。
 *
 * 模式参考 e2e/wiki-folder-picker.spec.ts: addInitScript 桩化 window.electronAPI
 * (vite dev server 没真实 preload), 让 list_skills 返回 sample skills。
 */

interface Skill {
  name: string;
  description: string;
  triggers: string[];
  parameters: Record<string, unknown>;
  examples: string[];
  enabled: boolean;
  usage_count: number;
  source: 'builtin' | 'skillmd';
}

interface SidebarSkillsMockWindow {
  electronAPI?: {
    invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
    listen: () => Promise<() => void>;
    windowControls?: Record<string, unknown>;
  };
  __mockSkills?: Skill[];
  __mockSkillCalls?: string[];
}

const SAMPLE_SKILLS: Skill[] = [
  {
    name: 'web-search',
    description: 'Search the web',
    triggers: ['search'],
    parameters: {},
    examples: [],
    enabled: true,
    usage_count: 5,
    source: 'skillmd',
  },
  {
    name: 'coder',
    description: 'Write code',
    triggers: ['code'],
    parameters: {},
    examples: [],
    enabled: true,
    usage_count: 12,
    source: 'builtin',
  },
];

test.describe('Sidebar — /skills navigation', () => {
  test.beforeEach(async ({ page }) => {
    // 浏览器侧运行 init script, 不能闭包外部 TS const。把 SAMPLE_SKILLS 序列化
    // 成 JSON 字符串注入, 浏览器内 JSON.parse 取回。
    const skillsJson = JSON.stringify(SAMPLE_SKILLS);
    await page.addInitScript(function (serialized: string) {
      const skills = JSON.parse(serialized);
      const w = window as unknown as SidebarSkillsMockWindow;
      w.__mockSkillCalls = [];
      w.electronAPI = {
        invoke: (cmd: string) => {
          if (cmd === 'list_skills') return Promise.resolve(skills);
          if (cmd === 'list_slash_commands') return Promise.resolve({ commands: [] });
          if (cmd === 'list_sessions') return Promise.resolve([]);
          if (cmd === 'load_sessions') return Promise.resolve([]);
          if (cmd === 'toggle_skill') return Promise.resolve(null);
          return Promise.resolve(null);
        },
        listen: () => Promise.resolve(() => {}),
        windowControls: {} as never,
      };
    }, skillsJson);
  });

  test('Sidebar shows a 技能 link with href /skills', async ({ page }) => {
    await page.goto('/chat');

    const skillsLink = page.getByRole('link', { name: '技能' });
    await expect(skillsLink).toBeVisible();
    await expect(skillsLink).toHaveAttribute('href', '/skills');
  });

  test('clicking the 技能 nav link navigates to /skills and renders the heading', async ({
    page,
  }) => {
    await page.goto('/chat');

    await page.getByRole('link', { name: '技能' }).click();

    await expect(page).toHaveURL(/\/skills$/);
    // Skills 页头部 h2 (PR #88 + PR #91)
    await expect(page.getByRole('heading', { name: '技能' })).toBeVisible();
  });

  test('/skills page loads skill cards and renders Refresh + auto-refresh controls', async ({
    page,
  }) => {
    await page.goto('/skills');

    // 等待 skillApi.list() mock 返回并由组件渲染
    await expect(page.getByText('web-search')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('coder')).toBeVisible();

    // PR #90 的 Refresh 按钮 (aria-label="刷新技能列表")
    await expect(page.getByRole('button', { name: '刷新技能列表' })).toBeVisible();
    // PR #91 的 auto-refresh toggle (role="switch")
    await expect(page.getByRole('switch', { name: /自动刷新/i })).toBeVisible();
  });
});
