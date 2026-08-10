"""检查 hnswlib / jieba / sqlite_vec 三个重依赖可 import。

诊断:这 3 个包在 backend/requirements.txt 中以 ``>=`` 浮动(PR #290 调研结论),
漂移风险高(尤其 hnswlib 跟 numpy ABI 绑定)。用户在 pip 装包后才在首次调用
embedding/分词/向量搜索时报 ImportError,排查链长。

本 check 在启动期做 ``importlib.import_module`` 探针,1 秒内能定位缺包。
"""
from __future__ import annotations

import importlib
import importlib.util

from backend.cli.doctor import CheckResult, Severity, register

#: 探针 import_name → 用户友好的 pip 包名
#: jieba 的 import 名与包名一致;sqlite-vec 包提供 import sqlite_vec
HEAVY_DEPS = (
    ("hnswlib", "hnswlib"),
    ("jieba", "jieba"),
    ("sqlite_vec", "sqlite-vec"),
)


def _try_import(name: str) -> tuple:
    """单包 import 探测。返回 (ok, error_message)。

    使用 importlib.util.find_spec 先做存在性检查(不实际执行模块顶层代码),
    然后再做一次 import_module 验证(覆盖"装了但 import 时崩"的边界情况)。
    """
    spec = importlib.util.find_spec(name)
    if spec is None:
        return False, f"未安装({name})"
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - any import-time error must be reported
        return False, f"import 失败({exc.__class__.__name__}): {exc}"
    return True, "OK"


@register
class HeavyDepsCheck:
    name = "heavy_deps"
    description = "hnswlib / jieba / sqlite_vec 三个重依赖可导入性"

    def run(self) -> CheckResult:
        failed: list = []
        for import_name, pkg_name in HEAVY_DEPS:
            ok, reason = _try_import(import_name)
            if not ok:
                failed.append(f"{pkg_name}: {reason}")

        if failed:
            joined = "; ".join(failed)
            return CheckResult(
                self.name,
                Severity.CRITICAL,
                f"{len(failed)}/{len(HEAVY_DEPS)} 重依赖不可用: {joined}",
                "pip install -r backend/requirements.txt",
            )

        return CheckResult(
            self.name,
            Severity.INFO,
            f"{len(HEAVY_DEPS)} 个重依赖全部可导入",
        )
