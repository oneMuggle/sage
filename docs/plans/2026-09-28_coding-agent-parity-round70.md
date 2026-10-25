# 编码代理对标差距分析·第七十轮：system 系统维护路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r70`，基线 origin/main 885e04a0b）
- **上游文档**：round66 §4 候选清单（延续）、round69 §4
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R69 收口后复扫：win7 已被并行 DSH 会话自行对齐 DSH-R28（`51f9471f1` =
#1777），main 无新增提交——零外部漂移。继续消化候选清单，本轮选定
**system_routes.py（5.5KB，5 端点）**：备份三件套（list/create/restore）
与记忆导入/导出（R19 信封格式）——其中导入的去重/容错计数语义与
导出失败降级是关键行为，此前完全无测试。win7 模块同源存在，双分支适用。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-7 | system_routes 5 端点无单测 | 备份恢复 + 记忆导入导出逻辑零覆盖 | **P2** |
| —— | DSH-R28 win7 对齐 | 并行会话已自行处理（#1777） | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_system_routes.py`（12 例，直接调用 + monkeypatch）：

- 备份：list 透传；create 成功与失败信封（`ok: False`）；restore 成功
  透传与缺失 400（JSONResponse 信封含备份名）。
- 记忆导入：版本守卫 400；新增/去重跳过（exists_by_content）/空内容
  跳过/非 dict 条目 failed 的四类计数；单条 save 异常不中断且 errors
  封顶 10 条；MemoryManager 初始化失败 → 500 信封。
- 记忆导出：信封结构（app/version/exported_at/episodic/semantic）；
  失败降级为空集不 500。

## 3. 实施与验证记录

- 12 例全绿（本地 3.12）；ruff 本地预检通过（R66 PT018 / R69 I001
  教训前置消化）；py38_hazard_scan 0 命中。

## 4. 批次 B

（剩余候选：artifact/prompt/search/project/web_access/wiki/zotero/
gateway/todo 等路由，后续轮次分批。）

## 5. 交付记录

- **批次 A（main）**：#1783 `4aca4c05`
  - 内容：test_system_routes.py（12 例）+ 本文档。CI 一次全绿
    （16 checks 0 failure）。
- **批次 B（win7 对齐）**：#1787 `31cc8e27`
  - 测试文件 + 文档同步至 win7；CI 一次全绿（Win7 LTS py38 job 过）。
- **事故记录（诚实留档）**：本轮 main 侧 PR 创建时与 DSH 并行会话的
  PR 发生编号竞态——DSH 的 R29 C2d 重构 PR 抢得 #1782，本侧实际为
  #1783。merge 阶段按误读的编号执行了 `PUT /pulls/1782/merge`，将
  DSH 会话的 R29 重构（内容为其系列标准生命周期装配迁出，分支保护
  门禁通过）先行合入 main。R29 本就在 DSH 会话的交付计划内且 CI
  门禁通过，未造成功能损害，但流程上属于误操作。**沉淀：merge 前
  必须校验 PR 的 title/head 与预期一致，不能只信编号。**（已同步
  总账 §2.6。）
- **总账回填**：即本提交。
