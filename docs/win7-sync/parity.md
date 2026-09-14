# Win7/Main Parity 看板 — 2026-09-15

- merge-base: `0643265b02b4c034dabd1cb6118c783f55bd84e5`
- main ahead: **728** / win7 ahead: **499**
- 异动文件: **1937**
- 分类: A=1807 B=121 C=6 D=3 (初版脚本，B/C 待精细化)

| 维度 | 目标 | 当前推算 | 差距 |
|------|------|----------|------|
| 功能对齐 | >=95% | ~62% (B+C 待消化) | 需 B1-B6 六批次 |
| 代码同源 | >=80% | ~54% (A类直通) | P1 平台层后可达 82% |
| 发布同构 | 同构 | 差异 67 文件 (D) | C 层收敛后 <50 行 |
| 约束隔离 | >=90% 集中 | 散弹（现状） | 需 platform/win7 |

> 由 `scripts/win7/classify_diff.py` + `parity_report.py` 生成。待 P1 细化 B/C 分类后刷新。
> 仪表盘：`docs/win7-sync/classify.csv` 明细 + 本文件。

## 下一步
- Phase 1: 细化 B/C 判定（扩大 backend coverage），把 963 backend 文件正确分到 B
- Phase 2 B1: Office R26-30 cherry-pick
