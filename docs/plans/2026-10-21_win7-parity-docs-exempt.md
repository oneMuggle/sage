# parity 口径：docs 差异改为只观测（docs-drift）

- 日期：2026-10-21
- 分支：`chore/win7-parity-docs-exempt-20261021` → `release/win7`
- 影响：`scripts/win7/parity_report.py`、`docs/win7-sync/parity.md`

## 1. 问题

`parity_report.py` 的验收口径「需要动作的文件」= `main-only + real + 未登记的 win7-only`。
这套口径把 `docs/**` 当成代码一样要求对齐，于是出现一个结构性问题：

**main 每写一篇 `docs/plans/*.md`，win7 侧的「需要动作」就 +1。**

2026-10-21 实测：需动作 963 件里，`docs/plans` 一项就占 217 件，
加上 `docs/technical` 29 件与其余 docs，docs 类合计 **295 件落在需动作里**。

后果：M1（≤500）/ M2（≤226 回到历史稳态）这两个验收指标，
**即使在代码零退步的情况下也永远达不成** —— 因为 main 的计划文档是持续增长的，
而 win7 分支按设计不会去追每一篇 main 的帖子。指标变成了「追文档」，不是「追代码」。

另外历史稳态 226 的构成里本来就写着「docs 33」（`parity.md` 第 6 行），
说明 docs 从一开始就是噪音项，只是量小的时候没人管。

## 2. 决策

**docs 不再参与合流验收，只作为观察项单独统计（分级名 `docs-drift`）。**

- 默认 `--docs-mode exempt`：`docs/**` 一律归 `docs-drift`，不计入「需要动作」
- `--docs-mode count`：完整复现旧口径，任何历史数字都能对得上（用于对照与回溯）
- `raw_grade` 字段照旧保留真实分级，JSON 消费方不受影响
- `--write-allow` 在 exempt 模式下不会把 docs 写进 `parity-allow.txt`
  （否则台账会被文档路径污染）

不选「物理同步 217 篇」的理由：那只是把数字挪走一次，main 下次再写计划还会涨，治不了根。

## 3. 改动

`scripts/win7/parity_report.py`（唯一逻辑改动点）：

1. 新增常量 `DOCS_PREFIX = "docs/"`
2. 新增 CLI `--docs-mode {exempt,count}`，默认 `exempt`
3. 分级覆盖放在 allow 覆盖之后、落行之前：`docs/**` → `docs-drift`
4. 看板表格新增 `docs-drift` 行；汇总行注明 docs 已排除，并单列 docs 差异数
5. `--write-allow` 过滤 docs
6. docstring 补充分级说明与用法

`docs/win7-sync/parity.md`：补一节口径变更说明。

## 4. 验证

同一 base/head（`f111bb9b2` / `9cac234a5`）下新旧口径对照：

| 分级 | 旧（count） | 新（exempt） |
|---|---:|---:|
| real | 467 | 401 |
| main-only | 445 | 226 |
| win7-only | 51 | 41 |
| intentional | 129 | 86 |
| typing-only | 103 | 103 |
| frozen | 16 | 16 |
| docs-drift | — | 338 |
| **需要动作** | **963** | **668** |

关键断言（脚本里逐条核过）：

- `docs-drift` 338 件**全部**以 `docs/` 开头 → 没有误伤代码
- **非 docs 文件的 (path, grade, raw_grade) 三元组在两种口径下逐条完全相同** → 改动是手术式的，
  只影响 docs 的归类，不影响任何代码文件的分级结果
- `--docs-mode count` exit=0 且数字与旧版逐项相等 → 可回退、可对照

## 5. 对验收指标的影响

M1/M2 是 2026-10 之前定义的，当时的数字里含 docs。口径变更后需要重新表述：

| 指标 | 旧口径 | 新口径（docs 排除后） |
|---|---|---|
| 起点 | 990 | 963（旧）→ **668（新）** |
| M1 | ≤500 | ≤ 500 − docs 部分 = **≤ 271** |
| M2 | ≤226（历史稳态） | 历史稳态 226 内含 docs 33 → **≤ 193** |

具体数值以本 PR 之后的实测为准；`docs/plans/` 仍在持续增长，所以 M1/M2 只应随代码批次下降，
不应随 main 写文档而上升 —— 这正是本次改动要保证的性质。

## 6. 回滚

`--docs-mode count` 即刻回到旧口径，无需回退代码。
若将来要恢复 docs 参与验收，把默认值改回 `count` 即可。
