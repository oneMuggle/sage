# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Excel 公式本地求值（Office Parity Round2 item R5）.

openpyxl 只能读公式文本 + Excel/LibreOffice 保存时留下的缓存值；对
openpyxl 自行生成（尚无缓存值）的工作簿，公式视图里看不到计算结果。
本模块用第三方 ``formulas`` 库在本地把公式算出来：

    evaluate_workbook(Path("book.xlsx"))  # → {"Sheet1": {"B4": 30}} 或 None

设计约束（全部 fail-safe，调用方 read_xlsx 据此降级回原提示行）：

1. ``formulas`` 懒加载：主渠道依赖（requirements.txt），Win7/py38
   bundle 不装 —— ImportError → ``None``，绝不影响读取主流程。
2. 单元格上限：公式单元格数 > :data:`_MAX_FORMULA_CELLS`（500）时直接
   ``None`` + log —— 求值是 O(重排) 的重操作，拒绝大簿。
3. 墙钟超时：``formulas`` 的 load+calculate 跑在单线程
   :class:`~concurrent.futures.ThreadPoolExecutor` 里，
   ``future.result(timeout=_EVAL_TIMEOUT_SECONDS)`` 超时 → ``None``。
   注意不能 ``with`` 该 executor —— 退出时会 ``shutdown(wait=True)``
   把超时白等回来；这里显式 ``shutdown(wait=False)`` 放飞失控线程。
4. 任何异常吞掉 → ``None`` + warning log，求值错误绝不向上传播。

输出键归一化：``formulas`` 解算结果的键形如
``"'[book.xlsx]SHEET1'!B4"``（book 取路径 basename、sheet 名大写）。
这里解析回 ``(openpyxl sheet 标题, 'B4')``，且只保留公式单元格的取值
（范围键如 ``'...'!B2:B3`` 跳过）。标量提取自 1x1 numpy array，
numpy 标量经 ``.item()`` 转原生类型、整数值 float 转 int，保证
``{"B4": 30}`` 而非 ``{"B4": array([[30.0]])}``。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: 公式单元格数量上限：超过则放弃本地求值（返回 None，读取侧保留原提示）。
_MAX_FORMULA_CELLS = 500

#: 求值墙钟超时（秒）：formulas 的编译 + 计算总预算。
_EVAL_TIMEOUT_SECONDS = 15.0

#: 整数值 float 转 int 的量级上限（超过按 float 原样保留）。
_MAX_INT_FLOAT = 1e15


def _load_formula_cells(file_path: Path) -> Dict[str, Dict[str, str]]:
    """openpyxl ``data_only=False`` → ``{sheet标题: {坐标: 公式文本}}``.

    只收集字符串值且以 ``=`` 开头的单元格（ArrayFormula 对象跳过，
    与读取侧 ``_extract_sheet_formulas`` 的口径一致）。
    """
    from openpyxl import load_workbook

    mapping: Dict[str, Dict[str, str]] = {}
    wb = load_workbook(str(file_path), data_only=False)
    try:
        for ws in wb.worksheets:
            cells: Dict[str, str] = {}
            for row in ws.iter_rows():
                for cell in row:
                    value = cell.value
                    if isinstance(value, str) and value.startswith("="):
                        cells[cell.coordinate] = value
            if cells:
                mapping[ws.title] = cells
    finally:
        wb.close()
    return mapping


def _split_solution_key(
    key: str,
    book_name: str,
    sheets_by_upper: Dict[str, str],
) -> Optional[Tuple[str, str]]:
    """把 ``formulas`` 输出键归一化为 ``(sheet标题, 单元格坐标)``.

    键形如 ``"'[book.xlsx]SHEET1'!B4"``：``!`` 前是 ``'<book>]SHEET'``
    引用部（book 为路径 basename、sheet 名大写），后是单元格地址或
    区域。book 与传入文件 basename 忽略大小写比对、sheet 大写名经
    ``sheets_by_upper`` 映射回 openpyxl 原标题；对不上或缺成分 → None。
    """
    ref_part, sep, addr = key.rpartition("!")
    if not sep or ":" in addr:
        return None
    if not (ref_part.startswith("'") and ref_part.endswith("'")):
        return None
    inner = ref_part[1:-1]
    book, bracket, sheet_upper = inner.partition("]")
    if not bracket or not sheet_upper or not book.startswith("["):
        return None
    book = book[1:]  # partition 保留前导 '['
    if book.lower() != book_name.lower():
        return None
    sheet_title = sheets_by_upper.get(sheet_upper.upper())
    if sheet_title is None:
        return None
    return sheet_title, addr


def _scalar_value(raw: Any) -> Any:
    """``formulas`` 的 1x1 数组包装 → JSON/字符串友好的原生标量。

    ``array([[7.0]])`` → ``7``；字符串/布尔原样；提取失败退回原对象
    （显示层 ``_cell_value_to_str`` 还有一层 str 兜底）。
    """
    value = getattr(raw, "value", raw)
    with contextlib.suppress(Exception):  # 非二维下标形态一律退回原值
        value = value[0, 0]
    to_item = getattr(value, "item", None)
    if callable(to_item):
        with contextlib.suppress(Exception):  # 标量化失败不致命
            value = to_item()
    # formulas 全程按 float 计算：整数值转 int，让展示为 "30" 而非 "30.0"
    if (
        isinstance(value, float)
        and not isinstance(value, bool)
        and value.is_integer()
        and abs(value) < _MAX_INT_FLOAT
    ):
        return int(value)
    return value


def _calculate(file_path: Path) -> Dict[str, Any]:
    """在 worker 线程里跑 formulas 的 load + calculate。

    返回 ``formulas`` 原生解算 dict（键形如 ``"'[book.xlsx]SHEET1'!B4"``，
    值为 1x1 数组包装），由调用方按 openpyxl 侧的公式清单归一化。
    ``import formulas`` 放在线程内：模块加载本身就有可观的启动开销，
    与编译/计算一并计入同一份超时预算。
    """
    import formulas

    model = formulas.ExcelModel().loads(str(file_path)).finish()
    return model.calculate()


def _guarded_calculate(file_path: Path) -> Optional[Dict[str, Any]]:
    """跑求值线程并施加墙钟超时；超时 / 异常 → ``None``（含 warning log）。

    不用 ``with`` 管理 executor —— 退出时会 ``shutdown(wait=True)``，把
    超时白等回来；这里显式 ``shutdown(wait=False)`` 放飞失控线程。
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_calculate, file_path)
        return future.result(timeout=_EVAL_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "excel_eval: 本地求值超时（%ss），跳过 %s",
            _EVAL_TIMEOUT_SECONDS,
            file_path,
        )
        return None
    except Exception:  # noqa: BLE001 — 求值错误绝不向读取主流程传播
        logger.warning("excel_eval: 本地求值失败 %s", file_path, exc_info=True)
        return None
    finally:
        executor.shutdown(wait=False)


def evaluate_workbook(file_path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    """本地求值工作簿里的公式单元格。

    Returns:
        ``{sheet标题: {单元格坐标: 值}}``，只含公式单元格；工作簿没有
        公式时返回空 dict。任何失败（库缺失 / 公式过多 / 超时 / 求值
        异常）返回 ``None`` —— 调用方据此保留原有的「需在 Excel 中打开」
        提示，读取主流程不受影响。
    """
    file_path = Path(file_path)
    try:
        formula_cells = _load_formula_cells(file_path)
    except Exception:  # noqa: BLE001 — 打不开/非法 xlsx：无求值价值
        logger.warning("excel_eval: 公式清单加载失败 %s", file_path, exc_info=True)
        return None

    total_cells = sum(len(cells) for cells in formula_cells.values())
    if total_cells == 0:
        return {}
    if total_cells > _MAX_FORMULA_CELLS:
        logger.warning(
            "excel_eval: 公式单元格 %d 个超过上限 %d，跳过本地求值 %s",
            total_cells,
            _MAX_FORMULA_CELLS,
            file_path,
        )
        return None

    try:
        import formulas  # noqa: F401 — 懒加载探测：缺失是预期内的降级路径
    except ImportError:
        logger.info("excel_eval: formulas 未安装，跳过公式本地求值 %s", file_path)
        return None

    solution = _guarded_calculate(file_path)
    if solution is None:
        return None

    sheets_by_upper = {title.upper(): title for title in formula_cells}
    evaluated: Dict[str, Dict[str, Any]] = {}
    for key, raw in solution.items():
        parsed = _split_solution_key(str(key), file_path.name, sheets_by_upper)
        if parsed is None:
            continue
        sheet_title, addr = parsed
        sheet_cells = formula_cells.get(sheet_title) or {}
        if addr not in sheet_cells:
            continue  # 只回填公式单元格（区域键/常量单元格一律跳过）
        evaluated.setdefault(sheet_title, {})[addr] = _scalar_value(raw)
    return evaluated


__all__ = ["evaluate_workbook"]
