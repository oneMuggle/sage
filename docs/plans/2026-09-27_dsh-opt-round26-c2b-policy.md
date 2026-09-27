# DSH 对标优化·第二十六轮：C2b——请求窗口策略五份重复收敛

- **状态**：批次 A 交付中（分支 `feat-dshopt-r26-c2b-policy`，基线 origin/main 含 R25）

## 0. 结论速览

`_resolve_effective_window` / `_check_request_within_window` 在
legacy_routes 与四个 C1 路由组模块中**五份逐字重复**（C1a/b/c 拆分时
整块搬运遗留）。本轮收敛为唯一实现 `backend/api/chat_request_policy.py`：

- `legacy_routes.py`：定义 → 导入（其实际调用方，净 -129 行）；
- 四个 C1 模块（memory / skills / memory_list / skill_draft）：副本
  为**死代码**（grep 全仓无调用、无再导出）→ 直接删除（各 -129 行）；
- 连带清理各模块因副本存在而保留的 now-unused imports
  （estimate_messages_tokens / Sequence / Any / Dict）。

净 **-684 行** + 消除五处漂移风险（改优先级级联不再需要同步五处）。

## 验证

- test_model_catalog_context 60 例（经 legacy_routes 再导出路径覆盖
  两个函数的全部分支）全绿
- import 身份冒烟：五个 api 模块可见名字同一对象（legacy_routes 为
  再导出，C1 模块不再暴露）
- ruff 通过；py38 AST 3.8 兼容；baseline：全部缩行，无需更新

## 不做

- 函数语义/签名任何变更（纯物理收敛）
- `_` 前缀改名（保持既有测试导入路径稳定）
