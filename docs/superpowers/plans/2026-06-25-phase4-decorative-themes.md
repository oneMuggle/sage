# Phase 4 — 装饰性主题（Decorative Themes）

> **Status:** Draft
> **Date:** 2026-06-25
> **Branch:** `feat/ui-optimization-phase3` (working branch) → continue Phase 4 work
> **Spec:** `docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md` (Phase 4 section)
> **FSD Layer:** `entities/theme` + `features/theme` + `pages/settings`
> **Prior Phase:** Phase 3 (CSS 主题存储 + ThemeProvider) — already merged

---

## Goal

在 Phase 3 已落地的 CSS 主题系统之上，新增 5 套"装饰性"主题预设（Mint Blue / Sakura / Cyber Neon / Midnight Amber / Parchment），并把设置页主题选择器从单色圆点列表升级为"封面图 + 主题名 + 描述"的网格画廊视图。

**用户故事：**
> 作为 Sage 用户，我希望在设置 → 主题里能直接看到每个主题长什么样（封面图预览），而不只是看一个色块圆点；并能从 6 套基础主题 + 5 套装饰主题里挑一个我喜欢的。

**验收标准：**
- 设置页出现 11 套主题（6 基础 + 5 装饰），以 240×160 封面图卡片网格展示
- 5 张 SVG 封面图 < 2KB，风格统一（极简单色 + 几何），无渐变/阴影
- 点击装饰主题卡片，主题色立即应用（与基础主题相同的切换体验）
- 封面图加载失败时，自动回退到该主题的渐变色占位（不破图）
- i18n 完整（中英文）覆盖 5 套装饰主题名 + Gallery 相关文案
- 整体测试覆盖率 ≥ 82%，ThemeGallery 组件覆盖率 ≥ 85%
- **不修改** 现有 6 套基础主题的 ID / 颜色 / 描述（向后兼容）
- **不新增** 任何 npm 包

---

## Architecture

### FSD 分层与依赖图

```
┌─────────────────────────────────────────────┐
│ pages/settings/ThemeSelector.tsx            │  ← 升级为 Gallery 视图（仅修改）
│   └─ imports: features/theme/ThemeGallery   │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ features/theme/ThemeGallery.tsx             │  ← 新建（薄壳组件）
│   └─ imports: entities/theme/presets        │
│            + entities/theme/decorative-     │
│              presets                        │
│            + features/theme/ThemeCover      │
└─────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────────────┐ ┌──────────────────────────┐
│ features/theme/      │ │ entities/theme/          │
│   ThemeCover.tsx     │ │   decorative-presets.ts  │ ← 新建
│  (封面图组件,        │ │  (5 套装饰主题常量 +     │
│   带 onError 降级)   │ │   DecorativeTheme 类型)  │
└──────────────────────┘ └──────────────────────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │ entities/theme/      │
                     │   presets.ts         │ ← 可能微调: 导出
                     │  (6 套基础主题)       │   union 主题类型
                     └──────────────────────┘

┌─────────────────────────────────────────────┐
│ public/themes/covers/*.svg                  │ ← 新建 5 张 SVG
│   (Vite 默认 public 静态资源, base:'./'    │
│    兼容 Electron file:// 加载)              │
└─────────────────────────────────────────────┘
```

### 主题数据流

```
用户点击装饰主题卡片
  └─> ThemeGallery 调用 useTheme().setPresetId(decorativeId)
        └─> ThemeProvider.setPresetId
              ├─> getThemeById(decorativeId)  // 6 套基础 + 5 套装饰统一查找
              ├─> applyThemeColors(colors)    // 设置 --color-* CSS 变量
              └─> saveThemePreset(id)         // 持久化
```

### 关键设计决策

1. **不破坏 `presets.ts` 的现有 API** — `getThemeById` 改为同时查 `themePresets` 和 `decorativePresets`，向后兼容。
2. **SVG 放在 `public/themes/covers/`** — Vite 默认静态目录，`base: './'`（Electron 兼容）下可直接 `<img src="/themes/covers/xxx.svg">` 访问。
3. **封面图降级用 CSS 渐变** — 不引入占位图文件；用主题自身的 `colors.primary` + `colors.accent` 拼 `linear-gradient` 兜底。
4. **`decorative-presets.ts` 独立文件** — 与 `presets.ts` 解耦，6 套基础主题零改动；统一通过 `getThemeById` 暴露给消费方。

---

## Tech Stack

| 类别 | 选型 | 备注 |
|------|------|------|
| Framework | React 18.2 + TypeScript 5 | 严格模式（tsconfig strict: true） |
| 测试 | Vitest 1.6 + Testing Library 16 | jsdom 环境；`npm run test:run` |
| 样式 | Tailwind CSS（已有 class 名） | 沿用项目现有 class（如 `bg-bg-hover`、`border-border`） |
| 静态资源 | Vite `public/` 目录 | 路径 `/themes/covers/*.svg` |
| i18n | 现有 `useI18n` hook | 翻译键加在 `zh.ts` + `en.ts` |
| 状态 | 现有 `useTheme` hook | 不新增 store |
| Lint | ESLint + Prettier | 提交前 `npm run lint` |

**不引入：** `@svgr/webpack`、`vite-plugin-svgr`、图标库、动画库（项目内 `motion` 已有但本 phase 不用）。

---

## Global Constraints

### 通用约束（贯穿所有 Task）

- **绝对路径：** 所有文件路径必须以 `/home/fz/project/sage/` 开头
- **FSD 严格：** `features/` 不能 import `pages/`；`entities/` 不能 import `features/` 或 `pages/`
- **TDD 严格：** 每个 Task 必须 RED（写测试并确认失败）→ GREEN（写实现）→ REFACTOR
- **commit 粒度：** 每个 Task 末尾一个 `git commit`，message 遵循 conventional commits
- **零 `any`：** 公共 API 必须显式类型；测试中可用 `as` 断言
- **不修改现有 6 套基础主题的 ID / 颜色 / 描述**（向后兼容）
- **不新增 npm 包**
- **不修改** `presets.ts` 中 6 套基础主题的 `colors` / `darkColors` 字面量
- **覆盖率目标：** ThemeGallery ≥ 85%；项目整体 ≥ 82%
- **SVG 单文件 < 2KB**（手写 SVG + 极简几何）
- **代码无 TODO/TBD/FIXME/占位符** — 每个代码块必须可直接运行

### 错误降级契约

| 场景 | 行为 |
|------|------|
| SVG 404 / 解析失败 | `ThemeCover` 显示该主题 primary→accent 的 `linear-gradient` 占位 + 主题名首字母 |
| 主题 ID 不存在 | `getThemeById` 返回 `undefined`；`setPresetId` 早返回（已存在逻辑） |
| localStorage 损坏 | 由 `loadThemePreset` 已有的 try-catch 兜底 |

---

## File Inventory

### 新建文件

| 路径 | 用途 | 估算行数 |
|------|------|---------|
| `/home/fz/project/sage/src/entities/theme/decorative-presets.ts` | 5 套装饰主题 + `DecorativeTheme` 类型 | ~150 |
| `/home/fz/project/sage/src/entities/theme/__tests__/decorative-presets.test.ts` | 装饰主题数据正确性测试 | ~50 |
| `/home/fz/project/sage/src/features/theme/ThemeCover.tsx` | 封面图组件（带 onError 降级） | ~70 |
| `/home/fz/project/sage/src/features/theme/__tests__/ThemeCover.test.tsx` | 封面图组件测试 | ~80 |
| `/home/fz/project/sage/src/features/theme/ThemeGallery.tsx` | 网格画廊视图组件 | ~80 |
| `/home/fz/project/sage/src/features/theme/__tests__/ThemeGallery.test.tsx` | Gallery 组件测试 | ~120 |
| `/home/fz/project/sage/public/themes/covers/mint-blue.svg` | 薄荷蓝封面 | ~30 |
| `/home/fz/project/sage/public/themes/covers/sakura.svg` | 樱花粉封面 | ~30 |
| `/home/fz/project/sage/public/themes/covers/cyber-neon.svg` | Cyber Neon 封面 | ~30 |
| `/home/fz/project/sage/public/themes/covers/midnight-amber.svg` | 深夜琥珀封面 | ~30 |
| `/home/fz/project/sage/public/themes/covers/parchment.svg` | 羊皮纸封面 | ~30 |

### 修改文件

| 路径 | 变更内容 |
|------|---------|
| `/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx` | 改为渲染 `<ThemeGallery />`（内部用所有主题） |
| `/home/fz/project/sage/src/entities/theme/presets.ts` | 扩展 `getThemeById` 同时查装饰主题（仅改函数体） |
| `/home/fz/project/sage/src/shared/lib/i18n/zh.ts` | 新增 5 主题名 + Gallery 翻译键 |
| `/home/fz/project/sage/src/shared/lib/i18n/en.ts` | 新增 5 主题名 + Gallery 翻译键 |

### 不修改文件（明确声明）

- `src/app/providers/ThemeProvider.tsx` — 已支持任意 `getThemeById` 返回的主题
- `src/app/providers/useTheme.ts` — Context 接口不变
- 6 套基础主题的 `colors` / `darkColors` 字面量

---

## Tasks Overview

| # | Task | 预估时间 | 依赖 |
|---|------|---------|------|
| 1 | 添加 i18n 翻译键（中英文） | 5 min | — |
| 2 | 创建 SVG 封面图 × 5 | 10 min | — |
| 3 | 创建 `decorative-presets.ts` + 测试 | 10 min | — |
| 4 | 修改 `presets.ts` 的 `getThemeById` + 测试 | 5 min | 3 |
| 5 | 创建 `ThemeCover.tsx` + 测试 | 10 min | 3 |
| 6 | 创建 `ThemeGallery.tsx` + 测试 | 15 min | 3, 5 |
| 7 | 升级 `ThemeSelector.tsx` 集成 Gallery | 5 min | 6 |
| 8 | 覆盖率验证 + 端到端冒烟 | 10 min | 1-7 |

---

## Task 1 — 添加 i18n 翻译键（中英文）

**Files:**
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`
- Modify: `/home/fz/project/sage/src/shared/lib/i18n/en.ts`

**Interfaces:**
- Consumes: 无（纯数据新增）
- Produces: 12 个新 `TranslationKey`
  - `theme.name.mint_blue`、`theme.name.sakura`、`theme.name.cyber_neon`、`theme.name.midnight_amber`、`theme.name.parchment`
  - `theme.desc.mint_blue`、`theme.desc.sakura`、`theme.desc.cyber_neon`、`theme.desc.midnight_amber`、`theme.desc.parchment`
  - `theme.gallery.section_basic`、`theme.gallery.section_decorative`

### Step 1.1：在 zh.ts 添加装饰主题翻译键

**Goal:** 中文翻译文件加 12 个新键。

完整新文件内容（替换原文件 `/home/fz/project/sage/src/shared/lib/i18n/zh.ts`）：

```typescript
/**
 * 中文翻译 — 默认语言
 *
 * 键使用点分隔的命名空间: sidebar.new_chat, chat.title, settings.general ...
 */
export const zh = {
  // ─── 侧边栏 ───────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': '对话',
  'sidebar.nav.memory': '记忆',
  'sidebar.nav.knowledge': '知识库',
  'sidebar.nav.agents': '智能体',
  'sidebar.nav.skills': '技能',
  'sidebar.nav.settings': '设置',
  'sidebar.recent': '最近对话',
  'sidebar.new_chat': '新对话',
  'sidebar.status.connected': '已连接',
  'sidebar.status.not_configured': '未配置',
  'sidebar.status.error': '连接失败',
  'sidebar.status.latency': '延迟',
  'sidebar.empty': '暂无对话记录',

  // ─── 聊天页 ───────────────────────
  'chat.title': '对话',
  'chat.new_session': '+ 新对话',
  'chat.placeholder': '输入消息...',
  'chat.send': '发送',
  'chat.stop': '停止',
  'chat.config_warning': '未配置 API 端点或对话模型',
  'chat.config_warning_action': '前往设置',
  'chat.loading': '正在加载对话...',
  'chat.welcome': '欢迎使用 Sage',
  'chat.welcome_sub': '开始一段新对话吧',
  'chat.hint':
    'Sage 会记住你的项目信息，无需重复说明上下文 · 支持 Markdown 语法 · 点击知识库按钮多选文档作为上下文引用',
  'chat.memory_applied': '条记忆已应用',
  'chat.copy': '复制',
  'chat.copied': '已复制',
  'chat.delete_confirm': '确定要删除这个会话吗？',

  // ─── 文件上传 ─────────────────────
  'chat.drop_files': '拖放文件到此处',
  'chat.attach_image': '插入图片',
  'chat.attach_file': '附加文件',
  'chat.knowledge_ref': '引用知识库',
  'chat.knowledge_docs': '引用知识库文档',

  // ─── Slash 命令 ───────────────────
  'slash.help': '帮助',
  'slash.help_desc': '显示可用命令列表',
  'slash.clear': '清空对话',
  'slash.clear_desc': '清空当前会话的所有消息',
  'slash.search': '搜索',
  'slash.search_desc': '使用 /search 后输入搜索内容',
  'slash.summarize': '总结',
  'slash.summarize_desc': '总结当前对话内容',
  'slash.translate': '翻译',
  'slash.translate_desc': '翻译上一条消息',
  'slash.compact': '压缩上下文',
  'slash.compact_desc': '压缩当前对话上下文',

  // ─── 命令面板 ─────────────────────
  'cmd.title': '命令面板',
  'cmd.placeholder': '输入命令或搜索...',
  'cmd.empty': '无匹配结果',
  'cmd.nav': '导航',
  'cmd.actions': '操作',
  'cmd.sessions': '最近会话',
  'cmd.new_chat': '新建对话',
  'cmd.new_chat_desc': '创建一个新的对话会话',
  'cmd.toggle_theme': '切换主题',
  'cmd.toggle_theme_desc': '在亮色/暗色之间切换',
  'cmd.hint_nav': '↑↓ 导航',
  'cmd.hint_select': '↵ 选择',
  'cmd.hint_close': 'esc 关闭',
  'cmd.messages': '条消息',

  // ─── 设置页 ───────────────────────
  'settings.title': '设置',
  'settings.tab.general': '通用',
  'settings.tab.endpoints': '端点',
  'settings.tab.models': '模型',
  'settings.tab.memory': '记忆',
  'settings.tab.network': '网络',
  'settings.tab.evolution': '进化',
  'settings.section.theme': '主题',
  'settings.section.appearance': '外观',
  'settings.section.chat': '对话',
  'settings.section.data': '数据',

  // ─── 装饰主题 ───────────────────
  'theme.name.mint_blue': '薄荷蓝',
  'theme.name.sakura': '樱花粉',
  'theme.name.cyber_neon': 'Cyber Neon',
  'theme.name.midnight_amber': '深夜琥珀',
  'theme.name.parchment': '羊皮纸',
  'theme.desc.mint_blue': '清新的薄荷绿色调，温和不刺眼',
  'theme.desc.sakura': '温柔的樱花粉色，浪漫春日感',
  'theme.desc.cyber_neon': '霓虹紫粉，未来科技感',
  'theme.desc.midnight_amber': '深色背景配琥珀高亮，长时间阅读友好',
  'theme.desc.parchment': '复古羊皮纸纹理，文学与写作场景',
  'theme.gallery.section_basic': '基础主题',
  'theme.gallery.section_decorative': '装饰主题',

  // ─── 通用 ─────────────────────────
  'common.skip_to_content': '跳到主内容',
  'common.delete': '删除',
  'common.cancel': '取消',
  'common.confirm': '确定',
  'common.save': '保存',
  'common.loading': '加载中...',
  'common.error': '出错',
  'common.retry': '重试',

  // ─── 时间分组 ─────────────────────
  'time.today': '今天',
  'time.yesterday': '昨天',
  'time.this_week': '本周',
  'time.earlier': '更早',
} as const;

export type TranslationKey = keyof typeof zh;
```

### Step 1.2：在 en.ts 添加装饰主题翻译键

**Goal:** 英文翻译文件加 12 个新键。

完整新文件内容（替换原文件 `/home/fz/project/sage/src/shared/lib/i18n/en.ts`）：

```typescript
/**
 * English translations
 */
import type { TranslationKey } from './zh';

export const en: Record<TranslationKey, string> = {
  // ─── Sidebar ──────────────────────
  'sidebar.brand': 'Sage',
  'sidebar.nav.chat': 'Chat',
  'sidebar.nav.memory': 'Memory',
  'sidebar.nav.knowledge': 'Knowledge',
  'sidebar.nav.agents': 'Agents',
  'sidebar.nav.skills': 'Skills',
  'sidebar.nav.settings': 'Settings',
  'sidebar.recent': 'Recent Chats',
  'sidebar.new_chat': 'New Chat',
  'sidebar.status.connected': 'Connected',
  'sidebar.status.not_configured': 'Not configured',
  'sidebar.status.error': 'Connection failed',
  'sidebar.status.latency': 'Latency',
  'sidebar.empty': 'No chat history',

  // ─── Chat ─────────────────────────
  'chat.title': 'Chat',
  'chat.new_session': '+ New Chat',
  'chat.placeholder': 'Type a message...',
  'chat.send': 'Send',
  'chat.stop': 'Stop',
  'chat.config_warning': 'API endpoint or chat model not configured',
  'chat.config_warning_action': 'Go to Settings',
  'chat.loading': 'Loading conversation...',
  'chat.welcome': 'Welcome to Sage',
  'chat.welcome_sub': 'Start a new conversation',
  'chat.hint':
    'Sage remembers your project context · Supports Markdown · Click Knowledge to attach documents',
  'chat.memory_applied': 'memories applied',
  'chat.copy': 'Copy',
  'chat.copied': 'Copied',
  'chat.delete_confirm': 'Are you sure you want to delete this session?',

  // ─── File upload ──────────────────
  'chat.drop_files': 'Drop files here',
  'chat.attach_image': 'Attach image',
  'chat.attach_file': 'Attach file',
  'chat.knowledge_ref': 'Reference knowledge',
  'chat.knowledge_docs': 'Reference knowledge documents',

  // ─── Slash commands ───────────────
  'slash.help': 'Help',
  'slash.help_desc': 'Show available commands',
  'slash.clear': 'Clear chat',
  'slash.clear_desc': 'Clear all messages in current session',
  'slash.search': 'Search',
  'slash.search_desc': 'Type after /search to search',
  'slash.summarize': 'Summarize',
  'slash.summarize_desc': 'Summarize current conversation',
  'slash.translate': 'Translate',
  'slash.translate_desc': 'Translate the last message',
  'slash.compact': 'Compact context',
  'slash.compact_desc': 'Compress conversation context',

  // ─── Command palette ──────────────
  'cmd.title': 'Command Palette',
  'cmd.placeholder': 'Type a command or search...',
  'cmd.empty': 'No matching results',
  'cmd.nav': 'Navigation',
  'cmd.actions': 'Actions',
  'cmd.sessions': 'Recent Sessions',
  'cmd.new_chat': 'New Chat',
  'cmd.new_chat_desc': 'Create a new chat session',
  'cmd.toggle_theme': 'Toggle Theme',
  'cmd.toggle_theme_desc': 'Switch between light and dark',
  'cmd.hint_nav': '↑↓ Navigate',
  'cmd.hint_select': '↵ Select',
  'cmd.hint_close': 'esc Close',
  'cmd.messages': 'messages',

  // ─── Settings ─────────────────────
  'settings.title': 'Settings',
  'settings.tab.general': 'General',
  'settings.tab.endpoints': 'Endpoints',
  'settings.tab.models': 'Models',
  'settings.tab.memory': 'Memory',
  'settings.tab.network': 'Network',
  'settings.tab.evolution': 'Evolution',
  'settings.section.theme': 'Theme',
  'settings.section.appearance': 'Appearance',
  'settings.section.chat': 'Chat',
  'settings.section.data': 'Data',

  // ─── Decorative themes ───────────
  'theme.name.mint_blue': 'Mint Blue',
  'theme.name.sakura': 'Sakura',
  'theme.name.cyber_neon': 'Cyber Neon',
  'theme.name.midnight_amber': 'Midnight Amber',
  'theme.name.parchment': 'Parchment',
  'theme.desc.mint_blue': 'Refreshing mint green tones, gentle on the eyes',
  'theme.desc.sakura': 'Soft cherry blossom pink, spring romance',
  'theme.desc.cyber_neon': 'Neon purple and pink, futuristic vibe',
  'theme.desc.midnight_amber': 'Dark background with amber highlights, easy on the eyes for long reads',
  'theme.desc.parchment': 'Vintage parchment texture, ideal for writing',
  'theme.gallery.section_basic': 'Basic',
  'theme.gallery.section_decorative': 'Decorative',

  // ─── Common ───────────────────────
  'common.skip_to_content': 'Skip to content',
  'common.delete': 'Delete',
  'common.cancel': 'Cancel',
  'common.confirm': 'Confirm',
  'common.save': 'Save',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.retry': 'Retry',

  // ─── Time groups ──────────────────
  'time.today': 'Today',
  'time.yesterday': 'Yesterday',
  'time.this_week': 'This Week',
  'time.earlier': 'Earlier',
};
```

### Step 1.3：类型校验

```bash
cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -20
```

期望：无错误（`TranslationKey` 自动包含新键，en/zh 两边都补齐了所以 `Record<TranslationKey, string>` 不报错）。

### Step 1.4：Commit

```bash
cd /home/fz/project/sage && git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts && \
  git commit -m "feat(i18n): add decorative theme names + gallery section keys (zh/en)"
```

---

## Task 2 — 创建 SVG 封面图 × 5

**Files:**
- Create: `/home/fz/project/sage/public/themes/covers/mint-blue.svg`
- Create: `/home/fz/project/sage/public/themes/covers/sakura.svg`
- Create: `/home/fz/project/sage/public/themes/covers/cyber-neon.svg`
- Create: `/home/fz/project/sage/public/themes/covers/midnight-amber.svg`
- Create: `/home/fz/project/sage/public/themes/covers/parchment.svg`

**Interfaces:**
- Consumes: 无
- Produces: 5 个公开静态资源（240×160，纯几何 + 单色，不使用渐变/阴影）

**风格规范：**
- viewBox: `0 0 240 160`
- 元素：圆 (`<circle>`) + 三角 (`<polygon>`) + 直线 (`<line>`)，最多 5 个元素
- 颜色：取该主题 primary（深色用 darkColors.primary）
- 无 `<defs>`、无 `filter`、无 `<text>`（极简）

### Step 2.1：创建 `public/themes/covers/` 目录

```bash
mkdir -p /home/fz/project/sage/public/themes/covers
```

### Step 2.2：mint-blue.svg

**File:** `/home/fz/project/sage/public/themes/covers/mint-blue.svg`

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="240" height="160">
  <rect width="240" height="160" fill="#0d9488"/>
  <circle cx="70" cy="80" r="36" fill="#5eead4" opacity="0.95"/>
  <circle cx="70" cy="80" r="14" fill="#0d9488"/>
  <line x1="140" y1="40" x2="200" y2="120" stroke="#5eead4" stroke-width="6" stroke-linecap="round"/>
  <line x1="200" y1="40" x2="140" y2="120" stroke="#5eead4" stroke-width="6" stroke-linecap="round"/>
</svg>
```

### Step 2.3：sakura.svg

**File:** `/home/fz/project/sage/public/themes/covers/sakura.svg`

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="240" height="160">
  <rect width="240" height="160" fill="#fce7f3"/>
  <circle cx="120" cy="80" r="28" fill="#f9a8d4"/>
  <circle cx="120" cy="80" r="10" fill="#fce7f3"/>
  <polygon points="60,40 76,72 44,72" fill="#f9a8d4"/>
  <polygon points="180,40 196,72 164,72" fill="#f9a8d4"/>
  <polygon points="60,120 76,88 44,88" fill="#f9a8d4"/>
  <polygon points="180,120 196,88 164,88" fill="#f9a8d4"/>
</svg>
```

### Step 2.4：cyber-neon.svg

**File:** `/home/fz/project/sage/public/themes/covers/cyber-neon.svg`

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="240" height="160">
  <rect width="240" height="160" fill="#0a0118"/>
  <polygon points="120,30 180,120 60,120" fill="none" stroke="#a855f7" stroke-width="4"/>
  <line x1="40" y1="40" x2="200" y2="40" stroke="#ec4899" stroke-width="3"/>
  <line x1="40" y1="80" x2="200" y2="80" stroke="#a855f7" stroke-width="3"/>
  <line x1="40" y1="120" x2="200" y2="120" stroke="#ec4899" stroke-width="3"/>
  <circle cx="120" cy="75" r="8" fill="#ec4899"/>
</svg>
```

### Step 2.5：midnight-amber.svg

**File:** `/home/fz/project/sage/public/themes/covers/midnight-amber.svg`

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="240" height="160">
  <rect width="240" height="160" fill="#1c1917"/>
  <circle cx="120" cy="80" r="50" fill="#f59e0b"/>
  <circle cx="120" cy="80" r="34" fill="#1c1917"/>
  <line x1="40" y1="80" x2="60" y2="80" stroke="#f59e0b" stroke-width="3" stroke-linecap="round"/>
  <line x1="180" y1="80" x2="200" y2="80" stroke="#f59e0b" stroke-width="3" stroke-linecap="round"/>
</svg>
```

### Step 2.6：parchment.svg

**File:** `/home/fz/project/sage/public/themes/covers/parchment.svg`

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160" width="240" height="160">
  <rect width="240" height="160" fill="#fef3c7"/>
  <line x1="40" y1="50" x2="200" y2="50" stroke="#92400e" stroke-width="2" opacity="0.6"/>
  <line x1="40" y1="80" x2="180" y2="80" stroke="#92400e" stroke-width="2" opacity="0.6"/>
  <line x1="40" y1="110" x2="190" y2="110" stroke="#92400e" stroke-width="2" opacity="0.6"/>
  <polygon points="200,30 215,52 185,52" fill="none" stroke="#92400e" stroke-width="2"/>
  <circle cx="50" cy="120" r="6" fill="#92400e" opacity="0.7"/>
</svg>
```

### Step 2.7：验证文件大小

```bash
for f in /home/fz/project/sage/public/themes/covers/*.svg; do
  echo "$(wc -c < "$f") bytes — $f"
done
```

期望：每个文件 < 2048 字节（实际应在 400-700 字节）。

### Step 2.8：Commit

```bash
cd /home/fz/project/sage && git add public/themes/covers/ && \
  git commit -m "feat(theme): add 5 decorative theme SVG cover images"
```

---

## Task 3 — 创建 `decorative-presets.ts` + 测试

**Files:**
- Create: `/home/fz/project/sage/src/entities/theme/decorative-presets.ts`
- Create: `/home/fz/project/sage/src/entities/theme/__tests__/decorative-presets.test.ts`

**Interfaces:**
- Consumes: 现有的 `ThemeColors` 类型（从 `./presets` 导入）
- Produces:
  ```typescript
  export interface DecorativeTheme {
    id: string;
    name: string;
    description: string;
    colors: ThemeColors;
    darkColors: ThemeColors;
    cover: string;
    category: 'decorative';
  }
  export const decorativePresets: DecorativeTheme[];
  export function findDecorativeThemeById(id: string): DecorativeTheme | undefined;
  ```

### Step 3.1：RED — 写测试先

**File:** `/home/fz/project/sage/src/entities/theme/__tests__/decorative-presets.test.ts`

```typescript
import { describe, it, expect } from 'vitest';

import { decorativePresets } from '../decorative-presets';

describe('decorativePresets', () => {
  it('包含 5 套主题', () => {
    expect(decorativePresets).toHaveLength(5);
  });

  it('所有主题都有唯一 id', () => {
    const ids = decorativePresets.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('所有 id 都是小写连字符格式', () => {
    for (const t of decorativePresets) {
      expect(t.id).toMatch(/^[a-z][a-z0-9-]*$/);
    }
  });

  it('所有主题的 category 字段为 "decorative"', () => {
    for (const t of decorativePresets) {
      expect(t.category).toBe('decorative');
    }
  });

  it('所有主题都有 cover 字段且以 .svg 结尾', () => {
    for (const t of decorativePresets) {
      expect(t.cover).toMatch(/\.svg$/);
    }
  });

  it('所有主题都有完整的亮色 + 暗色配色', () => {
    const requiredKeys = [
      'primary', 'primaryHover', 'secondary', 'accent', 'bg', 'bgMuted', 'bgSubtle',
      'bgHover', 'bgActive', 'surface', 'surfaceElevated', 'text', 'textSecondary',
      'textMuted', 'textInverse', 'border', 'borderHover', 'success', 'error',
      'warning', 'info', 'overlay',
    ];
    for (const t of decorativePresets) {
      for (const key of requiredKeys) {
        expect(t.colors).toHaveProperty(key);
        expect(t.darkColors).toHaveProperty(key);
      }
    }
  });

  it('包含预期的 5 个 id', () => {
    const ids = decorativePresets.map((t) => t.id).sort();
    expect(ids).toEqual(['cyber-neon', 'midnight-amber', 'mint-blue', 'parchment', 'sakura']);
  });

  it('主题名长度 > 0', () => {
    for (const t of decorativePresets) {
      expect(t.name.length).toBeGreaterThan(0);
      expect(t.description.length).toBeGreaterThan(0);
    }
  });
});
```

运行测试（应当失败 — 模块不存在）：

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/decorative-presets.test.ts 2>&1 | tail -20
```

期望：`Failed to resolve import "../decorative-presets"`。

### Step 3.2：GREEN — 实现 `decorative-presets.ts`

**File:** `/home/fz/project/sage/src/entities/theme/decorative-presets.ts`

```typescript
/**
 * 装饰性主题预设 — Phase 4 新增
 *
 * 与 `presets.ts` 中的 6 套基础主题（id: indigo / sage-green / ocean / ember / mono / cyberpunk）并存，
 * 通过统一的 `getThemeById` 暴露给消费方（见 `presets.ts`）。
 */

import type { ThemeColors } from './presets';

/** 装饰性主题（含 cover 图） */
export interface DecorativeTheme {
  id: string;
  name: string;
  description: string;
  colors: ThemeColors;
  darkColors: ThemeColors;
  cover: string;
  category: 'decorative';
}

// ─── Mint Blue（薄荷蓝）─────────────────────

const mintBlueLight: ThemeColors = {
  primary: '#0d9488',
  primaryHover: '#0f766e',
  secondary: '#06b6d4',
  accent: '#5eead4',
  bg: '#ffffff',
  bgMuted: '#f0fdfa',
  bgSubtle: '#ccfbf1',
  bgHover: '#f0fdfa',
  bgActive: '#99f6e4',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#134e4a',
  textSecondary: '#5eead4',
  textMuted: '#5eead4',
  textInverse: '#ffffff',
  border: '#ccfbf1',
  borderHover: '#99f6e4',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#06b6d4',
  overlay: 'rgba(0,0,0,0.25)',
};

const mintBlueDark: ThemeColors = {
  primary: '#5eead4',
  primaryHover: '#99f6e4',
  secondary: '#22d3ee',
  accent: '#0d9488',
  bg: '#042f2e',
  bgMuted: '#0a3d3a',
  bgSubtle: '#134e4a',
  bgHover: '#0f4a47',
  bgActive: '#115e59',
  surface: '#062e2c',
  surfaceElevated: '#0a3d3a',
  text: '#ccfbf1',
  textSecondary: '#99f6e4',
  textMuted: '#5eead4',
  textInverse: '#042f2e',
  border: '#134e4a',
  borderHover: '#115e59',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#22d3ee',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Sakura（樱花粉）────────────────────────

const sakuraLight: ThemeColors = {
  primary: '#ec4899',
  primaryHover: '#db2777',
  secondary: '#f472b6',
  accent: '#f9a8d4',
  bg: '#fdf2f8',
  bgMuted: '#fce7f3',
  bgSubtle: '#fbcfe8',
  bgHover: '#fce7f3',
  bgActive: '#f9a8d4',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#500724',
  textSecondary: '#9d174d',
  textMuted: '#be185d',
  textInverse: '#ffffff',
  border: '#fbcfe8',
  borderHover: '#f9a8d4',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#ec4899',
  overlay: 'rgba(0,0,0,0.25)',
};

const sakuraDark: ThemeColors = {
  primary: '#f9a8d4',
  primaryHover: '#fbcfe8',
  secondary: '#f472b6',
  accent: '#ec4899',
  bg: '#2d0a1f',
  bgMuted: '#3f0e2c',
  bgSubtle: '#500724',
  bgHover: '#4a0e2a',
  bgActive: '#831843',
  surface: '#2a0a1f',
  surfaceElevated: '#3f0e2c',
  text: '#fce7f3',
  textSecondary: '#f9a8d4',
  textMuted: '#fbcfe8',
  textInverse: '#2d0a1f',
  border: '#500724',
  borderHover: '#831843',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#f9a8d4',
  overlay: 'rgba(0,0,0,0.5)',
};

// ─── Cyber Neon ────────────────────────────

const cyberNeonLight: ThemeColors = {
  primary: '#a855f7',
  primaryHover: '#9333ea',
  secondary: '#ec4899',
  accent: '#06b6d4',
  bg: '#faf5ff',
  bgMuted: '#f3e8ff',
  bgSubtle: '#e9d5ff',
  bgHover: '#f3e8ff',
  bgActive: '#d8b4fe',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#1e1b4b',
  textSecondary: '#4c1d95',
  textMuted: '#7e22ce',
  textInverse: '#ffffff',
  border: '#e9d5ff',
  borderHover: '#d8b4fe',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#a855f7',
  overlay: 'rgba(0,0,0,0.25)',
};

const cyberNeonDark: ThemeColors = {
  primary: '#a855f7',
  primaryHover: '#c084fc',
  secondary: '#ec4899',
  accent: '#06b6d4',
  bg: '#0a0118',
  bgMuted: '#14072b',
  bgSubtle: '#1e0a3d',
  bgHover: '#1a0a35',
  bgActive: '#2e1065',
  surface: '#0d031f',
  surfaceElevated: '#14072b',
  text: '#e9d5ff',
  textSecondary: '#c084fc',
  textMuted: '#a855f7',
  textInverse: '#0a0118',
  border: '#1e0a3d',
  borderHover: '#2e1065',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#a855f7',
  overlay: 'rgba(0,0,0,0.6)',
};

// ─── Midnight Amber（深夜琥珀）────────────

const midnightAmberLight: ThemeColors = {
  primary: '#d97706',
  primaryHover: '#b45309',
  secondary: '#92400e',
  accent: '#fbbf24',
  bg: '#fffbeb',
  bgMuted: '#fef3c7',
  bgSubtle: '#fde68a',
  bgHover: '#fef3c7',
  bgActive: '#fde68a',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#1c1917',
  textSecondary: '#57534e',
  textMuted: '#a8a29e',
  textInverse: '#ffffff',
  border: '#e7e5e4',
  borderHover: '#d6d3d1',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const midnightAmberDark: ThemeColors = {
  primary: '#fbbf24',
  primaryHover: '#fcd34d',
  secondary: '#f59e0b',
  accent: '#d97706',
  bg: '#0c0a09',
  bgMuted: '#1c1917',
  bgSubtle: '#292524',
  bgHover: '#1c1917',
  bgActive: '#44403c',
  surface: '#0f0e0d',
  surfaceElevated: '#1c1917',
  text: '#fef3c7',
  textSecondary: '#fbbf24',
  textMuted: '#d97706',
  textInverse: '#0c0a09',
  border: '#292524',
  borderHover: '#44403c',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#60a5fa',
  overlay: 'rgba(0,0,0,0.6)',
};

// ─── Parchment（羊皮纸）───────────────────

const parchmentLight: ThemeColors = {
  primary: '#92400e',
  primaryHover: '#78350f',
  secondary: '#a16207',
  accent: '#b45309',
  bg: '#fef3c7',
  bgMuted: '#fde68a',
  bgSubtle: '#fcd34d',
  bgHover: '#fde68a',
  bgActive: '#fcd34d',
  surface: '#fffbeb',
  surfaceElevated: '#fffbeb',
  text: '#451a03',
  textSecondary: '#78350f',
  textMuted: '#a16207',
  textInverse: '#fffbeb',
  border: '#fde68a',
  borderHover: '#fcd34d',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  overlay: 'rgba(0,0,0,0.25)',
};

const parchmentDark: ThemeColors = {
  primary: '#fcd34d',
  primaryHover: '#fde68a',
  secondary: '#fbbf24',
  accent: '#f59e0b',
  bg: '#1c1208',
  bgMuted: '#2a1a0a',
  bgSubtle: '#3d2810',
  bgHover: '#2a1a0a',
  bgActive: '#4a3018',
  surface: '#221408',
  surfaceElevated: '#2a1a0a',
  text: '#fef3c7',
  textSecondary: '#fcd34d',
  textMuted: '#fde68a',
  textInverse: '#1c1208',
  border: '#3d2810',
  borderHover: '#4a3018',
  success: '#34d399',
  error: '#f87171',
  warning: '#fbbf24',
  info: '#60a5fa',
  overlay: 'rgba(0,0,0,0.6)',
};

// ─── 预设注册 ─────────────────────────────────

export const decorativePresets: DecorativeTheme[] = [
  {
    id: 'mint-blue',
    name: 'Mint Blue',
    description: '清新的薄荷绿色调，温和不刺眼',
    colors: mintBlueLight,
    darkColors: mintBlueDark,
    cover: '/themes/covers/mint-blue.svg',
    category: 'decorative',
  },
  {
    id: 'sakura',
    name: 'Sakura',
    description: '温柔的樱花粉色，浪漫春日感',
    colors: sakuraLight,
    darkColors: sakuraDark,
    cover: '/themes/covers/sakura.svg',
    category: 'decorative',
  },
  {
    id: 'cyber-neon',
    name: 'Cyber Neon',
    description: '霓虹紫粉，未来科技感',
    colors: cyberNeonLight,
    darkColors: cyberNeonDark,
    cover: '/themes/covers/cyber-neon.svg',
    category: 'decorative',
  },
  {
    id: 'midnight-amber',
    name: 'Midnight Amber',
    description: '深色背景配琥珀高亮，长时间阅读友好',
    colors: midnightAmberLight,
    darkColors: midnightAmberDark,
    cover: '/themes/covers/midnight-amber.svg',
    category: 'decorative',
  },
  {
    id: 'parchment',
    name: 'Parchment',
    description: '复古羊皮纸纹理，文学与写作场景',
    colors: parchmentLight,
    darkColors: parchmentDark,
    cover: '/themes/covers/parchment.svg',
    category: 'decorative',
  },
];

/**
 * 根据 id 查找装饰主题
 * （在 `presets.ts` 的 `getThemeById` 内部被调用）
 */
export function findDecorativeThemeById(id: string): DecorativeTheme | undefined {
  return decorativePresets.find((t) => t.id === id);
}
```

### Step 3.3：运行测试，应当全绿

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/decorative-presets.test.ts 2>&1 | tail -15
```

期望：`8 passed`。

### Step 3.4：Commit

```bash
cd /home/fz/project/sage && git add src/entities/theme/decorative-presets.ts src/entities/theme/__tests__/decorative-presets.test.ts && \
  git commit -m "feat(theme): add 5 decorative theme presets with cover paths"
```

---

## Task 4 — 修改 `presets.ts` 的 `getThemeById` 统一查找

**Files:**
- Modify: `/home/fz/project/sage/src/entities/theme/presets.ts`（顶部加 import + 改 `getThemeById` 函数体）
- Create: `/home/fz/project/sage/src/entities/theme/__tests__/presets.test.ts`（新建，覆盖 `getThemeById` 新行为）

**Interfaces:**
- Consumes: 现有的 `themePresets` + 新的 `decorativePresets` + `findDecorativeThemeById`
- Produces: 扩展后的 `getThemeById(id)` — 同时查基础 + 装饰主题，返回值类型为 `ThemePreset | DecorativeTheme`（实际收敛为 `ThemePreset & Partial<DecorativeTheme>` 仍可调用 `applyThemeColors`，因为 `colors` / `darkColors` 字段在两者上都有）

**重要约束：** 不修改 6 套基础主题的 ID / 颜色字面量 / 描述。

### Step 4.1：RED — 写新测试

**File:** `/home/fz/project/sage/src/entities/theme/__tests__/presets.test.ts`

```typescript
import { describe, it, expect } from 'vitest';

import { themePresets, getThemeById, DEFAULT_THEME_ID, decorativePresets } from '../presets';

describe('getThemeById', () => {
  it('能找到基础主题', () => {
    expect(getThemeById('indigo')).toBeDefined();
    expect(getThemeById('indigo')?.id).toBe('indigo');
  });

  it('能找到装饰主题', () => {
    const t = getThemeById('mint-blue');
    expect(t).toBeDefined();
    expect(t?.id).toBe('mint-blue');
  });

  it('能找到所有 5 套装饰主题', () => {
    for (const d of decorativePresets) {
      expect(getThemeById(d.id)).toBeDefined();
    }
  });

  it('找不到不存在的主题时返回 undefined', () => {
    expect(getThemeById('not-a-theme')).toBeUndefined();
  });

  it('返回的主题有 colors + darkColors 字段（保证 applyThemeColors 可用）', () => {
    for (const t of [...themePresets, ...decorativePresets]) {
      const found = getThemeById(t.id);
      expect(found).toBeDefined();
      expect(found?.colors.primary).toBeTruthy();
      expect(found?.darkColors.primary).toBeTruthy();
    }
  });

  it('装饰主题带 cover 字段', () => {
    const t = getThemeById('sakura');
    expect(t).toBeDefined();
    if (t && 'cover' in t) {
      expect((t as { cover: string }).cover).toMatch(/\.svg$/);
    }
  });

  it('DEFAULT_THEME_ID 仍然指向 indigo（向后兼容）', () => {
    expect(DEFAULT_THEME_ID).toBe('indigo');
    expect(getThemeById(DEFAULT_THEME_ID)?.id).toBe('indigo');
  });
});
```

运行测试（应当失败 — `getThemeById` 还没查装饰主题）：

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/presets.test.ts 2>&1 | tail -25
```

期望：3 个测试失败（"能找到装饰主题"、"能找到所有 5 套装饰主题"、"装饰主题带 cover 字段"）。

### Step 4.2：GREEN — 修改 `presets.ts`

**Goal:** 顶部加 import，把 `getThemeById` 改为同时查基础 + 装饰主题；并 re-export `decorativePresets` + `DecorativeTheme` 方便消费方单点导入。

**File:** `/home/fz/project/sage/src/entities/theme/presets.ts`

**替换第 1-4 行**：

```typescript
/**
 * 主题预设 — 每个主题包含完整的亮色 + 暗色配色
 */

import { decorativePresets, findDecorativeThemeById } from './decorative-presets';

export type { DecorativeTheme } from './decorative-presets';
export { decorativePresets } from './decorative-presets';

/** 主题颜色集合 */
```

**替换第 399-402 行**：

将：

```typescript
/** 根据 id 获取主题预设 */
export function getThemeById(id: string): ThemePreset | undefined {
  return themePresets.find((t) => t.id === id);
}
```

替换为：

```typescript
/**
 * 根据 id 获取主题预设（基础 6 套 + 装饰 5 套）
 *
 * 返回类型在运行时为 ThemePreset | DecorativeTheme，但两者都包含
 * `colors` 与 `darkColors` 字段（来自 `ThemeColors`），所以消费方
 * 可直接当作 ThemePreset 使用。
 */
export function getThemeById(id: string): ThemePreset | undefined {
  return themePresets.find((t) => t.id === id) ?? findDecorativeThemeById(id);
}
```

**其余 6 套基础主题的 `colors` / `darkColors` 字面量、`themePresets` 数组、`DEFAULT_THEME_ID` 全部保持原样不动。**

### Step 4.3：运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/entities/theme/__tests__/ 2>&1 | tail -15
```

期望：所有 storage / decorative-presets / presets 测试全绿。

### Step 4.4：Commit

```bash
cd /home/fz/project/sage && git add src/entities/theme/presets.ts src/entities/theme/__tests__/presets.test.ts && \
  git commit -m "feat(theme): unify getThemeById to lookup basic + decorative themes"
```

---

## Task 5 — 创建 `ThemeCover.tsx` 组件

**Files:**
- Create: `/home/fz/project/sage/src/features/theme/ThemeCover.tsx`
- Create: `/home/fz/project/sage/src/features/theme/__tests__/ThemeCover.test.tsx`

**Interfaces:**
- Consumes:
  - `ThemeColors`（从 `entities/theme/presets`）
  - `src: string` — SVG 路径
  - `fallbackLabel: string` — 降级显示的字符（主题名首字母）
- Produces:
  ```typescript
  interface ThemeCoverProps {
    src: string;
    colors: ThemeColors;
    fallbackLabel: string;
    alt?: string;
    className?: string;
  }
  export function ThemeCover(props: ThemeCoverProps): JSX.Element;
  ```

**降级契约：** `<img onError>` 触发后切换为绝对定位的渐变 div + 主题名首字母。

### Step 5.1：创建 `src/features/theme/` 目录

```bash
mkdir -p /home/fz/project/sage/src/features/theme/__tests__
```

### Step 5.2：RED — 写测试

**File:** `/home/fz/project/sage/src/features/theme/__tests__/ThemeCover.test.tsx`

```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { ThemeColors } from '../../../entities/theme/presets';
import { ThemeCover } from '../ThemeCover';

const sampleColors: ThemeColors = {
  primary: '#0d9488',
  primaryHover: '#0f766e',
  secondary: '#06b6d4',
  accent: '#5eead4',
  bg: '#ffffff',
  bgMuted: '#f0fdfa',
  bgSubtle: '#ccfbf1',
  bgHover: '#f0fdfa',
  bgActive: '#99f6e4',
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  text: '#134e4a',
  textSecondary: '#5eead4',
  textMuted: '#5eead4',
  textInverse: '#ffffff',
  border: '#ccfbf1',
  borderHover: '#99f6e4',
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#06b6d4',
  overlay: 'rgba(0,0,0,0.25)',
};

describe('ThemeCover', () => {
  it('渲染 img 标签且 src 正确', () => {
    render(
      <ThemeCover
        src="/themes/covers/mint-blue.svg"
        colors={sampleColors}
        fallbackLabel="M"
      />,
    );
    const img = screen.getByRole('img', { name: /theme cover/i });
    expect(img).toHaveAttribute('src', '/themes/covers/mint-blue.svg');
  });

  it('使用 alt 文本透传', () => {
    render(
      <ThemeCover
        src="/themes/covers/sakura.svg"
        colors={sampleColors}
        fallbackLabel="S"
        alt="Sakura 主题封面"
      />,
    );
    expect(screen.getByRole('img', { name: 'Sakura 主题封面' })).toBeInTheDocument();
  });

  it('img 加载失败时显示 fallback 渐变（无 img 节点）', () => {
    render(
      <ThemeCover
        src="/themes/covers/missing.svg"
        colors={sampleColors}
        fallbackLabel="M"
      />,
    );
    const img = screen.getByRole('img', { name: /theme cover/i });
    fireEvent.error(img);
    expect(screen.queryByRole('img', { name: /theme cover/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('theme-cover-fallback')).toBeInTheDocument();
  });

  it('fallback 显示首字母', () => {
    render(
      <ThemeCover
        src="/themes/covers/missing.svg"
        colors={sampleColors}
        fallbackLabel="CN"
      />,
    );
    const img = screen.getByRole('img', { name: /theme cover/i });
    fireEvent.error(img);
    expect(screen.getByTestId('theme-cover-fallback')).toHaveTextContent('CN');
  });

  it('fallback 渐变使用 primary + accent 颜色', () => {
    render(
      <ThemeCover
        src="/themes/covers/missing.svg"
        colors={sampleColors}
        fallbackLabel="M"
      />,
    );
    fireEvent.error(screen.getByRole('img', { name: /theme cover/i }));
    const fb = screen.getByTestId('theme-cover-fallback');
    expect(fb.style.background).toContain('#0d9488');
    expect(fb.style.background).toContain('#5eead4');
  });

  it('不抛错（即使不传 onError 也不影响其他 props）', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ThemeCover
        src="/themes/covers/mint-blue.svg"
        colors={sampleColors}
        fallbackLabel="M"
      />,
    );
    expect(screen.getByRole('img')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
```

运行测试（应当失败 — 模块不存在）：

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/ThemeCover.test.tsx 2>&1 | tail -15
```

### Step 5.3：GREEN — 实现 `ThemeCover.tsx`

**File:** `/home/fz/project/sage/src/features/theme/ThemeCover.tsx`

```typescript
/**
 * 主题封面图组件
 *
 * 行为契约：
 * - 正常：渲染 <img src={src} />
 * - 加载失败（onError）：切换为 absolute 渐变占位 + 主题名首字母，
 *   渐变使用传入 colors.primary → colors.accent。
 */

import { useState } from 'react';

import type { ThemeColors } from '../../entities/theme/presets';

export interface ThemeCoverProps {
  src: string;
  colors: ThemeColors;
  fallbackLabel: string;
  alt?: string;
  className?: string;
}

export function ThemeCover({ src, colors, fallbackLabel, alt, className }: ThemeCoverProps) {
  const [errored, setErrored] = useState(false);

  if (errored) {
    return (
      <div
        data-testid="theme-cover-fallback"
        className={`flex items-center justify-center text-lg font-semibold text-white ${
          className ?? ''
        }`}
        style={{
          background: `linear-gradient(135deg, ${colors.primary} 0%, ${colors.accent} 100%)`,
        }}
        aria-hidden="true"
      >
        {fallbackLabel}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt ?? 'theme cover'}
      onError={() => setErrored(true)}
      className={className}
    />
  );
}
```

### Step 5.4：运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/ThemeCover.test.tsx 2>&1 | tail -15
```

期望：`6 passed`。

### Step 5.5：Commit

```bash
cd /home/fz/project/sage && git add src/features/theme/ThemeCover.tsx src/features/theme/__tests__/ThemeCover.test.tsx && \
  git commit -m "feat(theme): add ThemeCover component with onError gradient fallback"
```

---

## Task 6 — 创建 `ThemeGallery.tsx` 组件

**Files:**
- Create: `/home/fz/project/sage/src/features/theme/ThemeGallery.tsx`
- Create: `/home/fz/project/sage/src/features/theme/__tests__/ThemeGallery.test.tsx`

**Interfaces:**
- Consumes:
  - `useTheme` 返回 `{ presetId, setPresetId, resolved }`
  - `themePresets`（6 套基础）
  - `decorativePresets`（5 套装饰）
  - `useI18n` 返回 `t`
- Produces:
  ```typescript
  export function ThemeGallery(): JSX.Element;
  ```

**布局：**
- 顶部：基础主题区（6 张小卡片，240×160 视觉感受）
- 底部：装饰主题区（5 张小卡片，240×160 视觉感受）
- 每张卡片：cover + 主题名 + 描述 + 点击切换
- 选中态：边框高亮（ring-2 ring-primary）

### Step 6.1：RED — 写测试

**File:** `/home/fz/project/sage/src/features/theme/__tests__/ThemeGallery.test.tsx`

```typescript
import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockUseTheme = vi.fn();
vi.mock('../../../app/providers/useTheme', () => ({
  useTheme: () => mockUseTheme(),
}));

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    locale: 'zh',
    setLocale: vi.fn(),
    t: (k: string) => {
      const map: Record<string, string> = {
        'theme.name.mint_blue': '薄荷蓝',
        'theme.name.sakura': '樱花粉',
        'theme.name.cyber_neon': 'Cyber Neon',
        'theme.name.midnight_amber': '深夜琥珀',
        'theme.name.parchment': '羊皮纸',
        'theme.gallery.section_basic': '基础主题',
        'theme.gallery.section_decorative': '装饰主题',
      };
      return map[k] ?? k;
    },
  }),
}));

import { ThemeGallery } from '../ThemeGallery';

describe('ThemeGallery', () => {
  beforeEach(() => {
    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId: vi.fn(),
      resolved: 'light',
    });
  });

  it('渲染两个分区标题（基础 + 装饰）', () => {
    render(<ThemeGallery />);
    expect(screen.getByText('基础主题')).toBeInTheDocument();
    expect(screen.getByText('装饰主题')).toBeInTheDocument();
  });

  it('基础区显示 6 张卡片（每张含主题名）', () => {
    render(<ThemeGallery />);
    const basic = screen.getByTestId('theme-section-basic');
    expect(within(basic).getAllByRole('button')).toHaveLength(6);
    expect(within(basic).getByText('Indigo')).toBeInTheDocument();
    expect(within(basic).getByText('Sage Green')).toBeInTheDocument();
  });

  it('装饰区显示 5 张卡片（每张含主题名）', () => {
    render(<ThemeGallery />);
    const deco = screen.getByTestId('theme-section-decorative');
    expect(within(deco).getAllByRole('button')).toHaveLength(5);
    expect(within(deco).getByText('薄荷蓝')).toBeInTheDocument();
    expect(within(deco).getByText('樱花粉')).toBeInTheDocument();
  });

  it('总主题数 = 11', () => {
    render(<ThemeGallery />);
    expect(screen.getAllByRole('button')).toHaveLength(11);
  });

  it('当前 presetId 对应的卡片带 active 标识', () => {
    mockUseTheme.mockReturnValue({
      presetId: 'mint-blue',
      setPresetId: vi.fn(),
      resolved: 'light',
    });
    render(<ThemeGallery />);
    const mintButton = screen.getByRole('button', { name: /薄荷蓝/ });
    expect(mintButton.getAttribute('data-active')).toBe('true');
  });

  it('点击装饰主题触发 setPresetId(该 id)', () => {
    const setPresetId = vi.fn();
    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId,
      resolved: 'light',
    });
    render(<ThemeGallery />);
    fireEvent.click(screen.getByRole('button', { name: /Cyber Neon/ }));
    expect(setPresetId).toHaveBeenCalledWith('cyber-neon');
  });

  it('点击基础主题也触发 setPresetId', () => {
    const setPresetId = vi.fn();
    mockUseTheme.mockReturnValue({
      presetId: 'indigo',
      setPresetId,
      resolved: 'light',
    });
    render(<ThemeGallery />);
    fireEvent.click(screen.getByRole('button', { name: /Deep Ocean/ }));
    expect(setPresetId).toHaveBeenCalledWith('ocean');
  });

  it('卡片为 <button> 元素', () => {
    render(<ThemeGallery />);
    const btns = screen.getAllByRole('button');
    for (const b of btns) {
      expect(b.tagName).toBe('BUTTON');
    }
  });
});
```

运行测试（应当失败 — 模块不存在）：

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/ThemeGallery.test.tsx 2>&1 | tail -15
```

### Step 6.2：GREEN — 实现 `ThemeGallery.tsx`

**File:** `/home/fz/project/sage/src/features/theme/ThemeGallery.tsx`

```typescript
/**
 * 主题画廊 — Phase 4 新组件
 *
 * 把 6 套基础主题 + 5 套装饰主题以"封面图 + 主题名 + 描述"的卡片网格展示。
 * 点击卡片触发 useTheme().setPresetId(id) 切换主题。
 */

import { clsx } from 'clsx';

import { useTheme } from '../../app/providers/useTheme';
import {
  themePresets,
  decorativePresets,
  type ThemePreset,
  type DecorativeTheme,
} from '../../entities/theme/presets';
import { useI18n } from '../../shared/lib/i18n';

import { ThemeCover } from './ThemeCover';

type AnyTheme = (ThemePreset | DecorativeTheme) & { cover?: string };

function getInitial(name: string): string {
  return name.charAt(0);
}

function getCoverPath(theme: AnyTheme): string {
  return theme.cover ?? '';
}

export function ThemeGallery() {
  const { presetId, setPresetId, resolved } = useTheme();
  const { t } = useI18n();

  const renderCard = (theme: AnyTheme) => {
    const isActive = theme.id === presetId;
    const colors = resolved === 'dark' ? theme.darkColors : theme.colors;
    const cover = getCoverPath(theme);

    return (
      <button
        key={theme.id}
        type="button"
        onClick={() => setPresetId(theme.id)}
        data-active={isActive ? 'true' : 'false'}
        data-testid={`theme-card-${theme.id}`}
        aria-pressed={isActive}
        className={clsx(
          'group flex flex-col rounded-radius-md border text-left overflow-hidden transition-all',
          isActive
            ? 'border-primary ring-2 ring-primary/30'
            : 'border-border hover:border-border-hover',
        )}
      >
        <ThemeCover
          src={cover}
          colors={colors}
          fallbackLabel={getInitial(theme.name)}
          alt={theme.name}
          className="w-full h-32 object-cover"
        />
        <div className="px-3 py-2">
          <div
            className={clsx(
              'text-sm font-medium truncate',
              isActive ? 'text-primary' : 'text-text',
            )}
          >
            {theme.name}
          </div>
          <div className="text-[11px] text-text-muted truncate">{theme.description}</div>
        </div>
      </button>
    );
  };

  return (
    <div className="space-y-5">
      <section>
        <h4
          data-testid="theme-section-basic"
          className="text-xs font-semibold text-text-secondary mb-2 uppercase tracking-wide"
        >
          {t('theme.gallery.section_basic')}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {themePresets.map((p) => renderCard(p))}
        </div>
      </section>
      <section>
        <h4
          data-testid="theme-section-decorative"
          className="text-xs font-semibold text-text-secondary mb-2 uppercase tracking-wide"
        >
          {t('theme.gallery.section_decorative')}
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {decorativePresets.map((p) => renderCard(p))}
        </div>
      </section>
    </div>
  );
}
```

### Step 6.3：运行测试

```bash
cd /home/fz/project/sage && npx vitest run src/features/theme/__tests__/ThemeGallery.test.tsx 2>&1 | tail -20
```

期望：`8 passed`。

### Step 6.4：Commit

```bash
cd /home/fz/project/sage && git add src/features/theme/ThemeGallery.tsx src/features/theme/__tests__/ThemeGallery.test.tsx && \
  git commit -m "feat(theme): add ThemeGallery component with 11 theme cards"
```

---

## Task 7 — 升级 `ThemeSelector.tsx` 集成 Gallery

**Files:**
- Modify: `/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx`

**Interfaces:**
- Consumes: 现有的 `useTheme`（不再直接使用，逻辑下移到 Gallery）
- Produces: 一个 `<ThemeGallery />` 的薄壳导出（保持 `GeneralTab.tsx` 中的 import 路径不变）

### Step 7.1：替换 `ThemeSelector.tsx` 全部内容

**File:** `/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx`

**完整新内容：**

```typescript
/**
 * 主题选择器 — Phase 4 升级为 Gallery 视图
 *
 * 内部委托给 `features/theme/ThemeGallery`，此处保留文件以兼容
 * `GeneralTab.tsx` 的 `import { ThemeSelector } from './ThemeSelector'`。
 */

import { ThemeGallery } from '../../features/theme/ThemeGallery';

export function ThemeSelector() {
  return <ThemeGallery />;
}
```

### Step 7.2：跑 `GeneralTab` 集成测试

无新增测试，但需跑一遍既有测试确保 `GeneralTab` 渲染不破：

```bash
cd /home/fz/project/sage && npx vitest run 2>&1 | tail -25
```

期望：所有现有测试 + Phase 4 新测试全绿。

### Step 7.3：Type check

```bash
cd /home/fz/project/sage && npx tsc --noEmit 2>&1 | head -20
```

期望：无错误。

### Step 7.4：Commit

```bash
cd /home/fz/project/sage && git add src/pages/settings/ThemeSelector.tsx && \
  git commit -m "refactor(settings): delegate ThemeSelector to ThemeGallery"
```

---

## Task 8 — 覆盖率验证 + 端到端冒烟

**Files:** 无新增（仅运行命令验证）

### Step 8.1：跑覆盖率

```bash
cd /home/fz/project/sage && npx vitest run --coverage 2>&1 | tail -40
```

**期望：**
- `src/features/theme/ThemeGallery.tsx` 行覆盖 ≥ 85%
- `src/features/theme/ThemeCover.tsx` 行覆盖 ≥ 85%
- `src/entities/theme/decorative-presets.ts` 行覆盖 = 100%
- `src/entities/theme/presets.ts` 行覆盖 ≥ 90%
- 整体行覆盖 ≥ 82%

### Step 8.2：视觉冒烟（手动）

```bash
cd /home/fz/project/sage && npm run dev
```

打开浏览器 `http://localhost:1420/`，进入设置 → 通用 tab：

**验收清单：**
- [ ] 看到两个分区标题："基础主题" / "装饰主题"
- [ ] 基础区显示 6 张卡片（Indigo / Sage Green / Deep Ocean / Warm Ember / Mono / Cyberpunk）
- [ ] 装饰区显示 5 张卡片（薄荷蓝 / 樱花粉 / Cyber Neon / 深夜琥珀 / 羊皮纸）
- [ ] 每张卡片显示封面图（240×160 视觉感受）
- [ ] 点击任一卡片，主题色立即应用
- [ ] 选中态：卡片有 primary 边框 + 浅 ring
- [ ] 模拟封面图失败：暂时把 `public/themes/covers/mint-blue.svg` 改名 → 刷新 → 薄荷蓝卡片显示青绿色渐变 + "M" 字符（确认 onError 降级）；改回原名
- [ ] 切换到暗色模式：所有卡片主题色正确应用
- [ ] i18n 切换：把 `useI18n` 的 `defaultLocale` 临时改为 `en` → 装饰主题名显示英文（Sakura / Cyber Neon 等）

### Step 8.3：Lint

```bash
cd /home/fz/project/sage && npm run lint 2>&1 | tail -20
```

期望：无 error。warning 可接受但应记录。

### Step 8.4：Coverage 报告归档

```bash
cd /home/fz/project/sage && ls -la coverage/ 2>&1
```

期望：存在 `coverage/lcov.info` 与 HTML 报告。

### Step 8.5：最终 Commit（如有 lint 修复）

如果 Step 8.3 触发了 auto-fix：

```bash
cd /home/fz/project/sage && git status 2>&1
# 如有变更：
git add -A && git commit -m "style: prettier reformat Phase 4 files"
```

### Step 8.6：推送 + 开 PR

```bash
cd /home/fz/project/sage && git push -u origin feat/ui-optimization-phase3 2>&1 | tail -5
```

然后：

```bash
cd /home/fz/project/sage && gh pr create --title "feat(ui): Phase 4 — decorative themes + gallery view" --body "## 概要
- 新增 5 套装饰主题（Mint Blue / Sakura / Cyber Neon / Midnight Amber / Parchment）
- 把设置页主题选择器从单色圆点列表升级为封面图卡片网格
- 封面图加载失败自动降级为渐变占位
- i18n 完整覆盖（zh + en）

## 文件变更
- 新增：src/entities/theme/decorative-presets.ts
- 新增：src/features/theme/ThemeCover.tsx
- 新增：src/features/theme/ThemeGallery.tsx
- 新增：public/themes/covers/*.svg × 5
- 修改：src/pages/settings/ThemeSelector.tsx（薄壳委托）
- 修改：src/entities/theme/presets.ts（getThemeById 扩展）
- 修改：src/shared/lib/i18n/{zh,en}.ts（+12 翻译键）
- 新增测试：3 个 test 文件

## 验证
- [x] tsc --noEmit 无错误
- [x] vitest 全绿
- [x] 覆盖率：ThemeGallery 85%+，整体 82%+
- [x] 视觉冒烟：浏览器手测 11 张卡片渲染正常
- [x] 降级：模拟 SVG 404 → 渐变占位正常

Closes Phase 4 of AionUi-inspired UI design."
```

---

## Risk Assessment

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `presets.ts` 改 `getThemeById` 破坏 `ThemeProvider` | 低 | 高 | 单元测试覆盖 `getThemeById('indigo')` 仍返回基础主题；`ThemeProvider` 用法不变 |
| SVG 文件未被打包到 Electron 产物 | 中 | 中 | 验证 `npm run build` 后 `dist/themes/covers/*.svg` 存在；vite `public/` 默认会复制 |
| 装饰主题 ID 撞名基础主题 | 低 | 高 | 测试覆盖"所有 ID 唯一" |
| 主题切换后 CSS 变量未应用装饰主题 | 低 | 高 | `applyThemeColors` 接受任意 `ThemeColors`；`decorativePresets` 的 `colors` / `darkColors` 字段完全满足 `ThemeColors` 形状 |
| i18n 翻译键拼写错误导致 `t('xxx')` 返回原 key | 低 | 中 | 视觉冒烟覆盖 zh + en；TypeScript 编译保证 `TranslationKey` 完整 |

---

## Definition of Done

- [ ] 5 张 SVG 封面图在 `public/themes/covers/` 下，每张 < 2KB
- [ ] 11 张主题卡片（6 基础 + 5 装饰）在设置页正确渲染
- [ ] 点击任一卡片成功切换主题
- [ ] 封面图加载失败时显示渐变占位（无白屏）
- [ ] i18n zh + en 翻译键完整
- [ ] 所有 vitest 测试通过
- [ ] 覆盖率：ThemeGallery ≥ 85%，整体 ≥ 82%
- [ ] `tsc --noEmit` 无错误
- [ ] `npm run lint` 无 error
- [ ] 视觉冒烟在浏览器手测通过
- [ ] PR 已开且 CI 绿
- [ ] 已 commit 并 push

---

## 参考

- 设计 spec：`/home/fz/project/sage/docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md`（Phase 4 + 测试策略段）
- 现有 `presets.ts`：`/home/fz/project/sage/src/entities/theme/presets.ts`
- 现有 `ThemeSelector.tsx`：`/home/fz/project/sage/src/pages/settings/ThemeSelector.tsx`
- 现有 `ThemeProvider`：`/home/fz/project/sage/src/app/providers/ThemeProvider.tsx`
- 现有 i18n：`/home/fz/project/sage/src/shared/lib/i18n/index.tsx`
- vitest 配置：`/home/fz/project/sage/vite.config.ts`（`test.environment = 'jsdom'`，`setupFiles = './src/test-setup.ts'`）
- 测试基线：`/home/fz/project/sage/src/entities/theme/__tests__/storage.test.ts`（localStorage + settingsClient mock 模式参考）
