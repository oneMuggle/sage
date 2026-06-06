"""Adapters 层（出/入站适配器实现）。

出站（out）：包装外部资源（LLM HTTP、SQLite、Tool runtime ...），实现 ports/ 中的 Protocol。
入站（in）：把外部输入（HTTP 请求 / 事件）翻译为 application service 调用。

PG2.3 起开始落地。
"""
