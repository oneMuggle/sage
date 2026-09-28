# R181：ZoteroClient（Zotero SQLite 只读客户端）单测补齐（2026-09-28）

- **上游文档**：parity-loop-sop；Zotero 集成（r63 切片，只读 SQLite）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`zotero/client.py`（817 行，ZoteroClient——只读 SQLite 客户端，支持
health_check / get_stats / search / get_item / get_annotations /
list_collections / get_bibtex / read_pdf_fulltext）此前零测试。

## 覆盖矩阵（约 18 例）

1. `_resolve_db_path`：显式路径 / env / 默认搜索 / 不存在 → 异常；
2. health_check：有表 → ok + item_count；无表 → error；
3. get_stats：items/collections/tags/attachments 四计数；
4. search：全文关键词 LIKE + 过滤；
5. get_item：命中 / 未命中；
6. list_collections：全量与 parent 过滤。

DB 用真实 tmp SQLite 文件建最小 schema，不依赖 Zotero 安装。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
