# wiki 图谱洞察（insights）行为测试补全（Round 17）

日期：2026-09-17 ｜ 分支：`feat/wiki-insights-tests` ｜ 基线：#923（9b0c9fc5）

## 背景

`backend/wiki/insights.py`（279 行）是「图谱洞察」功能的核心——跨社区惊人联系、
类型不匹配、边缘-中心连接三类发现 + 孤立节点 / 稀疏社区 / 桥节点三类知识缺口，
经 `/api/v1/wiki/insights` 直接面向用户。该模块 0 测试引用，启发式回归无防护。

本批为纯测试批次（含启发式审查）：审查未发现行为缺陷，全部为行为锁定测试。

## 测试设计（`backend/tests/unit/test_wiki_insights.py`）

### 单元层（直接构造 GraphData / CommunityInfo，无磁盘）

- `TestFindSurprisingConnections`
  - 跨社区边 → strength 0.8 + 「跨社区连接」reason；同社区边不命中该类
  - page_type 不匹配 → 0.6；相同类型不命中
  - 边缘-中心（度数 1 ↔ ≥5）→ 0.7 + 度数文案；中间度数组合不命中
  - 一条边可同时命中多类；结果按 strength 降序
  - 端点缺失的边跳过不崩溃
- `TestFindKnowledgeGaps`
  - 度数 0 节点 → isolated_node / medium
  - size≥3 且 cohesion<0.3 → sparse_community / low；cohesion≥0.3 或 size<3 不命中
  - 连接 ≥2 个外部社区的桥节点 → bridge_node / high
  - 全局排序 high → medium → low

### 端到端层（tmp 项目真实 markdown → build_graph → detect_communities → analyze_graph）

- 两个互链簇 + 跨簇链接 + 孤立页：
  - stats 节点 / 边计数正确；孤立页落入 isolated_node
  - surprising_connections 非空；节点 label 取自 frontmatter title
- 不断言具体社区划分（Louvain 在微型图上不稳定），只断言结构不变量

## 附带修复：wiki 路由签名 py38 兼容

`import backend.wiki.community` 触发 `wiki/__init__ → mcp_server → api/wiki_routes`
导入链，FastAPI 在装饰期求值路由签名、pydantic 在类创建期求值字段注解——
`str | None` 在 win7/py3.8 下导入即崩（main 上已烂，会随 win7 同步炸过去）。修复：

- `queue_tasks` / `get_graph` 路由签名 `str | None` → `Optional[str]`
- `ProjectCheckResponse` 字段注解同改

**范围外（另立审计批次）**：conftest → backend.main → orch/legacy_routes 导入链
的 py38 烂点（main.py L45、orch_routes 3 处、legacy_session_routes 3 处、
legacy_routes 74 处 `| None`——其中仅 FastAPI 签名 / pydantic 字段为真破点，
本地变量注解因 future import 无害）。

## 纪律

py3.8 兼容；networkx 仅经现有 community.detect_communities 间接使用。
