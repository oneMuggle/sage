# pages/

路由级页面。Sage 当前页面：Chat / Knowledge / Skills / Agents / Memory / Settings。

- 路由：`/` → `pages/Chat`，`/settings` → `pages/Settings`，等等
- pages 组合 widgets 与 features，但 **不直接实现业务逻辑**
- pages 可以 import：widgets / features / entities / shared
- pages **不可**直接 import：app / processes（通过 router 间接引用）
