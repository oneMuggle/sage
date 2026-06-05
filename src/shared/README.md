# shared/

通用代码：ui-kit / lib / config / api-client / types / styles。

- **不依赖任何上层**——`shared` 是叶子节点
- 可被任意上层（features / entities / widgets / pages / processes / app）import
- 内部组织：
  - `shared/ui/`：通用 UI 组件（Button / Input / ErrorState / LoadingState 等）
  - `shared/lib/`：纯函数工具
  - `shared/config/`：环境配置
  - `shared/api-client/`：HTTP 客户端
  - `shared/types/`：跨实体共享类型
  - `shared/styles/`：全局样式
