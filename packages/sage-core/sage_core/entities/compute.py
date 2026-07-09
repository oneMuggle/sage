"""外部计算能力领域模型（纯，零外部依赖）。

承载 sage 调用外部计算项目（如 ghm 激波管/风洞计算器）所需的元数据、
请求、结果与错误模型。本模块仅使用 stdlib（dataclass / enum / typing），
**禁止引入 pydantic / httpx / subprocess** 等外部依赖。

模型清单：

- ``ComputeSpec``       ：单个可调用计算操作的元数据（喂给 LLM 做 tool schema）
- ``ComputeRequest``    ：计算调用入参
- ``ComputeErrorType``  ：错误分类枚举
- ``ComputeError``      ：失败时的结构化错误信息
- ``ComputeResult``     ：计算结果（成功/失败统一返回）

参见 ``backend.ports.compute.ComputePort``。
"""

from __future__ import annotations
from typing import Dict, Optional

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class ComputeSpec:
    """一个可调用的计算项的元数据。

    Attributes:
        name:           操作唯一名（最终翻译为 LLM tool 名）
        description:    自然语言描述，喂给 LLM 用于选择
        params_schema:  JSON Schema 格式的参数定义
    """

    name: str
    description: str
    params_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComputeRequest:
    """计算调用入参。

    Attributes:
        operation:   ``ComputeSpec.name`` 引用
        params:      已校验/已解析为 dict 的参数
        timeout_ms:  单次调用超时，None 表示使用 adapter 默认值
        request_id:  关联到 chat request_id，便于审计/追踪
    """

    operation: str
    params: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: Optional[int] = None
    request_id: Optional[str] = None


class ComputeErrorType(str, Enum):
    """计算失败的分类。"""

    OPERATION_NOT_FOUND = "operation_not_found"
    INVALID_PARAMS = "invalid_params"
    TIMEOUT = "timeout"
    PROCESS_FAILED = "process_failed"  # 非零退出码 / HTTP 5xx
    OUTPUT_PARSE_ERROR = "output_parse_error"
    INTERNAL_ERROR = "internal_error"  # 配置错误 / 可执行文件找不到等


@dataclass
class ComputeError:
    """结构化错误信息（``ComputeResult.success=False`` 时填充）。

    Attributes:
        type:     错误分类
        message:  人类可读的错误说明
        details:  附加上下文（如 ``tried`` 列表、stderr 截断等）
    """

    type: ComputeErrorType
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComputeResult:
    """计算调用结果（成功/失败统一返回，**不抛异常**）。

    Attributes:
        success:      是否成功
        output:       成功时解析后的结果 dict（adapter 自行约定 schema）
        raw_stdout:   原始 stdout 文本（subprocess adapter 用，便于调试）
        raw_stderr:   原始 stderr 文本
        exit_code:    子进程退出码（subprocess adapter 用）
        duration_ms:  端到端耗时
        error:        失败时的 ``ComputeError``
    """

    success: bool
    output: Optional[Dict[str, Any]] = None
    raw_stdout: Optional[str] = None
    raw_stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[ComputeError] = None
