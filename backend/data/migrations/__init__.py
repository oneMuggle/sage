"""schema 版本化迁移框架（DSH 对标 R9，C3）。

迁移在 ``init_db`` 时由 ``database.py`` 调用
``run_pending_migrations`` 按序应用。
"""
