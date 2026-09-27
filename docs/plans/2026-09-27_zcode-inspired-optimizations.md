# ZCode 启发前端优化方案

> 日期：2026-09-27
> 分支：feat/zcode-inspired-optimizations
> 状态：已完成

---

## 背景与目标

参考 ZCode（/home/fz/project/ZCode）的工程实践，对 Sage 前端进行三方面优化：

1. **设计系统文档化** — 建立 `docs/technical/48-design-system.md`，统一视觉语言
2. **架构治理工具化** — FSD 依赖方向自动检查，防止层级违规
3. **消息渲染增强** — 折叠代码块、表格横滚、字体 token 化

---

## 现状分析

### 已有基础（无需从零开始）

| 方面 | 现状 |
|------|------|
| 语义化颜色 token | ✅ `tailwind.config.js` 已有 `bg-*`、`surface-*`、`text-*`、`border-*` |
| CSS 变量体系 | ✅ `index.css` `:root` 已有完整颜色变量（含 RGB 形式） |
| ZCode token 雏形 | ✅ 已有 `ui-bg`、`ui-card`、`ui-surface` 等 6 个 token |
| FSD 层级 | ✅ `app → pages → widgets → features → entities → shared` 规则存在 |
| 架构基线 | ✅ `architecture-baseline.json` 记录文件大小上限 |

### 差距（本次要填补）

| 方面 | 差距 |
|------|------|
| 设计文档 | ❌ 无 `48-design-system.md`，视觉规范未文档化 |
| 字体 token 比例尺 | ❌ 直接使用 `text-xs`/`text-sm`/`text-base`/`text-lg`，无语义字号 |
| FSD 依赖检查 | ❌ 无工具强制，层级违规只靠人工 review |
| 消息区代码块折叠 | ❌ 长代码块始终展开，无折叠机制 |
| 表格横滚 | ❌ 消息内宽表格可能撑破容器 |

---

## 实施步骤

### Task 1：DESIGN.md 设计系统文档

**输出文件：** `docs/technical/48-design-system.md`

**内容结构：**
```
1. 设计原则（3 条：Local-first、Dense-operable、Calm-hierarchy）
2. 颜色系统（token 表、语义层级、暗色映射规则）
3. 字体系统（比例尺定义、使用场景矩阵）
4. 间距系统（4px base、密度模式对应）
5. 圆角层级（radius-sm/md/lg/xl 使用场景）
6. 海拔层级（elevation levels: bg → surface → elevated → overlay）
7. 组件规范（Button/Card/Message/Input 的视觉规格）
```

---

### Task 2：字体比例尺 token 化

**在 `tailwind.config.js` 中扩展语义字体大小：**

```js
fontSize: {
  'ui-xs':   ['11px', { lineHeight: '16px' }],  // 标签、徽标、元信息
  'ui-sm':   ['12px', { lineHeight: '16px' }],  // 辅助文字、时间戳
  'ui-base': ['13px', { lineHeight: '20px' }],  // 正文（密集模式）
  'ui-md':   ['14px', { lineHeight: '22px' }],  // 正文（标准）
  'ui-lg':   ['16px', { lineHeight: '24px' }],  // 小标题
  'ui-xl':   ['18px', { lineHeight: '28px' }],  // 页面标题
  'ui-2xl':  ['22px', { lineHeight: '32px' }],  // 大标题
}
```

**迁移范围（首批）：**
- `src/widgets/chat/Message.tsx` — Markdown 渲染组件
- `src/widgets/sidebar/` — 侧栏列表项

---

### Task 3：FSD 依赖方向检查（import-lint）

**工具：** `eslint-plugin-import` 的 `no-restricted-paths` 规则

**FSD 约束：**
```
app       → 可导入所有层
pages     → 可导入 widgets/features/entities/shared
widgets   → 可导入 features/entities/shared
features  → 可导入 entities/shared
entities  → 可导入 shared
shared    → 不可导入其他层
```

**CI：** 现有 `npm run lint` 已跑 ESLint，无需额外 CI 步骤。

---

### Task 4：消息渲染增强

**4a. 代码块折叠（ShikiCodeBlock）**
超过 30 行的代码块默认折叠，显示"展开全部 N 行"按钮。

**4b. 表格横向滚动**
消息内 `<table>` 外层加 `overflow-x-auto`，表格用 `min-w-max`。

**4c. 消息字体 token 迁移**
`Message.tsx` 内 Markdown 渲染组件中的 `text-xs`/`text-sm`/`text-base`/`text-lg` 替换为 `text-ui-*`。

---

## 优先级与工作量

| Task | 优先级 | 预估工作量 | 风险 |
|------|--------|-----------|------|
| Task 1: DESIGN.md | P0 | 1h | 低 |
| Task 2: 字体 token 化 | P0 | 1.5h | 低 |
| Task 3: FSD import-lint | P1 | 1h | 中 |
| Task 4a: 代码块折叠 | P1 | 45min | 低 |
| Task 4b: 表格横滚 | P1 | 30min | 低 |
| Task 4c: 消息字体迁移 | P1 | 30min | 低 |

---

## 验收标准

- [x] `docs/technical/51-design-system.md` 存在且内容完整
- [x] `text-ui-*` token 在 `tailwind.config.js` 中定义（已预存在）
- [x] `Message.tsx` 中所有字号改用 `text-ui-*`
- [x] 侧栏列表项使用 `text-ui-sm`（7 个文件完成迁移）
- [x] FSD import-lint 规则在 ESLint 中配置，`npm run lint` 无 error（已预存在）
- [x] 长代码块（>30行）默认折叠，可展开（已预存在）
- [x] 消息内表格超出容器宽度时横向滚动（已预存在 `overflow-x-auto`）
- [ ] 长代码块（>30行）默认折叠，可展开
- [ ] 消息内表格超出容器宽度时横向滚动，不撑破

---

## 不在本次范围内

- 远程工作区支持（与核心场景关联弱）
- 插件市场（架构量大，独立 feature）
- 对话分享功能（独立 feature）
- 后台空闲任务调度（后端为主）
