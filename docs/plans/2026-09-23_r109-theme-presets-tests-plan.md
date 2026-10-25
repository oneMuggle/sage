# R109 批次计划 —— 主题预设数据完整性测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r109-scan`（基于 origin/main 8b27eaf6）

## 背景

`src/entities/theme/presets.ts`（412 行，6 套基础主题 × 明暗两套 22 字段配色）
与 `decorative-presets.ts`（339 行，5 套装饰主题带封面/渐变）为纯数据模块，
全仓无同名测试。主题新增/改色属高频人工编辑，字段漏写、格式错、id 撞车
（base 与装饰 `getThemeById` 双表查询存在语义歧义风险）均无防线。

## 批次内容

新增 `src/entities/theme/__tests__/presets.test.ts`（8 用例）：

- **基础主题**：6 id 唯一且顺序稳定；明暗两套 22 字段齐全且格式合法
  （`#rrggbb` 或 `rgba(r,g,b,a)`）；明暗 bg 不同、暗色 bg 非纯白；text ≠ bg
  可读性；
- **装饰主题**：5 id 唯一顺序稳定；cover/渐变降级字段非空；配色字段全集
  合法；装饰 id 不与基础 id 撞车（getThemeById 双表歧义防线）；
- **getThemeById / DEFAULT_THEME_ID**：默认主题存在且为 indigo；基础/装饰
  均可查到；未知 id 返回 undefined。

## 验证矩阵

- 本机 vitest：8/8 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest。

## 不做

- 不改生产数据；demoChatScript 维持不测。
