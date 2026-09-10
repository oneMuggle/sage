"""写后语法诊断（对标增强 Phase-2 G8，docs/plans §2.1）。

Qoder 式"写完即反馈"：``write_file`` / ``edit_file`` / ``apply_patch``
落盘成功后，对 Python 文件跑一次 stdlib ``ast.parse`` 语法检查；失败时
在工具结果的 ``diagnostics`` 字段给出（行号, 提示），LLM 立即看到并
修正，不用等到运行期炸。

刻意只用标准库：ruff/pyflakes 不是生产依赖，引入会拖环境且 Win7 LTS
通道（py3.8）要同步装。语法层是最高频的"写坏"，语义层（未定义名、
导入错误）交给 repl / bash 执行反馈 —— 分层不重复。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 参与诊断的扩展名（其余语言无零依赖检查器，跳过）
_DIAGNOSABLE_SUFFIXES = frozenset({".py", ".pyw", ".json"})


def _syntax_check(path: Path) -> Optional[Dict[str, Any]]:
    """对 Python/JSON 文件做语法检查；返回诊断 dict 或 None（无问题/不适用）。

    F-2 (round5 批次 F): ``.json`` 走 stdlib ``json.loads``——配置/manifest
    类文件写坏 JSON 是高频错误，LLM 立即看到行号即可修正。非白名单后缀
    直接跳过 —— 调用方（attach_diagnostics 与 apply_patch 逐文件收集）都
    依赖这一语义，无需各自再判。
    """
    if path.suffix.lower() not in _DIAGNOSABLE_SUFFIXES:
        return None
    if path.suffix.lower() == ".json":
        return _json_check(path)
    try:
        source = path.read_bytes()
    except OSError as exc:
        logger.warning("post-write diagnostics: 读取 %s 失败: %s", path, exc)
        return None
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return None  # 非文本/其他编码 —— 不诊断
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return {
            "severity": "error",
            "message": f"语法错误: {exc.msg}",
            "line": exc.lineno,
            "offset": exc.offset,
        }
    return None


def _json_check(path: Path) -> Optional[Dict[str, Any]]:
    """JSON 语法检查（stdlib json, 零依赖）。"""
    import json

    try:
        source = path.read_bytes()
    except OSError as exc:
        logger.warning("post-write diagnostics: 读取 %s 失败: %s", path, exc)
        return None
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "severity": "error",
            "message": f"JSON 语法错误: {exc.msg}",
            "line": exc.lineno,
            "offset": exc.colno,
        }
    return None


def attach_diagnostics(
    content: Optional[Dict[str, Any]], file_path: str
) -> Optional[Dict[str, Any]]:
    """把写后诊断附加到成功的工具结果 content；返回原 dict（可能带新字段）。

    失败静默 —— 诊断是锦上添花，绝不能让写文件本身报错。
    """
    if content is None:
        return content
    try:
        path = Path(file_path)
        if path.suffix.lower() not in _DIAGNOSABLE_SUFFIXES:
            return content
        issue = _syntax_check(path)
        if issue is not None:
            diagnostics = [issue]
            content["diagnostics"] = diagnostics
            content["diagnostics_note"] = (
                f"文件已写入，但检测到 {len(diagnostics)} 个语法问题 —— "
                "请修正后重新写入"
            )
    except Exception:  # noqa: BLE001 — 诊断失败绝不影响写入结果
        logger.warning("post-write diagnostics 失败: %s", file_path, exc_info=True)
    return content


__all__ = ["attach_diagnostics"]
