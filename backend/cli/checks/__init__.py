"""Sage Doctor — 各 check 子模块的导入入口。

``backend.cli.doctor._import_all_checks()`` 会按需 import 本包内的模块。
新增 check 时,在 ``doctor.py._import_all_checks`` 的元组中追加模块名。
"""
from __future__ import annotations
