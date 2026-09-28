# 编码代理对标差距分析·第七十三轮：artifact 产物路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r73`，基线 origin/main e52a96621）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R72 收口后复扫：main 零新增提交；DSH-R31（#1800）的 win7 cherry-pick
尚未出现（并行会话自有节奏，届时跳过）。继续消化候选清单，本轮选定
**artifact_routes.py（约 190 行，7 端点）**：产物清单、content 读取按
kind/后缀分派（pdf/image/office/html/text）、reveal、版本历史与恢复
（sha256 + 锁内建版本）、乐观并发更新（ConflictError 409 / ValueError
400 / FileNotFoundError 404）。win7 模块同源存在，双分支适用。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-9 | artifact_routes 7 端点无单测 | 版本历史 + 乐观并发语义零覆盖 | **P2** |
| —— | DSH-R31 不做 | 并行会话自有对齐管线 | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_artifact_routes.py`（21 例，直接调用 +
monkeypatch 模块属性——路由以模块对象引用三个 repo/reader）：

- 清单 to_dict 映射；content 读取 parametrize 分派（pdf/image/docx/后缀
  docx 兜底）+ html 后缀 kind 标记 + 默认 text；reveal 命中/404。
- 版本：清单透传、读取 404、恢复成功（sha256 断言、snapshot_dir、
  restored_from/new_version）、前置 404 两例。
- 更新：成功、404、ConflictError 409、ValueError 400、FileNotFoundError 404。

## 3. 实施与验证记录

- 21 例全绿（本地 3.12）；ruff 本地预检通过（PT006 parametrize 元组、
  F401 提交前消化）；py38_hazard_scan 0 命中；全量 collect 11507 例
  （8 个 mcp 收集错误为已知本地环境伪影）。

## 4. 批次 B

（剩余候选：todo/search/project/web_access/wiki/zotero/gateway 等路由，
后续轮次分批。）

## 5. 交付记录

（交付后回填）
