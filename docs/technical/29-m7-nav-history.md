# 29 — M7 Nav-history

## Overview

`Sage` 提供浏览器式的前进/后退导航,实现形式是 `NavHistoryProvider` +
`useNavigationHistory` hook + `TitlebarActions` UI。该模块替代了原本的"按
浏览器 back/forward 按钮"的隐式行为,把 `pathname` 栈与 cursor 显式管理,
使得跨路由前进/后退在标题栏 ↩ 按钮上直接可见。

> 本文档是 M7 (Nav-history) 模块的"事后归档"——原始 spec 在
> `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md` §3.3。
> 实施以 main 侧 `0ab979d..283d207` 10 个 commit (含 `aa235a2` TitlebarActions
> + `dd43561` Layout render) 为蓝本 byte-for-byte port 到 `release/win7`。
> drag region CSS fix (e35c590) 的 `no-drag` 部分手工 amend 到 aa235a2。

## Architecture

### 文件清单

```
src/app/providers/NavHistoryProvider.tsx                  # 新增: pathname 栈 + cursor + skipNextRef
src/app/providers/__tests__/NavHistoryProvider.test.tsx   # 新增: 4 specs + 累计 ~12 tests
src/shared/lib/useNavigationHistory.ts                   # 新增: hook + noop fallback
src/shared/lib/__tests__/useNavigationHistory.test.tsx   # 新增: 1 spec + fallback tests
src/widgets/layout/TitlebarActions.tsx                   # 新增: ◀ / ▶ 按钮 + no-drag class
src/widgets/layout/__tests__/TitlebarActions.test.tsx    # 新增: 4 tests (渲染 + 禁用 + 点击 + no-drag)
src/widgets/layout/Layout.tsx                            # +(不动): 通过 Titlebar 子树自动 mount
src/App.tsx                                              # +9/-5: <BrowserRouter><NavHistoryProvider><Routes>
src/shared/lib/i18n/{zh,en}.ts                           # +6 keys (nav.back/forward + time.today/yesterday/this_week/earlier)
```

### 核心数据结构

`NavHistoryProvider.tsx`:

```typescript
const MAX_HISTORY = 50;

interface HistoryEntry {
  path: string;
}

interface NavHistoryContextValue {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
}
```

内部 state:
- `stack: HistoryEntry[]` —— 累积的 pathname 栈
- `cursor: number` —— 当前活跃 entry 在栈中的索引

外部消费 (`useNavigationHistory`):

```typescript
export function useNavigationHistory(): NavHistoryContextValue {
  const ctx = useContext(NavHistoryContext);
  if (!ctx) {
    return {
      canBack: false,
      canForward: false,
      back: () => {},
      forward: () => {},
    };
  }
  return ctx;
}
```

## 关键设计

### pathname 变更如何触发 stack 更新

```typescript
export function NavHistoryProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();

  const [stack, setStack] = useState<HistoryEntry[]>(() => [
    { path: buildPath(location) },
  ]);
  const [cursor, setCursor] = useState(0);

  // 关键:`skipNextRef` 防止 back()/forward() 自身触发的 navigate() 在 effect 中
  // 被当成新 entry
  const skipNextRef = useRef(false);

  useEffect(() => {
    if (skipNextRef.current) {
      skipNextRef.current = false;
      return;
    }
    const path = buildPath(location);
    setStack((prevStack) => {
      const prevEntry = prevStack[cursor];
      if (prevEntry && prevEntry.path === path) {
        return prevStack; // Same path as current cursor — no-op
      }
      if (navigationType === NavigationType.Replace) {
        const next = prevStack.slice();
        next[cursor] = { path };
        return next;
      }
      // Discard any forward entries past the cursor, then append.
      // 溢出 MAX_HISTORY 时丢最早 entry。
    });
  }, [location, navigationType, cursor]);
  ...
}
```

### back() 与 forward()

```typescript
const back = useCallback(() => {
  if (cursor > 0) {
    skipNextRef.current = true;  // 防止 effect 把 back 自身再加为新 entry
    setCursor(cursor - 1);
    navigate(-1);
  }
}, [cursor, navigate]);

const forward = useCallback(() => {
  if (cursor < stack.length - 1) {
    skipNextRef.current = true;
    setCursor(cursor + 1);
    navigate(1);
  }
}, [cursor, stack.length, navigate]);
```

## 路由集成

`App.tsx`:

```tsx
<BrowserRouter>
  <NavHistoryProvider>
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="welcome" element={<Welcome />} />
        <Route path="chat" element={<ChatRoute />} />
        ...
      </Route>
    </Routes>
  </NavHistoryProvider>
</BrowserRouter>
```

**关键约束**:`NavHistoryProvider` 必须在 `<BrowserRouter>` **内部**,因为它
调用的 `useLocation` / `useNavigate` / `useNavigationType` 需要路由上下文。
否则第一次 `useEffect` 会报 "useLocation() may be used only in the context of a
<Router> component" 错误。这就是 main 侧 commit `283d207` 修复的核心。

## UI 集成 (TitlebarActions)

`TitlebarActions.tsx` 是个纯组件:

```tsx
export function TitlebarActions() {
  const { t } = useI18n();
  const history = useNavigationHistory();

  const canBack = history?.canBack ?? false;
  const canForward = history?.canForward ?? false;

  return (
    <div className="no-drag flex items-center gap-1">
      <button
        type="button"
        aria-label={t('nav.back')}
        disabled={!canBack}
        onClick={() => history?.back()}
        className="p-1.5 rounded hover:bg-bg-hover ..."
      >
        <ArrowLeft className="w-4 h-4" />
      </button>
      <button ... aria-label={t('nav.forward')} disabled={!canForward} ...>
        <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );
}
```

`no-drag` class 在外层 div 上(来自 `28-phase5-titlebar.md`),按钮不会被
Electron frameless window 的 drag region 吞掉鼠标事件。

`Titlebar.tsx`(在 M9 port 中创建)的三个分支都会 render `<TitlebarActions />`:
- Web 分支: 默认
- macOS 分支: 给 native traffic lights 让出 28px(`pt-7`)
- Win/Linux 分支: `drag` 类让外层 div 整个可拖动

## 测试覆盖

| 文件 | 测试数 | 覆盖 |
|---|---|---|
| `NavHistoryProvider.test.tsx` | 4 specs × ~3 cases | initial state + push new path + MAX_HISTORY=50 丢最早 + back/forward cursor 增减 + replace 时覆盖当前 entry |
| `useNavigationHistory.test.tsx` | 1 spec | provider 外 fallback noop |
| `TitlebarActions.test.tsx` | 4 | 渲染 + disabled state + 点击调 context.back()/forward() + no-drag class 验证 |

## win7 适配差异

- **App.tsx 嵌套保留 win7 现有 routes**: 当 cherry-pick `283d207` 时,HEAD
  (win7) 已有 `/welcome` / `/scheduled` / `/orchestration` 等路由;这些不属于
  283d207 范围但需要保留。直接合并 HEAD 与 main 结构,不删除 win7 路由。
- **CHANGELOG i18n keys**: M7 加了 nav.* + time.* 共 6 keys。原 win7 上
  `translations.test.ts` hardcoded `83 keys`(对应 M1-M6 累计)。M9 加 3 个
  titlebar.* keys。加上原本 win7 上 M6 时漏补的 `chat.config_warning_action`
  等 9 keys。一共 `83 + 6 + 3 + 9 = 101`。本分支 `d97845b` 同步更新了此 hardcoded
  期望值。
- **drag region 部分手工 amend**: e35c590 (`fix: 标题栏无法拖动窗口`) 在 main
  上同时改 Titlebar.tsx + TitlebarActions.tsx + index.css。在 win7 上
  TitlebarActions.tsx 当时不存在(M7 T13 aa235a2 才创建),所以 cherry-pick
  e35c590 时跳过 TitlebarActions.tsx 部分,在 M7 T13 commit 时手工 amend 加
  `no-drag` class(本分支 commit `33c756e` 即为 amend 后的样子)。

## 与 M9 Phase5 Titlebar 的关系

- M7 的 `<TitlebarActions />` 是 M9 `<Titlebar />` 的子组件 — M9 的三个
  平台分支都会 render 它。
- 两个 module 强耦合,无法独立 port。本分支 `feat/win7-m7-nav-history` 是
  **(M7+M9 联合 port)**,17 commits 包含 4 M9 + 1 drag fix + 9 M7 + 3 fixup。
- 详见 `28-phase5-titlebar.md`。

## 参考

- **父 spec**: `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md` §3.3 + §4.5
- **本模块 plan**: `docs/superpowers/plans/2026-06-29-win7-m7-nav-history-impl.md` Phase 4
- **main M7 source commits**: `0ab979d..283d207` (10 commits,含 aa235a2/dd43561)
- **main drag fix**: `e35c590` (TitlebarActions 部分手工 amend 到 `33c756e`)
- **df747bd partial**: `fcec066` (tsc-error fix,仅 windowControlsClient.test 部分应用)
- **兄弟模块**: `docs/technical/28-phase5-titlebar.md` (Titlebar container)
- **用户角度**: `docs/user-manual/07-titlebar.md` (使用前进/后退与窗口控制按钮)
