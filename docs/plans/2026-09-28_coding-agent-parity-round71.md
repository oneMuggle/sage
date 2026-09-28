# 编码代理对标差距分析·第七十一轮：prompt 模板库路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r71`，基线 origin/main d1d358dc5）
- **上游文档**：round66 §4 候选清单（延续）、round69/70 §4
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R70 收口后复扫：main 零新增提交；DSH 会话对 R70 期间被误先行合入的
R29（#1782）已按标准管线完成 win7 对齐（#1790 cherry-pick ← #1782），
事后处置闭环、无遗留冲突。继续消化候选清单，本轮选定
**prompt_routes.py（233 行，8 端点）**：模板 CRUD + R42 拖拽排序 +
R30 导出/导入信封（R32 同名冲突 skip/overwrite 双策略）——导入的
冲突/上限/容错计数语义此前零覆盖。win7 模块同源存在（SettingsRepository
KV 模式），双分支适用。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-8 | prompt_routes 8 端点无单测 | 导入冲突策略与 100 条上限零覆盖 | **P2** |
| —— | DSH-R29 win7 对齐 | 并行会话已自行处理（#1790） | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_prompt_routes.py`（18 例，同步直接调用 +
SettingsRepository 打桩为内存 KV，沿用 r166/R66 惯例）：

- list 空库、create（strip 语义 + id 前缀）、100 条上限 400。
- update 命中/404、delete 命中/404。
- reorder：按 ordered_ids 重排、缺失 id 尾部追加、多余 id 忽略。
- export 信封（app/kind/version/templates/exported_at）。
- import：版本守卫 400、新增、同名 skip（conflicts 清单 + 保留现有）、
  overwrite（保 id 不断链）、非 dict 计 failed、空名/空内容 skipped、
  长度超限 failed + errors、总量上限跳过。
- KV 不可达按空库降级；Payload 边界校验（name 1~60 / content 1~8000 /
  description ≤300）。

## 3. 实施与验证记录

- 18 例全绿（本地 3.12）；ruff 本地预检通过；py38_hazard_scan 0 命中；
  全量 collect 11463 例（8 个 mcp 收集错误为已知本地环境伪影）。

### win7 侧适配（对齐批次差异）

- 首验发现 win7 的 prompt_routes 为 R42 之前的版本：无 reorder 端点，
  `list_templates` 按 updated_at 新→旧排序（main 已改存储序 + reorder
  端点，配套前端拖拽 UI 未上 win7）。
- 处置：**不做行为搬运**（仅搬后端会让 win7 用户模板列表乱序而无可视
  排序手段），改为测试适配——reorder 两例替换为 win7 行为基线一例
  （list 按 updated_at DESC），其余 16 例与 main 完全一致。
- 适配后：17 例全绿；ruff 0 命中。

## 4. 批次 B

（剩余候选：artifact/search/project/web_access/wiki/zotero/gateway/todo
等路由，后续轮次分批。）

## 5. 交付记录

（交付后回填）
