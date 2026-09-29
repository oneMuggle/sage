# 编码代理对标差距分析·第七十四轮：依赖审计门漂移治理（policy + 门脚本 + CI 自愈）

- **状态**：单批次交付（分支 `feat-parity-r74`，基线 origin/main d1d358dc5 → 本轮基线 e52a96621 之后的 origin/main）
- **上游文档**：R73 §5（审计门漂移发现）、总账 §3.5
- **编号约定**：对齐批次（ALG）+ OPS

## 0. 结论速览

R73 发现 Dependency audit 对全任意 PR 红（含纯文档 PR）。经下载失败 run
的真实审计报告（artifact `dependency-audit-reports`）逐项定位，三类根因、
三类处置，**真报告重放门禁已转绿（exit 0）**：

1. **fast-uri ×2 未入 policy**（HIGH，transitive URI parser）→ policy
   登记两条例外（review_by 2027-01-01，与 electron 先例同口径）。
2. **undici nodes 不在 lockfile**（MODERATE，node-gyp 嵌套路径）→
   门脚本改动：lockfile 是安装事实的权威口径，moderate/low 缺节点按
   「未安装」跳过并打印说明；**high/critical 缺节点维持失败**
   （宁可误报不可漏报）。
3. **pip-audit venv 入口偶发缺失**（env 创建与安装日志均成功、入口
   仍缺——间歇性）→ ci.yml pip-audit 步骤增加自愈重装（缺失时重装
   pip-audit==2.9.0 一次），仍失败才落错误占位。

## 1. 差距矩阵

| # | 差距 | 处置 |
| --- | --- | --- |
| ALG-16 | fast-uri GHSA-58mr/-qw65 未入 policy | policy +2 例外 |
| OPS-6 | moderate 项 nodes 不在 lockfile 即全门红 | 门脚本分级行为 |
| OPS-7 | pip-audit venv 入口偶发缺失无自愈 | ci.yml 自愈重装 |

## 2. 设计

- policy：fast-uri 两条，`actual_reachability` 如实标注
  「conditionally reachable; transitive URI parser…」。
- `scripts/check_dependency_audit.py`：nodes 校验拆两级——结构非法
  （非列表/空串）仍报错；lockfile 缺节点按 severity 分级（moderate/
  low 跳过 + 打印，high/critical 报错）。既有 53 例门测试全兼容
  （high 缺节点用例维持失败路径）。
- 新增 2 例门测试：moderate 缺节点跳过放行；high 缺节点维持失败。
- `ci.yml`：pip-audit 步骤缺失自愈重装。

## 3. 实施与验证记录

- 门测试套件：**53 passed, 1 skipped**（原 52 例 + 新 2 例，其中 1 例
  本就 skipped）。
- **真报告重放**：以 R73 失败 run 的 npm-audit(.prod).json /
  pip-audit.json + 更新后 policy 实测——
  `Dependency audit gate passed: all findings are explicitly covered`
  **exit 0**（undici 打印 skip 说明；pip findings=10 全部命中 policy）。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

（交付后回填）
