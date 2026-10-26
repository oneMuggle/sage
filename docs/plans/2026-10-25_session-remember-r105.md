# R105 仅本次会话记住（session 级 remember）规格

- 日期：2026-10-25
- 基线：`main` `1708e1efe6fadb39084b9ee534ceb3a7157d753a`
- 状态：已合并（PR #2511）
- 编号说明：R105 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：审批「记住我的选择」至今只有永久一档——用户只想
  在当前对话里放行也要先落一条永久规则、事后再去设置页
  删（或忘了删，信任面越攒越大）。R104 取证曾判此功能
  「过大」；本轮复核发现管线其实齐备：会话身份有现成
  的 `ToolExecutionContext`（ContextVar）贯穿工具分发与
  审批归因，enforcer 的 `_match_rules` 是唯一合并点，故
  可在单轮内以小而明确的缝完成。

## 1. 目标与语义

- 审批应答新增与「记住范围（工具/整插件）」正交的
  「记住时长」：`permanent`（默认，行为同从前）/
  `session`（仅当前 chat 会话）。
- session 规则只存进程内存（按 session 隔离、上限
  淘汰），永不写 settings；后端进程重启即消失，自动
  回到逐次询问（fail-safe）。
- 求值合并：enforcer 在当前存在工具执行上下文时把该
  会话规则与持久规则一起按 deny > allow > ask 裁决；
  无上下文（后台任务/单测）时完全不生效，行为与从前
  逐字一致。持久 deny 永远压过会话 allow（与既有
  deny 优先一致；且持久 deny 命中时根本不会弹审批，
  不存在用会话授权绕开持久拒绝的路径）。
- 会话归属由服务端在创建审批请求时从
  `ToolExecutionContext` 捕获到请求对象上（不下发前
  端、客户端不可指定）；应答侧据此定位存储。请求无
  会话归属而用户选了 session → 降级为不记住，绝不静
  默转成永久规则。
- pattern 派生与持久化共用同一道安全闸（fnmatch 元字
  符拒绝、整插件范围只认服务端权威插件名）。

## 2. 边界

- 不改持久规则的任何语义与存储结构；设置页规则管理
  器只管持久规则，会话规则不在其中出现（短命、进程
  内），本轮不做会话规则的查看/撤销 UI。
- 会话规则不跨会话、不跨进程；不做 TTL/手动过期
  （会话结束与进程重启即自然失效；存储另有容量上限
  淘汰防无界增长）。
- 子代理等共享同一 `ToolExecutionContext` 的执行与主
  会话同属一个会话边界，会话规则同样生效；没有设置
  上下文的执行路径天然不受影响。
- 远程渠道语义不变：时长选择只存在于本地审批对话框
  的记住区内，默认 permanent 与从前完全一致。
- Win7 分支按既有口径待对齐（新代码保持 py38 兼容
  写法）。

## 3. 实现要点

- `backend/tools/permissions.py`：进程内会话规则存储
  （`remember_session_rule` / `session_rules_for` /
  `clear_session_rules`，去重同 R99 口径）；enforcer
  `_match_rules` 合并会话规则。
- `backend/services/permission_gate.py`：
  `ApprovalRequest.session_id`（`create()` 时捕获，不
  进 `to_dict`）；审计归属改用同一捕获值（兜底现查）。
- `backend/api/permission_routes.py`：应答体新增
  `remember_duration`（默认 permanent，老客户端不带
  即从前行为）；pattern 安全派生抽共用函数，session
  分支写会话存储。
- ApprovalDialog：记住区新增时长二选一（永久/仅本
  次会话），默认永久、新请求重置；Electron
  `permissions_answer` body 透传 `remember_duration`
  （无新命令，manifest 不变）。

## 4. 测试计划

- 后端单测：存储去重/会话隔离/容量淘汰/清空；
  enforcer 有上下文时会话 allow 生效、会话 deny 压
  持久 allow、持久 deny 压会话 allow、会话 allow
  压持久 ask、无上下文/异会话不生效、插件通配仍查
  权威身份。
- 后端 API：session 时长应答后 settings 不动而会话
  存储命中；无会话归属降级不记；整插件范围 + 会话；
  fnmatch 闸在会话路径同样拒绝；默认时长回归永久。
- 前端：时长区随记住勾选显隐、payload 透传三态
  （永久默认/会话/整插件+会话）、新请求重置；既有
  payload 断言随新字段更新。
- 通用：相邻回归（enforcer/gate/routes/规则管理系
  列）、Ruff 全库、py38、tsc、ESLint、architecture、
  silent-exceptions、diff-check、diagnostics 0。

## 5. 本地证据（2026-10-25）

- 后端：新增单测 9 例（存储去重/隔离/容量淘汰 +
  enforcer 五种合并裁决）+ API 契约 6 例（会话写存
  储不动 settings/无归属降级/整插件+会话/fnmatch
  闸/默认永久回归）；与 routes/enforcer/gate 及规
  则管理相邻套件共 156 例、agent/chat 集成 79 例
  通过；Ruff 全库、py38、silent-exceptions 全绿。
- 前端：ApprovalDialog 新增 4 例（显隐/session 透
  传/整插件+会话/新请求重置）且既有 5 处 payload
  断言随新字段更新；permission 组件与设置相邻套件
  共 96 例通过；tsc、ESLint、architecture、
  diff-check、diagnostics（0）全绿；无新 Electron
  命令（manifest 仍 266）；Electron 命令合约测试
  （commands/invoke 的 body 全等断言）随新字段同步
  更新，electron 套件 153 例通过。
