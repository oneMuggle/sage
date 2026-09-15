# UI Mock 工作区 (docs/mocks)

> **A10 · UI Mocks In-Repo** — 重大 UI 改动先丢一个可点击的 HTML 原型，
> 设计评审通过再进正式实现（FSD）。

## 为什么

现状问题：UI 改动主要靠口头描述或截图，方向错了要等实现完才发现，返工成本高。

In-repo mock 解决三件事：

1. **先评后做** — 静态 HTML 双击就能打开，比任何描述都直观；方向性错误在原型阶段就暴露
2. **零翻译落地** — mock 与 `tailwind.config.js` 共享设计令牌与 utility 名，class 名可直接搬进 `src/`
3. **onboarding 友好** — 新人通过 mock 理解每个设计决策的来由（设计意图写在 HTML 注释与同名 .md 中）

## 工作流

```
1. 新建 mock          2. 设计评审          3. 实现落地          4. 收尾
   复制 TEMPLATE.md      浏览器打开 HTML       照常开 feature 分支    HTML 头注释标注
   写设计说明(.md)       对照评审 checklist    class 名直接搬进组件    ✅ 已实现，或直接删除
   写 HTML 原型          意见写进 HTML 注释     PR 描述引用 mock 文件
   PR: docs(mock): …     通过 → Approve
```

### 1. 新建 mock

- 文件命名：`<kebab-case-topic>.html`；较复杂的提案配一份同名 `<kebab-case-topic>.md`（从 [TEMPLATE.md](./TEMPLATE.md) 复制）
- 参考样例：[example-redesign.html](./example-redesign.html)（Sidebar + Chat 布局，含明暗主题与折叠式工具调用）
- **必须**：内嵌与实现完全一致的 `tailwind.config` + CSS 变量（从样例文件或
  `tailwind.config.js` + `src/index.css` 复制，禁止另起一套色值）

### 2. 设计评审

- 评审人直接用浏览器打开 HTML（需联网加载 Tailwind CDN），用顶部按钮切换明暗主题
- 评审意见直接写进 HTML 注释或同名 .md 的「评审结论」一节
- 通过标准：达成设计目标 + 未引入新令牌 + 无明显可访问性问题

### 3. 实现落地（FSD）

- mock 里的 class 名直接搬进 `src/` 组件 — 令牌共享，无需任何色值翻译
- mock 中出现但尚不存在的组件结构，在实现时拆成任务清单
- PR 描述中关联原型：`设计原型: docs/mocks/<topic>.html`

### 4. 生命周期

| 状态 | 动作 |
|---|---|
| 已实现且稳定 | HTML 头注释标 `状态: ✅ 已实现 → src/components/…`，或直接删除 |
| 方案废弃 | 直接删除文件（与全局文档规范一致：不保留过时历史版本） |

## 设计令牌与实现共享（重点）

mock 的价值在于「所见即所实现」。约定速查表（来源：`tailwind.config.js` + `src/index.css`）：

| 类别 | 令牌 | utility 名示例 |
|---|---|---|
| 品牌色 | `colors.primary` | `bg-primary` · `text-primary` · `bg-primary/15` · `hover:bg-primary-hover` |
| 背景层级 | `colors.bg.*` | `bg-bg` · `bg-bg-muted` · `bg-bg-subtle` · `bg-bg-hover` · `bg-bg-active` |
| 表面 | `colors.surface.*` | `bg-surface` · `bg-surface-elevated` · `bg-surface-overlay` |
| 文本层级 | `colors.text.*` | `text-text` · `text-text-secondary` · `text-text-muted` · `text-text-inverse` |
| 边框 | `colors.border.*` | `border-border` · `hover:border-border-hover` |
| 语义色 | `colors.success/error/warning/info` | `text-success` · `bg-error/10` |
| 角色徽章 | `colors.role.*` | `bg-role-blue text-role-blue-text` · `bg-role-green text-role-green-text` |
| 记忆强调 | `colors.mem.*` | `bg-mem-subtle text-mem-accent` |
| 间距 | `spacing.space-*` | `p-space-4` · `gap-space-2` · `px-space-3` |
| 圆角 | `borderRadius.radius-*` | `rounded-radius-md` · `rounded-radius-lg` · `rounded-radius-2xl` |
| 阴影 | `boxShadow.*` | `shadow-sm` · `shadow-md` · `shadow-lg` |
| 主题切换 | `data-theme="dark"` | 颜色全部由 CSS 变量驱动，一般不需要 `dark:` 变体 |

**禁止**在 mock 里引入任意色值（如 `bg-[#123456]`）。确需新颜色时，先在
`tailwind.config.js` + `src/index.css` 中讨论加令牌，再在 mock 中使用 —
保证 mock 永远是实现的子集。

## 预览

```bash
# 直接打开（需联网加载 Tailwind CDN）
xdg-open docs/mocks/example-redesign.html

# 或用任意静态服务器
npx serve docs/mocks
```

## 参考

- OpenWorker `ui-mocks/` 实践（`redesign.html` 是其 Tailwind config 的参考源）
- 计划来源：`docs/plans/2026-07-30_sage-optimization-unified.md` §A10
