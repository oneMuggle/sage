# R147：codebase_search 语义检索工具单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；F2（round5 批次 E）工作区语义检索
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/codebase_search_tool.py`（105 行，工作区语义检索：embedding 配置
门、参数校验（未知参数拒绝/ query 最短 2 字符/limit 钳位 [1,20]）、
工作区绑定门、索引与检索两级异常降级、结果聚合 index 统计）此前零
测试。

## 覆盖矩阵（13 例）

1. schema：name=codebase_search、required=[query]、risk=READ；
2. 未知 kwargs → 错误列出非法参数名（sorted）；
3. query 非字符串 / 长度 <2 → 错误；
4. limit 钳位 [1,20]（0→1、100→20）；
5. embedding 未配置 → 引导性错误（含"设置 → 模型"）；
6. 无 workspace_root → 绑定工作区错误；
7. _index_workspace 抛异常 → "索引构建失败"；8. _search_workspace
抛异常 → "检索失败"；9. 成功路径：content 含 query/results/index
（indexed_files_delta/chunks_total + stats 合并）。
四个协作者（load_embedding_config/_index_workspace/_search_workspace/
workspace_index_stats）全部 monkeypatch 在工具模块命名空间。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
