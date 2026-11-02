# UX N4：设置页标题层级与整体美化（2026-11-01）

> 分支：`feat/ux-n4-settings-visual`  
> 基线：`origin/main`（N3 合并后）

## 问题

- 设置页没有 tab 级页面标题；内容直接从摘要卡开始。
- 各 tab 手写 section 标题至少 4 种样式（text-sm / text-ui-base / text-ui-md / text-ui-lg），
  与 `SettingRow` 的设置项名称（text-sm）几乎同级，用户无法区分一级/二级标题。
- 左侧导航分组标题过小，选中态弱；内容区缺少卡片与呼吸感。

## 实现

- `components.tsx` 新增：
  - `SettingsPageHeader`：h1（text-ui-xl）+ 描述；
  - `SettingsSection`：h2 卡片容器（供后续 tab 增量迁移）。
- `Settings.tsx`：
  - 内容区顶部新增 sticky 页头（当前 tab 标题 + `settings.page_description`）；
  - 内容区加 `settings-content` 类与 `space-y-6`；
  - 左侧导航分组标题改为 `text-ui-xs font-semibold`，选中项加 ring 与 `aria-current`。
- 新增 `src/pages/settings/settings.css`：
  - 顶层 `section` 统一卡片（圆角/边框/背景/内边距）；
  - `.settings-content h2` 统一为 `text-ui-lg`；
  - `.settings-content h3` 统一为 `text-ui-base`；
  - 最后一行 SettingRow 去除重复底边框。
  - 用 CSS 覆盖而非改 25 个文件，新 tab 自动继承。
- i18n 新增 `settings.page_description`（中英）。

## 验证

- typecheck 通过；
- `vite build` 通过（证明 `@apply` 合法）；
- Vitest：components / Settings.anchor / OrchestrationTab / BasicTab → **72 passed**；
- eslint 0 error；architecture 通过。

## 剩余

- 桌宠安装包重新发布（代码已双分支对齐，按用户要求暂未重打）。
