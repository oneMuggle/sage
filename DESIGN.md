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

## 10. Information Density（信息密度）

Sage 面向长时间会话用户，必须保持**高密度可读性**：

### 聊天消息区
- 消息间 padding: `py-2`（8px），不用 `py-4` 以上
- 用户消息与助手消息用背景色差区分，不用大间距
- 工具调用卡片紧凑排列，折叠状态高度 ≤ 40px

### 侧边栏
- Section header 高度: `h-8`（32px）
- 列表项高度: `h-9`（36px）或 `py-1.5`（6px 上下）
- Section 间分隔: `border-t border-ui-border` + `mt-1`（4px）

### 设置页
- 使用卡片分组，不用大标题 + 大间距
- 开关/选择器行高: `h-10`（40px）
- 说明文字: `text-ui-sm text-text-secondary`

### 禁止
- ❌ "营销式"大间距（`py-16`、`py-20` 等）
- ❌ 全宽渐变背景作为默认 UI 语言
- ❌ 无层级理由混用 `bg-ui-bg` / `bg-ui-card` / `bg-ui-surface`

## 11. Tool Call 渲染（工具调用展示）

参考 ZCode 的 ToolCallBlocks 设计，工具调用按类型分发渲染器：

### 通用规则
- 折叠态：图标 + 工具名 + 一句话摘要，高度 ≤ 40px
- 展开态：完整参数 + 结果预览
- 状态色：运行中=`text-info`，成功=`text-success`，失败=`text-error`

### 按工具类型

| 工具 | 折叠态显示 | 展开态显示 |
|------|-----------|-----------|
| Bash | 命令首行（截断 60 字符） | 完整命令 + 输出（滚动区 max-h-48） |
| FileEdit | 文件名 + 操作（创建/修改/删除） | Diff preview（SplitDiff 组件） |
| WebSearch | 查询词 + 结果数 | 结果列表（标题+链接+摘要） |
| Read | 文件路径 | 文件内容（带行号） |
| Write | 文件路径 + 字节数 | Diff（旧 vs 新） |

### 图标
- Bash: `Terminal`
- FileEdit/Write: `FileEdit`
- Read: `FileText`
- WebSearch: `Globe`
- 默认: `Wrench`

## 12. Icon Sizing（图标尺寸）

| 场景 | 尺寸 | Tailwind |
|------|------|----------|
| 导航栏 | 20×20 | `w-5 h-5` |
| 侧边栏 Section | 16×16 | `w-4 h-4` |
| 按钮内 | 16×16 | `w-4 h-4` |
| 文本内联 | 14×14 | `w-3.5 h-3.5` |
| 工具调用折叠态 | 14×14 | `w-3.5 h-3.5` |
| 空状态插图 | 48×48 | `w-12 h-12` |

**禁止**：同一组件内使用 >2 种图标尺寸。
