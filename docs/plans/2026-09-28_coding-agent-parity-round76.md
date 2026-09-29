# 编码代理对标差距分析·第七十六轮：全局搜索路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r76`，基线 origin/main 2961a9b15 之后的 origin/main）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R75 收口后复扫：并行会话密集交付但全部自行闭环——U1 轮次导航器已
win7 对齐（#1821）并回填 gap-analysis（#1824）；DSH-R32 C2g 自对齐
（#1822）+ dsh-opt 回填（#1823）。零漂移需本循环处理。继续消化候选
清单，本轮选定 **search_routes.py（212 行，全局搜索聚合）**：types
过滤、knowledge_project 多根授权解析（P9/P13）、四源聚合与异常降级、
`{root}::{path}` 去重语义此前零覆盖。win7 模块与六个传递依赖同源存在。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-11 | search_routes 无单测 | types 过滤/多根授权/去重/降级零覆盖 | **P2** |
| —— | U1/DSH-R32 不做 | 并行会话已自行对齐闭环 | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_search_routes.py`（14 例）：

- global_search：缺省全集、types 过滤（未知类型忽略）、
  knowledge_project 多根授权解析（_resolve_knowledge_scope 逐 part
  调用、逗号拼接传参）、limit 透传。
- _search_sessions：字段映射。
- _search_memories：归一化（content 截断 200、memory_type 回退 type、
  缺省 importance/tags）、异常降级空集。
- _search_projects：session_count 映射（stats 缺省 (0, None)）、异常降级。
- _search_knowledge：多根逐根搜索、`{root}::{path}` 去重（同根重复
  提交去重；不同根同类相对路径是不同文件——按实现语义断言）、
  snippet 截断、无最近项目空集、回退 recent[0].path、异常降级。
- Windows 注意：`_Path("/w/a")` 归一化 `\w\a`，路径断言按 Path 语义比较。

## 3. 实施与验证记录

- 14 例全绿（本地 3.12）；ruff 本地预检通过（N814 提交前消化）；
  py38_hazard_scan 0 命中；全量 collect 11700 例（8 个 mcp 收集错误
  为已知本地环境伪影）。

## 4. 批次 B

（剩余候选：project/web_access/wiki/zotero/gateway 等路由，后续轮次
分批。）

## 5. 交付记录

（交付后回填）
