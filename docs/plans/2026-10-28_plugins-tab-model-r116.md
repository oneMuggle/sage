# R116 PluginsTab 纯数据/纯函数抽离规格

- 日期：2026-10-28
- 基线：`main` `348d6fa62693d4beada04368002928bb01d58088`
- 状态：已开 PR（#2621），待合并
- 编号说明：R116 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：归属可见化弧（R110–R115）已收官，后续插件面的维
  护（发布面对账、名单新鲜度等）都绕不开设置页的插件
  Tab，而该文件 819 行顶格（基线 820 只降不升）自
  R111 起就反复挡下候选。本轮做一次纯机械抽离，把与组
  件状态无关的纯数据与纯函数搬到同目录模型模块，先还出
  行数预算；行为逐字不变，不夹带功能。

## 1. 抽离清单（原样搬移）

- 新 `src/pages/settings/pluginsTabModel.ts`（命名随同
  目录 camelCase 非组件模块惯例），承接：
  `StatusFilter` 类型、`STATUS_BADGE_CLASSES`、
  `MANIFEST_TEMPLATE`、`isRecord`、`errorMessage`、
  `formatTime`，以及原组件内的双语文案对象（以
  `getPluginsTabCopy(en)` 函数形态）、
  `getPluginStatusLabels(en)`、`getPluginEventLabel(en, event)`。
- `PluginsTab.tsx` 改为导入上述符号；组件内保留一行
  别名（copy/statusLabel/eventLabel），全部调用点不动。
- 实测 819 → 686 行（模型文件 160 行）；基线文件不
  tighten（全局紧缩涉及他人文件的存量 slack，不在本轮）。

## 2. 边界

- 纯重构：渲染输出、文案、事件处理、取数与后端接口逐
  字不变（manifest 284，本轮未涉）；不顺手修文件的存
  量格式漂移之外的内容。
- Win7 待对齐（无后端新代码）。

## 3. 测试计划

- 既有 PluginsTab 套件原样通过（只改导入来源的符号对
  测试不可见）；相邻 settings 套件回归。

## 4. 本地证据

- settings 全目录 59 文件 365 例通过（含
  PluginsTab 14 例原样通过）。
- 搬移逐字性机械校验：新旧字符串字面量多重集比对，
  126 个搬移来源字面量在模型文件中全等出现（模型仅
  多 1 个 pluginClient 导入路径字面量）。
- tsc、ESLint（0/0）、architecture（rc=0；全局 slack
  210 → 343，与本文件缩减 133 行吻合）、diff-check、
  diagnostics 全绿；后端零改动。
