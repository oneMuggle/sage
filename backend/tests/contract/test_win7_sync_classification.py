"""
test_win7_sync_classification.py — win7-sync 工具链的契约测试。

覆盖:
  - classify_diff.classify: 4 个 win7 平台 Electron 文件必须归为 C 类,
    避免 #2946 回归(整文件取 main 静默回退救援工具能力)。
  - symbols.capability_symbols: 提取源码能力标识符, 排除注释/普通小写词。
  - symbols.capability_loss: base − head 集合差。

这些是 win7-sync 机器人 + CI 门禁的基础, 任何行为变更必须显式更新测试。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "win7"))

from classify_diff import classify  # noqa: E402
from symbols import (  # noqa: E402
    WIN7_PLATFORM_FILES,
    capability_loss,
    capability_symbols,
)


def test_win7_platform_files_all_class_c() -> None:
    """#2946 回归: 这 4 个文件曾被误分为 A 类直通, 整文件取 main 丢能力。"""
    for path in WIN7_PLATFORM_FILES:
        assert classify(path) == "C", f"classify({path!r}) should be C, got {classify(path)!r}"


def test_classify_d_freeze_still_fires() -> None:
    """D 类(发布/打包冻结件)优先级高于 C, 即使路径也匹配 C 模式。"""
    assert classify("package.json") == "D"
    assert classify("electron-builder.yml") == "D"
    assert classify("backend/requirements.txt") == "D"


def test_classify_a_generic_electron_file() -> None:
    """非平台 Electron 文件走默认 A 类。"""
    assert classify("electron/main.ts") == "A"
    assert classify("electron/commandRoutes/memory.ts") == "A"


def test_capability_symbols_filters_comments_and_small_words() -> None:
    """注释行 / 普通小写词 / 中文文案不算能力标识符。"""
    text = """
// This is a comment line with checkTrustedInstallerService
/* Another block with checkWuauservService */
const state = 1;
const idx = 0;
const some = 'hello';
const checkWuauservService = () => {};
const doc_path = '/foo/bar';
const label = '用户配置';
"""
    syms = capability_symbols(text)
    # 注释里的不应计入
    assert "block" not in syms
    # 普通小写词不应计入
    assert "state" not in syms
    assert "idx" not in syms
    assert "some" not in syms
    # 中文文案不应计入
    assert "用户配置" not in syms
    # 真正的能力标识符必须计入
    assert "checkWuauservService" in syms
    assert "doc_path" in syms


def test_capability_loss_diff() -> None:
    """base 有、head 没有的标识符被检出; head 新增的不算丢失。"""
    base = "def checkTrustedInstallerService() { /* ... */ };"
    head = "def checkWuauservService() { /* ... */ }; const hasDownloads = true;"
    lost = capability_loss(base, head)
    assert "checkTrustedInstallerService" in lost
    assert "checkWuauservService" not in lost  # head 新增
    assert "hasDownloads" not in lost  # head 新增


def test_capability_loss_empty_when_superset() -> None:
    """head 是 base 的超集时, 丢失集合为空。"""
    base = "const doc_path = ''; const fix_script_path = '';"
    head = base + "; const win7FixDir = 'resources/win7-fix';"
    assert capability_loss(base, head) == set()


def test_capability_loss_full_when_file_emptied() -> None:
    """head 为空(文件被清空)时, base 的全部能力标识符都算丢失。"""
    base = "const checkTrustedInstallerService = () => {};"
    lost = capability_loss(base, "")
    assert "checkTrustedInstallerService" in lost
