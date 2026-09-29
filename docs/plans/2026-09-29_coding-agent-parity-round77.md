# 编码代理对标差距分析·第七十七轮：web-access 路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r77`，基线 origin/main b0906cd5b）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R76 收口后复扫：main 零新增提交；win7 侧并行会话合入 restore_runs 修复
（#1830 ← #1826，其自有范畴）。继续消化候选清单，本轮选定
**web_access_routes.py（217 行，8 端点，Round 12/14/15）**：凭据清单
（脱敏）/删除、config 读写（合并 + 500 透出）、header/cookie 凭据新增
（域名归一 + 422 校验）、出网指标快照（R28 TLS 指纹合并）与重置——
Origin 守卫与载荷 extra=forbid 语义此前无直接单测。win7 模块同源存在。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-12 | web_access_routes 8 端点无单测 | 守卫短路/config 合并/422/指标合并零覆盖 | **P2** |
| —— | win7 restore_runs 修复 | 并行会话已自行对齐（#1830） | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_web_access_routes.py`（16 例，异步直接调用，
origin 守卫统一打桩放行 + 拦截路径一例；SettingsRepository / credential_vault /
web_metrics / tls_transport 全 monkeypatch；Query/Body 默认参数显式传纯值）：

- 凭据：清单透传；删除命中/404（JSONResponse 信封）。
- config：缺省补 False、读取既有值（多余键不透出）、PUT 合并语义、
  写失败 500 透出、extra=forbid。
- header/cookie 凭据：域名 strip+lower 归一、ValueError → 422
  （header 透出原文、cookie 固定 error 码）、extra=forbid。
- 指标：snapshot + tls stats 合并、重置透传。
- Origin 守卫：命中时直接返回守卫响应（短路验证）。

## 3. 实施与验证记录

- 16 例全绿（本地 3.12）；ruff 本地预检通过；py38_hazard_scan
  0 命中；全量 collect 11746 例（8 个 mcp 收集错误为已知本地环境伪影）。

## 4. 批次 B

（剩余候选：project/wiki/zotero/gateway/search 完成等路由，后续轮次
分批。）

## 5. 交付记录

（交付后回填）
