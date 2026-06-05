# app/

应用入口、Provider、全局样式、根组件。

- 只能被本目录内文件 import
- **不可**被下层（processes / pages / widgets / features / entities / shared）import
- 承载 Provider 组合（ErrorBoundary, Theme, QueryClient 等）
