# 51 — 设计系统规范

> 生效日期：2026-09-27
> 维护人：前端团队
> 关联：`tailwind.config.js`、`src/index.css`

---

## 1. 设计原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | **Local-first** | 所有状态离线可用，UI 不依赖网络；加载骨架屏代替 loading spinner |
| 2 | **Dense-operable** | 操作区域（侧栏、列表、工具栏）密集紧凑；阅读区域（消息正文）宽松舒展 |
| 3 | **Calm-hierarchy** | 用颜色深浅和字号建立层级，不用粗体/颜色爆炸吸引注意力 |

---

## 2. 颜色系统

### 2.1 Token 命名规则

所有颜色通过 CSS 变量（`index.css :root`）定义，Tailwind 通过 `rgb(var(--*-rgb) / <alpha-value>)` 桥接。
**组件中禁止直接写 `#hex` 或 `rgb()` 字面量**，必须使用下方 token。

### 2.2 语义颜色层级

#### 背景（Background）

| Token | Tailwind 类 | Light | Dark | 用途 |
|-------|------------|-------|------|------|
| `--color-bg` | `bg-bg` | `#ffffff` | `#0f172a` | 应用主背景 |
| `--color-bg-muted` | `bg-bg-muted` | `#f9fafb` | `#1f2937` | 次级背景（卡片内嵌区域） |
| `--color-bg-subtle` | `bg-bg-subtle` | `#f3f4f6` | `#374151` | 工具提示背景、代码块底色 |
| `--color-bg-hover` | `bg-bg-hover` | `#f3f4f6` | `#4b5563` | 列表项 hover |
| `--color-bg-active` | `bg-bg-active` | `#e0e7ff` | `#312e81` | 选中/激活态 |

#### Surface（海拔层级）

| Token | Tailwind 类 | Light | Dark | 用途 |
|-------|------------|-------|------|------|
| `--color-surface` | `bg-surface` | `#ffffff` | `#111827` | 卡片默认 |
| `--color-surface-elevated` | `bg-surface-elevated` | `#ffffff` | `#1f2937` | 悬浮面板、下拉菜单 |
| `--color-surface-overlay` | `bg-surface-overlay` | `#ffffff` | `#374151` | 模态框背景 |

#### 文字（Text）

| Token | Tailwind 类 | Light | Dark | 用途 |
|-------|------------|-------|------|------|
| `--color-text` | `text-text` | `#111827` | `#f9fafb` | 主文字 |
| `--color-text-secondary` | `text-text-secondary` | `#6b7280` | `#d1d5db` | 辅助说明 |
| `--color-text-muted` | `text-text-muted` | `#9ca3af` | `#9ca3af` | 时间戳、placeholder |
| `--color-text-inverse` | `text-text-inverse` | `#ffffff` | `#ffffff` | 深色按钮上的文字 |

#### Ink/Faint 语义阶梯

5 级由深到浅的文字层级，用于建立视觉节奏：

| Token | Tailwind 类 | Light | Dark | 使用场景 |
|-------|------------|-------|------|---------|
| `--color-ink` | `text-ink` | `#111827` | `#f9fafb` | 标题、强调文字 |
| `--color-text` | `text-text` | `#111827` | `#f9fafb` | 正文 |
| `--color-muted` | `text-muted` | `#6b7280` | `#d1d5db` | 次要说明 |
| `--color-faint` | `text-faint` | `#9ca3af` | `#9ca3af` | 占位符、禁用文字 |
| `--color-line` | `text-line` | `#e5e7eb` | `#374151` | 分割线、边框 |

#### 边框

| Token | Tailwind 类 | Light | Dark | 用途 |
|-------|------------|-------|------|------|
| `--color-border` | `border-border` | `#e5e7eb` | `#374151` | 默认边框 |
| `--color-border-hover` | `border-border-hover` | `#d1d5db` | `#4b5563` | hover 加深 |

#### 语义色（状态）

| Token | Tailwind 类 | Light | Dark |
|-------|------------|-------|------|
| `--color-success` | `text-success` / `bg-success` | `#10b981` | `#34d399` |
| `--color-error` | `text-error` / `bg-error` | `#ef4444` | `#f87171` |
| `--color-warning` | `text-warning` / `bg-warning` | `#f59e0b` | `#fbbf24` |
| `--color-info` | `text-info` / `bg-info` | `#3b82f6` | `#60a5fa` |

#### ZCode 兼容 token（`ui-*`）

供新增组件优先使用，与 ZCode 设计语言对齐：

| Token | Tailwind 类 | Light | Dark |
|-------|------------|-------|------|
| `--color-background` | `bg-ui-bg` | `#ffffff` | `#0f172a` |
| `--color-card` | `bg-ui-card` | `#f8f9fa` | `#1e293b` |
| `--color-surface` | `bg-ui-surface` | `#f3f4f6` | `#334155` |
| `--color-popover` | `bg-ui-popover` | `#ffffff` | `#1e293b` |
| `--color-foreground` | `text-ui-foreground` | `#111827` | `#f1f5f9` |
| `--color-foreground-subtle` | `text-ui-subtle` | `#6b7280` | `#94a3b8` |

---

## 3. 字体系统

### 3.1 字体族

| 用途 | CSS 变量 | 回退链 |
|------|---------|--------|
| UI 文字 | `--font-ui` | `Inter, 'Noto Sans SC', system-ui, sans-serif` |
| 代码 | `--font-code` | `'JetBrains Mono', monospace` |

### 3.2 字号比例尺（`text-ui-*`）

**新代码优先使用 `text-ui-*`。** 遗留 `text-xs`/`text-sm` 等逐步迁移。

| Token | 计算 | 实际值 | 使用场景 |
|-------|------|--------|---------|
| `text-ui-xs` | `--ui-font-size - 4px` | `10px` | 行数徽章、超小标签 |
| `text-ui-sm` | `--ui-font-size - 2px` | `12px` | 时间戳、侧栏次级文字 |
| `text-ui-caption` | `--ui-font-size - 1px` | `13px` | 工具提示、元信息 |
| `text-ui-base` | `--ui-font-size` | `14px` | 正文（默认） |
| `text-ui-lg` | `--ui-font-size + 2px` | `16px` | 小标题、强调文字 |
| `text-ui-xl` | `--ui-font-size + 4px` | `18px` | 页面标题 |

`--ui-font-size` 默认 `14px`，未来接入"字体大小"设置时只改变量即可全局缩放。

### 3.3 字号使用矩阵

| 场景 | Token |
|------|-------|
| 侧栏列表项（会话标题） | `text-ui-base` |
| 侧栏次级信息（时间戳） | `text-ui-sm` |
| 消息正文 | `text-ui-base` |
| Markdown h1 | `text-ui-xl` |
| Markdown h2 | `text-ui-lg` |
| Markdown h3 | `text-ui-base`（`font-bold`）|
| 代码块头部语言名 | `text-ui-sm` |
| 代码块行数徽章 | `text-ui-xs` |
| 设置项说明文字 | `text-ui-caption` |
| Badge / Tag | `text-ui-xs` |
| 页面标题 | `text-ui-xl` |

---

## 4. 间距系统

基准单位：**4px**（`--space-1`）

| Token | 值 | 典型用途 |
|-------|----|---------|
| `space-1` | `4px` | 图标与文字间距 |
| `space-2` | `8px` | 列表项内 padding、相邻按钮间距 |
| `space-3` | `12px` | 卡片内 padding（密集区） |
| `space-4` | `16px` | 卡片内 padding（标准）、列表项垂直间距 |
| `space-5` | `20px` | 区块间距 |
| `space-6` | `24px` | 页面 section 间距 |
| `space-8` | `32px` | 大区块分隔 |

**密度模式**（Settings > Density）：
- Compact：列表行高 28px，padding 减一档
- Comfortable：列表行高 36px，标准 padding

---

## 5. 圆角层级

| Token | 值 | 使用场景 |
|-------|----|---------|
| `radius-sm` | `3px` | 代码块、Tag、Badge |
| `radius-md` | `6px` | Input、Select、Button |
| `radius-lg` | `8px` | Card、Dialog |
| `radius-xl` | `12px` | Modal、Popover |
| `radius-2xl` | `16px` | 特殊容器 |

**规则**：同一容器内的子元素圆角 ≤ 父容器圆角。

---

## 6. 海拔（Elevation）

背景对比优先于阴影。阴影仅作辅助。

| Level | 背景 | 阴影 | 场景 |
|-------|------|------|------|
| 0 | `bg-bg` | 无 | 应用背景 |
| 1 | `bg-surface` | 无 | 静态卡片 |
| 2 | `bg-surface-elevated` | `shadow-sm` | Hover 卡片 |
| 3 | `bg-surface-elevated` | `shadow-md` | Dropdown |
| 4 | `bg-surface-overlay` + overlay 遮罩 | `shadow-lg` | Modal |

---

## 7. 动效

| Token | 值 | 场景 |
|-------|----|------|
| `transition-fast` | `120ms ease` | Button hover、Icon 切换 |
| `transition-base` | `200ms ease` | Card hover、Panel 展开 |
| `transition-slow` | `300ms ease` | Modal fade、Page transition |

---

## 8. 布局常量

| Token | 值 |
|-------|----|
| `--sidebar-width` | `240px` |
| `--header-height` | `48px` |

---

## 9. 组件规范

### Button

- 高度：`32px`（`py-1.5 px-3`）
- 圆角：`rounded-radius-md`
- 主色：`bg-primary text-text-inverse`
- 次要：`bg-bg-subtle text-text border border-border`
- Hover：背景切换到 `bg-bg-hover`

### Card

- 背景：`bg-surface`
- 边框：`border border-border`
- 圆角：`rounded-radius-lg`
- Padding：`p-4`（标准）/ `p-3`（密集）

### Message

- 消息气泡：无背景，头像在左
- 代码块：`bg-[#282c34]`（深色固定），`rounded-radius-md`
- 工具调用结果：`bg-bg-subtle border border-border rounded-radius-sm`

### Input / Select

- 高度：`32px`
- 圆角：`rounded-radius-md`
- 边框：`border-border`，focus 时 `border-primary`

### 侧栏列表项

- 高度：`32px`（Comfortable）/ `28px`（Compact）
- Hover：`bg-bg-hover`
- Active：`bg-bg-active`
- 文字：`text-ui-base text-text`
- 次级文字：`text-ui-sm text-text-muted`

---

## 10. 禁止清单

| 反模式 | 替代方案 |
|--------|---------|
| `text-gray-500` 等直接颜色 | `text-text-secondary` / `text-muted` |
| `text-xs`/`text-sm`/`text-base`/`text-lg`（新代码） | `text-ui-xs`/`text-ui-sm`/`text-ui-base`/`text-ui-lg` |
| `rounded` / `rounded-lg`（裸值） | `rounded-radius-md` / `rounded-radius-lg` |
| `shadow` 在 Level 0/1 上使用 | 用背景对比代替 |
| `bg-white` / `bg-gray-100` 等字面量 | `bg-bg` / `bg-bg-muted` |
