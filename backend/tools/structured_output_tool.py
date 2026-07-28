"""
结构化输出工具 - agent 最终机器可读载荷（移植 claw-code execute_structured_output）

让 agent 在多轮对话收尾时产出 JSON 结构化结果，供前端/API 直接消费。

- 载荷存入会话级内存存储（与 todo_state 同构的 ``SessionStateStore``，
  按 session_id 隔离），前端/API 可通过 ``get_last_structured_output()``
  提取；``ToolExecutionContext`` 是 frozen 的，无法就地挂载载荷。
- 可选 ``schema`` 校验：优先用 ``jsonschema``（如已安装）；sage 的
  requirements.txt 未声明该依赖（Win7 LTS 分支可能缺失），故内置一个
  仅支持 ``{type, properties, required, items}`` 的最小校验器兜底。
- READ 能力：只写 agent 内部状态，不触碰用户数据/文件系统。
"""

import logging
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolResult, ToolSchema
from .todo_state import SessionStateStore, resolve_session_id

logger = logging.getLogger(__name__)

try:  # requirements.txt 未声明 jsonschema；缺失时走最小校验器
    import jsonschema

    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover — 取决于运行环境
    jsonschema = None
    _HAS_JSONSCHEMA = False

#: 最小校验器支持的 JSON Schema type 名 → 谓词。
#: 注意 bool 是 int 的子类：integer/number 判定需显式排除 bool。
_TYPE_PREDICATES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),  # noqa: UP038 — py3.8 不支持 X | Y isinstance
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _type_matches(value: Any, expected: str) -> bool:
    """检查值是否匹配 JSON Schema type 名；未知 type 名放行（宽容）。"""
    predicate = _TYPE_PREDICATES.get(expected)
    return predicate(value) if predicate is not None else True


def minimal_schema_errors(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """最小 JSON Schema 校验器：仅支持 type / properties / required / items。

    返回错误消息列表（空列表 = 通过）。不支持的关键字一律忽略——这是
    jsonschema 不可用时的兜底，宁可漏报也不误报。
    """
    errors: List[str] = []

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(instance, expected_type):
        errors.append(f"{path}: 期望类型 {expected_type}，实际 {type(instance).__name__}")
        return errors  # 类型不符 → 不再下钻，避免级联噪音

    if isinstance(instance, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in instance and isinstance(subschema, dict):
                    errors.extend(minimal_schema_errors(instance[key], subschema, f"{path}.{key}"))
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in instance:
                    errors.append(f"{path}: 缺少必填字段 {key!r}")

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, element in enumerate(instance):
                errors.extend(minimal_schema_errors(element, items, f"{path}[{index}]"))

    return errors


def validate_against_schema(data: Any, schema: Dict[str, Any]) -> List[str]:
    """用 jsonschema（若可用）或最小校验器校验，返回错误消息列表。"""
    if _HAS_JSONSCHEMA:
        validator_cls = jsonschema.validators.validator_for(schema)
        try:
            validator_cls.check_schema(schema)
        except jsonschema.exceptions.SchemaError as exc:
            return [f"schema 本身非法: {exc.message}"]
        validator = validator_cls(schema)
        return [
            f"$.{'.'.join(str(p) for p in error.absolute_path)}: {error.message}"
            for error in validator.iter_errors(data)
        ]
    return minimal_schema_errors(data, schema)


#: 会话级「最后一次结构化输出」存储（单例）
_structured_output_store = SessionStateStore()


def get_last_structured_output(session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取某会话最后一次 structured_output 载荷。

    ``session_id=None`` → 取当前 ContextVar 上下文（无上下文 → 匿名桶）。
    供前端/API 层在对话结束后提取机器可读结果。
    """
    key = session_id if session_id is not None else resolve_session_id()
    return _structured_output_store.get(key)


class StructuredOutputTool(BaseTool):
    """结构化输出工具 - 产出并暂存最终 JSON 载荷"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="structured_output",
            description=(
                "产出最终结构化 JSON 载荷（任务收尾时用）。"
                "载荷存入当前会话，前端/API 可提取；可选提供 JSON Schema 做校验。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "data": {"type": "object", "description": "结构化 JSON 载荷"},
                    "schema": {
                        "type": "object",
                        "description": "可选 JSON Schema，用于校验 data",
                    },
                },
                "required": ["data"],
            },
        )

    def execute(self, data: Any = None, schema: Any = None, **kwargs) -> ToolResult:
        """
        校验并存储结构化输出

        Args:
            data:   JSON 对象载荷（必填）
            schema: 可选 JSON Schema

        Returns:
            ToolResult；content 回显存储的 data + session_id。
            校验失败 → success=False + 错误明细。
        """
        if not isinstance(data, dict):
            return ToolResult(success=False, error="data 必须是 JSON 对象")
        if schema is not None and not isinstance(schema, dict):
            return ToolResult(success=False, error="schema 必须是 JSON 对象")

        try:
            if schema is not None:
                errors = validate_against_schema(data, schema)
                if errors:
                    return ToolResult(
                        success=False,
                        error="schema 校验失败: " + "；".join(errors[:10]),
                    )

            session_id = resolve_session_id()
            _structured_output_store.replace(session_id, data)

            return ToolResult(
                success=True,
                content={
                    "stored": True,
                    "session_id": session_id,
                    "data": data,
                },
            )
        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("structured_output 执行失败: %s", e)
            return ToolResult(success=False, error=f"结构化输出失败: {e}")
