# 编码代理对标差距分析·第六十四轮：win7 对齐小批次（r166 hooks 测试 + round63 文档回填同步）

- **状态**：单批次交付（分支 `feat-parity-r64`，基线 origin/release/win7 ce8213b95）
- **上游文档**：#1743（r166）、#1745（R63 回填）、R63（round63）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R63 收口后复扫：main 新增 4 个并行交付（#1741/#1742/#1743/#1744）。
逐项核对 win7 适用性：#1744 归 DSH 会话自有对齐管线（不抢）；#1741
不适用（其修复的 dict() 工厂仅存在于 main，win7 的 test_conventions.py
为旧版 194 行差）；**#1743 适用**——hooks_routes.py 已在 win7 而对应
测试文件缺失；另 round63 文档 §4/§5 的回填版（#1745）应同步 win7。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-7 | win7 有 `backend/api/hooks_routes.py` 但无 `test_hooks_routes.py` | cat-file 实证 | **P2** |
| ALG-8 | win7 的 round63 文档 §4/§5 仍是交付前占位 | #1745 仅改了 main 侧 | **P3** |
| —— | #1741 不适用 | dict() 工厂未上 win7，无 C408 红 | 跳过 |
| —— | #1744 不做 | DSH 系列由并行会话维护（见 #1737 惯例） | 跳过 |

## 2. 设计

- ALG-7：cherry-pick `7c40d0b29`（r166，+271 行新测试文件 + 方案文档）。
- ALG-8：cherry-pick `2ed9dc7e2`（#1745）中 round63 文档部分；
  总账 `parity-rounds-index.md` 为 main-only，冲突时继续排除。
- 验证：py38_hazard_scan 0 命中 + 新增测试本地（3.12）通过；
  py3.8 权威验证交由 Win7 LTS CI。

## 3. 实施与验证记录

- cherry-pick `7c40d0b29`：干净落地（新文件）。
- cherry-pick `2ed9dc7e2`：round63 文档 hunk 干净；总账按预期 modify/delete
  冲突，win7 侧排除。
- 首跑 CI 红：**Architecture check 行数基线棘轮**——BU23/BU24 pick 使
  chat_dispatcher 2239→2258（+19）、test_chat_dispatcher_budget 910→969
  （+59）。按棘轮协议（只升不降）补账 `architecture-baseline.json`，
  数值与 main #1730 一致。
- 二跑 CI 红：**py38 收集错误（import file mismatch）**——`tests/unit/api/`
  与既有 `tests/api/` 存在同名 `test_hooks_routes.py`（pytest prepend
  模式按 basename 定模块名）。根因：main 有 `tests/unit/api/__init__.py`
  使模块名带包前缀，win7 缺失。补齐该空 `__init__.py`（对齐 main）；
  顺带评估了 mcp/services/tools 等 5 个同类缺失 init——**不加**：其模块名
  （`mcp.*`/`services.*`/`tools.*`）会遮蔽 backend 真实顶层包，本地
  collect-only 实证 4 错。全量收集 10262 例 0 错误。
- 本地：扫描 0 命中；hooks 测试 + 扫描器测试全绿（本地 3.12）。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

- **批次（win7，本轮唯一交付面）**：#1748 `870d4ebf`
  - 内容：#1743（r166 hooks 测试，+271 行）+ round63 文档回填同步
  - 两轮修复（详见 §3）：行数基线棘轮补账（2239→2258 / 910→969，
    同 main #1730 数值）；补 `tests/unit/api/__init__.py` 修同名模块
    收集冲突（对齐 main 布局）
  - 波折：CI 红 2 次，均定位修复后终跑全绿（11 checks 0 failure，
    含 Win7 LTS py38 job）
- **总账回填**：即本提交。
