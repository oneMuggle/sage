# app/providers/

应用顶层 Provider 组合。所有 Provider 在此聚合,由 `AppProviders` 统一对外暴露。

**层级（外→内）：** `ErrorBoundary` > `ThemeProvider` > `QueryClientProvider` > `{children}` > `ToastProvider`

| Provider            | 依赖          | 职责                                                                 |
| ------------------- | ------------- | -------------------------------------------------------------------- |
| `ErrorBoundary`     | (none)        | 捕获子树未处理错误,展示 fallback UI + 重试                           |
| `ThemeProvider`     | (none)        | light / dark / system 三态切换,写 `<html class="dark">` 配合 Tailwind |
| `QueryClientProvider` | `@tanstack/react-query` | 服务端状态缓存根(staleTime 30s, retry 1)                     |
| `ToastProvider`     | `sonner`      | 顶层 `<Toaster>`,订阅 theme 让颜色随主题切换                         |

**使用约束：**

- 业务组件 **不可** 直接 import 此目录下文件(只能从 `app/` 同层或通过 `AppProviders` 间接获得)
- 需要 toast 能力:`import { toast } from 'sonner'`
- 需要当前主题:仅在 `app/` 内可用 `useTheme()`
