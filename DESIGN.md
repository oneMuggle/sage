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

| 用途 | Duration | Easing | Tailwind class |
|---|---|---|---|
| 即时反馈（按钮 hover、icon 切换） | 120ms | `ease-out` | `transition-fast` |
| 常规过渡（面板展开、路由切换） | 200ms | `ease-out` | `transition-base` |
| 大范围重排（sidebar 折叠、模态框） | 300ms | `ease-out` | `transition-slow` |

原则：
- **低戏剧**：不使用弹跳、回弹或夸张缩放
- **目的性**：动画用于引导注意力，不是装饰
- **可中断**：所有过渡在用户交互时立即响应，不等待完成

## 10. Density（信息密度）

两档密度，通过 `[data-density]` 属性切换，默认 `comfortable`。

| Token | Comfortable | Compact | 影响范围 |
|---|---|---|---|
| `--density-msg-gap` | 16px | 8px | 消息列表 vertical gap |
| `--density-msg-py` | 10px | 6px | 消息气泡 vertical padding |
| `--density-msg-px` | 14px | 10px | 消息气泡 horizontal padding |
| `--density-setting-row-py` | 12px | 8px | 设置行 vertical padding |
| `--density-sidebar-item-py` | 8px | 4px | 侧栏条目 vertical padding |

切换方式：在 `<html>` 上设置 `data-density="compact"` 或 `data-density="comfortable"`。

组件中引用密度变量时使用任意值语法：`py-[var(--density-msg-py)]`。

## 11. 状态与反馈

| 状态 | 颜色 | 用途 |
|---|---|---|
| Success | `--color-success` | 操作完成、保存成功 |
| Error | `--color-error` | 表单校验失败、请求异常 |
| Warning | `--color-warning` | 需要注意、即将过期 |
| Info | `--color-info` | 提示信息、帮助说明 |
