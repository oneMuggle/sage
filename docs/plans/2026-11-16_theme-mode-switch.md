# 主题模式三态开关（浅色 / 深色 / 跟随系统）

## 背景与目标

Sage 的主题模式默认是 `system`（`ThemeProvider` 的 `defaultMode`），按
`prefers-color-scheme` 跟随操作系统。但设置页目前只有主题配色画廊
（`ThemeSelector` / `ThemeGallery`），**没有**亮/暗/跟随系统三态切换 UI：
用户只能通过 `Ctrl+Shift+D` 或命令面板"切换主题"在亮/暗之间切换，
一旦切换就把偏好固化为显式 `light`/`dark`，且没有入口再回到 `system`。

目标：在设置 → 基础 → 主题区域新增三态开关，复用已有的
`useTheme().mode / setMode` 与持久化链路（localStorage `sage-theme` +
后端偏好 `theme_mode`），让用户可以随时选择浅色、深色或跟随系统。

## 涉及的文件与模块

| 文件                                                    | 变更                                     |
| ------------------------------------------------------- | ---------------------------------------- |
| `src/pages/settings/ThemeModeSelect.tsx`                | 新增：三态分段控件（SettingRow 包装）    |
| `src/pages/settings/BasicTab.tsx`                       | 主题区域标题下插入 `<ThemeModeSelect />` |
| `src/shared/lib/i18n/locales/zh/settingsUi.ts`          | 新增 4 个文案 key                        |
| `src/shared/lib/i18n/locales/en/settingsUi.ts`          | 新增 4 个文案 key                        |
| `src/pages/settings/__tests__/ThemeModeSelect.test.tsx` | 新增：渲染/切换/系统态描述测试           |
| `docs/technical/` 对应设置章                            | 补充三态开关说明                         |

## 技术方案

- 复用 `useTheme()`（`src/app/providers/useTheme.ts`）：`mode` 有
  `'light' | 'dark' | 'system'` 三态，`setMode` 已负责写
  localStorage + 后端偏好（`entities/theme/storage.ts`）。
- `ThemeProvider` 已有 `matchMedia('(prefers-color-scheme: dark)')`
  监听，选择 `system` 后系统主题变化实时生效，无需新增逻辑。
- 控件形态：`role="radiogroup"` + 三个 `role="radio"` 按钮
  （浅色 / 深色 / 跟随系统），激活项高亮；`system` 态下 SettingRow
  描述动态显示"跟随系统（当前系统为深色/浅色）"。
- 不改变 `Ctrl+Shift+D` / 命令面板的既有行为（仍显式设为 light/dark），
  但用户可用本开关回到 `system`。

## 实施步骤

- [x] 步骤 1：新建 worktree `feat/theme-mode-switch`（基于 origin/release/win7）
- [x] 步骤 2：实现 `ThemeModeSelect` 组件并接入 `BasicTab`
- [x] 步骤 3：补充 zh/en i18n 文案
- [x] 步骤 4：新增组件测试（渲染、三态切换、system 描述）
- [x] 步骤 5：运行 lint / typecheck / 相关 vitest
- [x] 步骤 6：提交并开 PR（release/win7 #3094）；main 待 cherry-pick

## 风险评估与依赖

- 影响面仅设置页 UI；主题解析/持久化逻辑不变。
- 后端偏好接口接受任意字符串，`system` 无需后端改动。
- 架构基线（architecture-baseline.json）如因新增文件触发棘轮，
  按分支实测值更新。
