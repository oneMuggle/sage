# R106 会话级规则查看与撤销（聊天顶栏就地管理）规格

- 日期：2026-10-26
- 基线：`main` `4377693a366d59545f4688fba82658f5103f9f54`
<<<<<<< HEAD
- 状态：实施完成，PR #2530 待合并
=======
- 状态：已合并（PR #2530）
>>>>>>> origin/main
- 编号说明：R106 为 `plugin-evo-index.md` 的插件账轮次号，
  与其它账本的同号计划无关。
- 前置：R105 让审批「记住」可以只记本次会话，但会话规
  则自此不可见、不可撤销——记错一条（尤其整插件
  deny）只能等会话结束或重启后端；这与持久规则 R97
  起的全套管理（查看/逐条删除/清空/归属标注）明显不
  对称。R105 规格明确把「会话规则的查看/撤销 UI」留
  到后续轮次，本轮补齐。落点选聊天顶栏
  PermissionModeSwitch（已有本会话自动放行审计），
  而不是设置页：会话规则的生命周期边界就是当前
  chat 会话，设置页没有「当前会话」概念，跨会话罗列
  无意义且扩大暴露面。

## 1. 目标与语义

- 后端新增按会话的读/撤销端点：
  `GET /api/v1/permissions/session/{session_id}/remembered-rules`
  列出该会话规则（与 R101 同口径附插件归属标注）；
  `POST .../remembered-rules/delete` 按内容逐条删除
  （请求体与 R99 持久删除同形）；`POST
  .../remembered-rules/clear` 无请求体清空该会话全
  部会话规则。删除/清空返回最新列表，前端直接采用。
- 聊天顶栏徽记在「自动批准 0 次但本会话有记住的规
  则」时也出现（文案「本会话已记住 N」）；审计弹层
  顶部新增「本会话已记住的决定」区：逐条 pattern +
  决定 + 归属徽标 + 撤销按钮，区末「清空本会话」
  （confirmDialog 确认）。与自动放行审计同一刷新节
  奏（会话切换 / 流结束 / 30s 轮询）。
- 撤销下一次工具调用起生效：enforcer 每 run 构造时
  现查会话存储（R105 合并点），删掉的规则不再命
  中，回到逐次询问。撤销/清空不影响已执行调用
  （审计流水保留），也不影响任何持久规则。

## 2. 边界

- 创建面不变：会话规则仍只能由审批应答经服务端捕
  获的会话归属生成（R105）。本轮端点只读/只删，客
  户端不能借 session_id 往任何会话写入规则；按客
  户端给出的 session_id 读取/删除与既有
  auto-approvals 查询同形，且删除方向恒为收紧
  （回到询问），不构成放行面。
- pattern 仍只是「删哪一条」的选择子：服务端只删
  存储中已存在且完全一致的一条（不存在或 decision
  非法 → 400 且不写）；不提供新建/编辑 pattern 的
  写面。clear 不接受筛选参数，语义只有「清空该会
  话全部」；两写端点与持久规则写操作共用 Origin
  守卫。
- 设置页规则管理器只管持久规则的口径不变（R105
  §2）：会话规则不进设置页，也不跨会话汇总展示。
- 不做 TTL/手动过期以外的回收机制，不动导出格
  式（PermissionModeSwitch 的 Markdown/JSON 导出
  仍只含权限模式与自动放行审计），远程渠道语义不
  变。Win7 按既有口径待对齐（新后端代码保持 py38
  兼容写法）。

## 3. 实现要点

- `backend/tools/permissions.py`：新增
  `forget_session_rule`（锁内按内容删除第一条等值规
  则，返回是否命中；会话删空后移除其条目）。
- `backend/api/permission_routes.py`：三个新端点，
  复用 `PermissionRuleDeleteBody` 与
  `_annotate_rules_with_plugin_status`；列表数据自
  `[r.to_dict() for r in session_rules_for(sid)]`；
  delete 未命中与持久删除同形 400 `rule not found`。
- Electron：新增 `permissions_list_session_rules` /
  `permissions_delete_session_rule` /
  `permissions_clear_session_rules` 三命令（manifest
  266 → 269）；sessionId 只进路径并 url-encode，
  delete 的 body 只留 `tool_pattern`/`decision`，
  clear 无 body。
- 前端：`permissionApi` 新增
  `listSessionRememberedRules` /
  `deleteSessionRememberedRule` /
  `clearSessionRememberedRules`（复用
  `parseRuleItems`）；PermissionModeSwitch 徽记显隐
  改为「自动批准 > 0 或会话规则 > 0」，审计弹层增
  会话规则区；i18n 新增 `chat.perm.session_rules.*`
  键，决定/归属文案复用
  `settings.permission.rules.*` 既有键。

## 4. 测试计划

- 后端单测：forget 按内容删一条、未命中返回
  False、删空后会话条目消失、跨会话互不影响。
- 后端 API：list 返回形态与标注字段、未知会话空列
  表；delete 命中返回余下列表且持久 settings 不
  变、未命中/非法 decision → 400 不写、Origin 守
  卫拦截跨站；clear 只清本会话且幂等。
- 前端：permissionApi 三方法的 invoke 映射与宽容
  解析；PermissionModeSwitch 在「0 次自动批准但有
  会话规则」时出徽记、弹层列出规则、撤销采用后端
  返回列表、撤销失败保留列表并提示、清空需确认且
  取消时不调后端；electron 三命令合约（路径编
  码 / body 剥离）。
- 通用：相邻回归、Ruff 全库、py38、tsc、ESLint、
  architecture、silent-exceptions、diff-check、
  diagnostics 0、`ipc:manifest:check`（269）。

## 5. 本地证据

- 后端：新增单测 4 例（forget 按内容删除/未命中
  False/删空移除会话条目/撤销后不再命中）+ API 契
  约 9 例（列表形态与 missing 标注/未知会话空列
  表/删除返回余下列表且持久 settings 不动/未命中与
  非法 decision 400/删除与清空各一 Origin 403/清
  空只清本会话且幂等）；与 routes/enforcer/gate、规
  则管理系列及 agent/chat 集成相邻套件共 262 例通
  过；Ruff 全库、py38、silent-exceptions 全绿。
- 前端/Electron：PermissionModeSwitch 新增 4 例
  （0 次自动批准但有会话规则时出徽记并列出/撤销采
  用后端返回列表/撤销失败保留并 toast/清空需确认
  且取消不发请求）、permissionApi 新增 6 例、
  electron 命令合约新文件 3 例；与 permission 组
  件、设置页与 i18n 镜像、electron 相邻套件共 286
  例通过；tsc、ESLint（0 error）、architecture、
  diff-check、diagnostics（0）全绿；新增 3 个
  Electron 命令，manifest 266 → 269。
- architecture 说明：`permission_routes.py` 随本轮
  三个内聚端点增至 855 行跨过 800 上限，按 ratchet
  协议以 checker 口径登记 baseline（仅此一条）；
  permission 全域端点同文件与 R97–R105 一贯，拆分
  留待独立 tighten 轮次。
