"""Round D P8: 结构化读结果的进程内缓存层。

三个 read 端点（word/excel/ppt）此前每次请求都全量重解析文档 ——
前端一次预览刷新会触发 2-3 次相同 read（预览面板 + 文档列表 +
编辑对话框），大文档时每次都是几百毫秒的重复解析。

设计：
- key = (kind, resolved_path, options_key)；options_key 由调用方拼装
  （workspace_path / original_filename 等影响 summary 的参数都要进 key）。
- fingerprint = (mtime_ns, size)：文件一变自动失效 —— 与 pdf_preview /
  template_thumbnail 的失效口径一致，编辑/恢复快照后 mtime 必变。
- 命中返回 ``model_copy(deep=True)``：路由层会就地改写 ``result.summary``
  （_persist_read_summary），浅共享会污染缓存。
- LRU 上限 ``_MAX_ENTRIES``（OrderedDict.move_to_end），线程锁保护
  （FastAPI 默认线程池并发）。
- 失败不缓存：loader 抛异常原样上抛（错误语义完全不变）。

Python 3.8-compatible syntax，可回流 release/win7。
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Tuple, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

__all__ = ["get_or_read", "invalidate", "clear"]

ModelT = TypeVar("ModelT", bound=BaseModel)

#: LRU 条目上限。结构化读结果可能带内嵌图片 data URL（P4），单条可达
#: 数 MB —— 上限保守，命中场景（同一文档的预览/列表/编辑三连读）只需
#: 少量条目。
_MAX_ENTRIES = 8

_lock = threading.Lock()
#: key → (fingerprint, model)
_cache: OrderedDict[Tuple[str, str, str], Tuple[Tuple[int, int], BaseModel]] = OrderedDict()


def get_or_read(
    kind: str,
    file_path: Path,
    options_key: str,
    loader: Callable[[], ModelT],
) -> ModelT:
    """Return the cached read result or run ``loader`` and cache it.

    ``loader`` 抛出的异常原样透传（不缓存失败）。命中与回填都返回
    deep copy —— 调用方可以任意改写返回值。
    """
    path = Path(file_path)
    try:
        stat = path.stat()
        fingerprint = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        # 文件不可 stat —— 让 loader 走原有的 not-found 错误路径。
        return loader()

    key = (kind, str(path), options_key)
    with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0] == fingerprint:
            _cache.move_to_end(key)
            logger.debug("read cache hit: %s", key)
            return entry[1].model_copy(deep=True)  # type: ignore[return-value]

    result = loader()

    with _lock:
        _cache[key] = (fingerprint, result.model_copy(deep=True))
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES:
            evicted_key, _ = _cache.popitem(last=False)
            logger.debug("read cache evict: %s", evicted_key)
    return result


def invalidate(file_path: Path) -> None:
    """Drop every cached entry for ``file_path`` (any kind/options).

    编辑管线在改写文件后可显式调用；不调用也安全 —— mtime 指纹在下次
    读取时自动失效。提供显式失效只是为了同秒内写读的极端时序。
    """
    target = str(Path(file_path))
    with _lock:
        stale = [k for k in _cache if k[1] == target]
        for k in stale:
            del _cache[k]


def clear() -> None:
    """Reset the cache (tests)."""
    with _lock:
        _cache.clear()
