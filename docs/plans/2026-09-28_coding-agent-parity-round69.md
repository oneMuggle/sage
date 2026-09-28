# 编码代理对标差距分析·第六十九轮：小型路由组测试补齐（metrics/media/theme）

- **状态**：单批次交付（分支 `feat-parity-r69`，基线 origin/main 2e040f501）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R68 收口后 main 仅新增 DSH-R28（#1774，归并行会话对齐管线，跳过）。
继续消化 round66 §4 候选清单中的小型路由组：**metrics（1.4KB 单端点）/
media（1.5KB 单端点）/ theme（1.8KB 四端点）**——三者在 win7 均存在
（模块与传递依赖一起验证），双分支同源适用。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-4 | metrics_routes 无单测（Prometheus/空 body 两路径） | 1.4KB 33 行 | **P2** |
| T-5 | media_routes 无单测（非法 id/store 未命中/盘缺失/命中） | 1.5KB 47 行 | **P2** |
| T-6 | theme_router 无单测（save/list/delete/get + 载荷校验） | 1.8KB 70 行 | **P2** |

## 2. 设计

三个新测试文件（直接调用路由函数 + monkeypatch，沿用 r166/R66 惯例；
Query 默认参数显式传纯值——R66 沉淀）：

- `test_metrics_routes.py`（2 例）：PrometheusMetricAdapter 子类识别 →
  text-format 透出；非 Prometheus 适配器 → 空 body。content_type 为
  只读 property，测试子类以 property 覆写。
- `test_media_routes.py`（4 例）：非法 media_id（格式/长度）404、
  store 未命中 404、盘上文件缺失 404（竞态防护）、命中返回
  FileResponse（Cache-Control + media_type）。
- `test_theme_router.py`（12 例）：save/list/delete/get 透传、get 未命中
  404、ThemeCssPayload 校验（name 1~32、appearance 枚举、css 1~8192）。
  注意 theme 路由为同步函数，直接同步调用。

## 3. 实施与验证记录

- 18 例全绿（本地 3.12）；py38_hazard_scan 0 命中；全量 collect
  11398 例（本地 8 个 mcp 收集错误为已知环境伪影，与本批次无关）。

## 4. 批次 B

（剩余候选：artifact/system/prompt/search/project/web_access/wiki/
zotero/gateway/todo 等路由，后续轮次分批。）

## 5. 交付记录

（交付后回填）
