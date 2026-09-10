"""期刊模板文章生成与格式校验子包。

公共 API 由 backend.office.journal.<errors|models|parser|validator|generator|persistence|pandoc_adapter> 暴露，
通过 backend.api.office_routes.py 的 /office/journal/* 端点对外服务，
经 backend.tools.office_journal_tool.py 暴露给 LLM 工具循环。
"""
from __future__ import annotations
