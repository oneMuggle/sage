# Sage Design System

> 日期：2026-09-21
> 状态：强制约束
> 优先级：最高（覆盖所有其他 UI 规范）

## 1. Product Character

Sage 是一个 **calm, dense, operational** 的个人知识管理工具。
- Calm: 低戏剧、快速响应、不抢注意力
- Dense: 信息密度高，操作效率高
- Operational: 以任务为导向，不是展示型产品

## 2. Theme Modes

支持 3 种主题模式：
- **System**: 跟随操作系统设置
- **Light**: 强制浅色
- **Dark**: 强制深色

主题切换通过 `data-theme='dark'` 属性控制，CSS 变量自动切换。

## 3. Color Palette（语义颜色）

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `--color-background` | `#ffffff` | `#0f172a` | 页面背景 |
| `--color-card` | `#f8f9fa` | `#1e293b` | 卡片背景 |
| `--color-surface` | `#f3f4f6` | `#334155` | 输入框、按钮背景 |
| `--color-popover` | `#ffffff` | `#1e293b` | 下拉菜单、弹窗 |
| `--color-border` | `#e5e7eb` | `#334155` | 边框 |
| `--color-foreground` | `#111827` | `#f1f5f9` | 主文本 |
| `--color-foreground-subtle` | `#6b7280` | `#94a3b8` | 次要文本、说明 |

**禁止**：直接使用 `text-white/60`、`border-black/10` 等临时拼凑色。

## 4. Typography（`text-ui-*` 标尺）

所有操作界面文本**只能**采用以下标尺：

| Token | 计算 | 默认值 | 用途 |
|---|---|---|---|
| `text-ui-xl` | `--ui-font-size + 4px` | 18px | 页面标题 |
| `text-ui-lg` | `--ui-font-size + 2px` | 16px | 区块标题 |
| `text-ui-base` | `--ui-font-size` | 14px | 正文（默认） |
| `text-ui-caption` | `--ui-font-size - 1px` | 13px | 紧凑说明 |
| `text-ui-sm` | `--ui-font-size - 2px` | 12px | 次要信息、时间戳 |
| `text-ui-xs` | `--ui-font-size - 4px` | 10px | 快捷键徽标 |

**基准字号**：由设置中的 `--ui-font-size`（默认 14px）驱动。
**严禁**修改根 `html` 的 `font-size`（避免破坏 CodeMirror/Monaco 渲染）。

**例外**：代码预览、Diff 视口允许保持等宽字号。

## 5. Spacing

基础单元：**4px**。

所有间距必须是 4 的倍数：`p-1` (4px)、`p-2` (8px)、`p-3` (12px)、`p-4` (16px)、`p-6` (24px)、`p-8` (32px)。

## 6. Radius（容器阶梯）

最外层 rounded-xl，内部递减：

| 层级 | Radius | 用途 |
|---|---|---|
| 最外层 | `rounded-xl` (12px) | 页面容器、模态框 |
| 中层 | `rounded-lg` (8px) | 卡片、面板 |
| 内层 | `rounded-md` (6px) | 按钮、输入框 |
| 最小 | `rounded-sm` (4px) | 徽标、标签 |
| 特批 | `rounded-2xl` (16px) | 输入框、弹窗（需要更高视觉权重） |

## 7. Components

### Buttons
- 主按钮：`bg-ui-bg text-ui-foreground border-ui-border`
- 次要按钮：`bg-ui-surface text-ui-foreground`
- 危险按钮：`bg-red-500 text-white`

### Cards
- 背景：`bg-ui-card`
- 边框：`border border-ui-border`
- 圆角：`rounded-xl`

### Inputs
- 背景：`bg-ui-surface`
- 边框：`border border-ui-border`
- 圆角：`rounded-md` 或 `rounded-2xl`（特批）

## 8. Elevation and Depth

**背景对比优先于阴影**。

- Light 模式：通过 `bg-ui-bg` vs `bg-ui-card` 的色差区分层级
- Dark 模式：通过 `bg-ui-bg` (#0f172a) vs `bg-ui-card` (#1e293b) 的色差区分层级

阴影仅用于浮层（弹窗、下拉菜单）：`shadow-lg`。

## 9. Motion

- 快速：动画时长 150-200ms
- 低戏剧：使用 `ease-out` 缓动，不使用弹跳或夸张效果
- 目的性：动画用于引导注意力，不是装饰
