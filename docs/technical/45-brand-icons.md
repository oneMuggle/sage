# Sage 品牌图标资产与复用（45 / 品牌）

> 上次更新：2026-09-02 · 维护者：Sage 团队
>
> 范围：Sage 项目品牌图标的设计资产、生成流水线、UI 接入规范、跨平台缺口与未来补全路径。

## 1. 决策背景

Sage 桌面端需要在所有可见界面与所有打包平台呈现**一致的品牌标识**。早期仅靠 `lucide-react` 图标 + 文字方块占位（典型如 Sidebar 顶部硬编码 `<div>S</div>Sage`），结果是：

- 浏览器 tab 无 favicon（`index.html` 引用了不存在的 `/sage.svg`）
- Welcome 屏用 lucide `<Sparkles />` 占位，缺乏品牌识别
- 桌面窗口与安装包图标与"产品本身"脱节
- 30+ 组件各自拼凑，散落不一致

2026-08 设计阶段产出 `build/source/sage-icon-1024-master.png`（几何 S + 星点 + 青紫渐变 + 深底），并在 27fcb09c 落地为 `build/icon.ico` 与 `build/icon.png` 用于 OS 层。本专题补齐 UI 层（favicon / Welcome / Sidebar / Titlebar）与组件复用基线。

## 2. 资产层级

```
设计母版（本地，gitignored）
├── sage-icon-1024-master.png       ← 已选定的主设计，候选 design-1/2/3 在 candidates/ 留存
└── candidates/                   ← design-1/2/3 候选档案（README.md 说明差异）

可重现的次级母版（force-track，git 历史可见）
├── build/icon.ico                ← Windows 窗口/安装包图标
└── build/icon.png                ← Linux AppImage/deb 安装包图标

Web/UI 资源（Vite publicDir）
├── public/sage.svg               ← 浏览器 favicon（手绘简化矢量版，<2 KB）
├── public/favicon-512.png        ← Apple touch icon / PWA 图标
├── public/favicon-32.png         ← 浏览器标准 fallback
└── public/favicon-16.png         ← 浏览器 tab fallback

代码层
└── src/shared/ui/BrandLogo.tsx   ← 单一共享组件，从 public/sage.svg 引用
```

**关键不变量**：
- `build/icon.ico` / `build/icon.png` 是**已提交**的二进制产物（`git add -f`），可作为可重现的次级母版。即便 `build/source/` 是 gitignored，新 clone 仍能拿到这两份图标。
- `public/sage.svg` 是**手绘简化矢量版**（990 B），不是从 master PNG 反向追踪。语义等价（深底 + 上下渐变丝带 + 白色 4 角星），但**不与 master 像素级一致**。后续如需像素级一致，需要新增 `scripts/sync_master_svg.py`（用 potrace 追踪）。

## 3. `<BrandLogo>` 组件规范

源文件：`src/shared/ui/BrandLogo.tsx`。**所有 favicon 之外的 UI 品牌位点必须通过本组件**，禁止散落实现。

### API

```ts
type BrandLogoSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';
// xs: 16px（Titlebar）
// sm: 24px（Sidebar 顶部）
// md: 32px（卡片 / 通用）
// lg: 48px（页头）
// xl: 64px（Welcome avatar）

interface BrandLogoProps {
  size?: BrandLogoSize;       // 默认 'md'
  withWordmark?: boolean;     // 默认 false；仅 sm/md 启用有意义
  alt?: string;               // 默认 t('brand.alt')
  className?: string;
  testId?: string;            // 默认 'brand-logo'；可透传既有 testid
}
```

### 当前接入位点（截至 2026-09-02）

| 位点 | 文件 | 调用方式 |
|---|---|---|
| Welcome avatar | `src/widgets/welcome/WelcomeHero.tsx` | `<BrandLogo size="xl" testId="welcome-avatar" />` |
| Sidebar 顶部 logo + wordmark | `src/widgets/layout/Sidebar.tsx` | `<BrandLogo size="sm" withWordmark />` |
| Titlebar 左侧（Windows/Linux） | `src/widgets/layout/Titlebar.tsx` | `<BrandLogo size="xs" />` |

### 反模式（commit 时拒绝）

- ❌ 在新位点直接 `<img src="/sage.svg" />` — 必须走 BrandLogo（统一 a11y、testId、尺寸）
- ❌ 重新写硬编码 `<div>S</div>Sage`（这是被替换前的旧实现）
- ❌ 在 BrandLogo 之外的位点硬编码 lucide `<Sparkles />` 作为品牌代表

## 4. macOS 资源缺口（重要）

| 资产 | 当前状态 | 期望 |
|---|---|---|
| `resources/icon.icns` | 2026-06-23 旧版（与新 master 设计**不一致**） | 与 `build/icon.{ico,png}`（2026-09-02 新版）保持一致 |
| `electron-builder.yml` mac 段 | `mac.target: null` — macOS 打包当前禁用 | 启用时需 `icon: build/icon.icns` |

**当前为何不阻塞**：`mac.target: null` 意味着 `.icns` 不会被消费，旧文件虽然视觉过时但不影响发布。

**未来补全路径**（任选其一）：
1. **macOS CI runner**：从 `build/source/sage-icon-1024-master.png` 派生 1024/512/256/128/64/32/16 PNG → `icons.iconset/` → `iconutil --convert icns icons.iconset/`
2. **跨平台 npm 依赖**：引入 `png2icons` 或 `icon-gen`，从单一 1024×1024 PNG 直接生成 `.icns`
3. **手动借用**：在 macOS 工作站一次性生成，提交为 force-track 文件（仿照 `build/icon.ico`）

## 5. 复用流程（新增品牌位点时）

1. 决定 size：从 5 个 size token 中选（不要自定义 px 值）
2. 是否需要 wordmark？只在 Sidebar 类持久 header 启用
3. 是否需要 testId 透传？如该位点已有快照/e2e 测试
4. 调用 `<BrandLogo size=... />`，**不要** 直接 `<img>`
5. 如果现有 i18n key `brand.alt` / `sidebar.brand` 文案不合适，覆盖 `alt` prop 而不是改字典
6. 提交前跑 `npm run test:run` + `npm run typecheck`

## 6. 变更记录

| 日期 | 改动 | Commit |
|---|---|---|
| 2026-08 | 设计阶段产出 master + 3 候选 | （本地，未提交） |
| 2026-09-02 | OS 层刷新 `build/icon.{ico,png}` | 27fcb09c |
| 2026-09-02 | UI 层接入：favicon / Welcome / Sidebar / Titlebar + `<BrandLogo>` 组件 | （本 PR feat/icon-ui-application） |

## 7. 相关文件

- `public/sage.svg`, `public/favicon-{16,32,512}.png` — UI 资源
- `src/shared/ui/BrandLogo.tsx` — 组件实现
- `src/shared/ui/__tests__/BrandLogo.test.tsx` — 单测
- `src/widgets/welcome/WelcomeHero.tsx` — Welcome 接入
- `src/widgets/layout/Sidebar.tsx` — Sidebar 接入
- `src/widgets/layout/Titlebar.tsx` — Titlebar 接入
- `electron-builder.yml` — mac 段注释说明 .icns 缺口
- `build/source/candidates/README.md` — 候选设计档案
- `docs/plans/2026-09-02_icon-ui-application.md` — 实施计划（实施完成后删除，不归档）