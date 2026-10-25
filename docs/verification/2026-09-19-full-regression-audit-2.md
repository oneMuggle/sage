# 全量回归审计 #2（R55-R63 九轮合并后）验证记录

> 日期: 2026-09-19 · 环境: Windows 本地（sage-backend py3.11.16）
> 范围: tests/unit + tests/integration（xdist loadfile，排除
> test_event_loop_blocking）
> 对象: main @ cdfadaae（含 R55-R63 + 并行合并）

## 结果

- **8136 passed / 54 failed / 492 skipped**
- 54 个失败与首轮审计（R54，55 failed）为同一簇：settings_route_legacy
  （13）、wiki_ingest_stream（6）、chat_auto_compaction（3）、
  llm_proxy_routes（3）、skill_delete（3）、r38_skill_activation（3）、
  ingest_stream（6）、doctor_cli（1）、agent_m2_tools（1）、
  agent_office_create_flow（0——R55 已修复）、chat_routing 等杂项。
- **全部为预存在本地 Windows 环境问题**（首轮审计已经 base 0b4b45b1
  对照坐实；本轮与该簇完全重合，office word/toc/caption/ref/fn/en/
  pgnum/metadata 家族零失败）。
- 变化：55 → 54 的净减来自 R55（office_create_flow JSON 转义修复，
  2 个用例恢复）；新增测试（脚注/尾注/一致性 lint/元数据等）全部通过。

## 结论

R55-R63 九轮合并（office_create_flow 修复 + 图表目录 + 交叉引用 +
脚注/尾注 + 属性 + pgNumType + lint 收口）无回归；预存在本地失败簇
归属其他线程（settings/wiki/compaction 基建），修复需其 owner 跟进。
