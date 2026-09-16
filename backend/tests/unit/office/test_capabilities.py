"""Unit tests for backend.office.capabilities (Round A P6 环境能力探测).

探测函数本身只做 find_spec / 路径检查，测试通过 monkeypatch 钉住
``_locate_soffice`` / ``find_spec`` / ``sys.platform``，不依赖宿主机
实际安装状态。缓存语义（30s TTL + force 旁路）单独断言。
"""

from __future__ import annotations

import pytest

from backend.office import capabilities


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前后清空模块级缓存，避免测试间串扰。"""
    capabilities._cache = None
    yield
    capabilities._cache = None


def _pin(monkeypatch, *, soffice=None, platform="linux", specs=()):
    """钉住探测的全部外部输入。``specs`` 是 find_spec 应命中的模块名集合。"""
    monkeypatch.setattr(capabilities, "_locate_soffice", lambda: soffice)
    monkeypatch.setattr(capabilities.sys, "platform", platform)
    monkeypatch.setattr(
        capabilities, "find_spec", lambda name: object() if name in specs else None
    )


def test_probe_all_missing(monkeypatch):
    _pin(monkeypatch)
    caps = capabilities.probe_capabilities(force=True)
    assert caps.soffice_available is False
    assert caps.word_com_available is False
    assert caps.pdf_export_available is False
    assert caps.pillow_available is False
    assert caps.formulas_available is False


def test_probe_soffice_found(monkeypatch):
    _pin(monkeypatch, soffice="/usr/bin/soffice", specs={"PIL", "formulas"})
    caps = capabilities.probe_capabilities(force=True)
    assert caps.soffice_available is True
    assert caps.soffice_path == "/usr/bin/soffice"
    assert caps.pdf_export_available is True
    assert caps.pillow_available is True
    assert caps.formulas_available is True


def test_word_com_only_counts_on_windows(monkeypatch):
    # pywin32 可导入但非 Windows → COM 不可用（linux CI 上装了 win32com
    # 的诡异环境也不该误报）。
    _pin(monkeypatch, platform="linux", specs={"win32com"})
    assert capabilities.probe_capabilities(force=True).word_com_available is False

    _pin(monkeypatch, platform="win32", specs={"win32com"})
    caps = capabilities.probe_capabilities(force=True)
    assert caps.word_com_available is True
    assert caps.pdf_export_available is True  # COM 单独即可导出


def test_cache_hit_and_force_bypass(monkeypatch):
    calls = []

    def counting_locate():
        calls.append(1)

    monkeypatch.setattr(capabilities, "_locate_soffice", counting_locate)
    monkeypatch.setattr(capabilities, "find_spec", lambda name: None)

    capabilities.probe_capabilities()          # 探测 1 次
    capabilities.probe_capabilities()          # 30s 内 → 命中缓存
    assert len(calls) == 1
    capabilities.probe_capabilities(force=True)  # force → 旁路缓存
    assert len(calls) == 2
