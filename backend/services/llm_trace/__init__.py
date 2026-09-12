"""LLM 调用诊断包导出模块.

提供:
- LlmTraceRecorder: 进程级 ring buffer,记录最近 N 次 LLM 调用的完整元数据
- TraceRecord: 不可变 dataclass,单次调用的完整快照
"""
from __future__ import annotations

from backend.services.llm_trace.recorder import LlmTraceRecorder, TraceRecord

__all__ = ["LlmTraceRecorder", "TraceRecord"]
