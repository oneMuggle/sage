# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""渲染实例池测试（R24 多槽 LRU / R42 自动扩槽）。

从 test_web_render.py 拆出（架构 800 行门禁）：只保留实例池相关用例。
CDP 交互全部 stub，浏览器进程用假体模拟。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.tools import browser_cdp, web_render
from backend.tools.web_render import RENDER_IDLE_TIMEOUT_SECONDS, RENDER_POOL_ID

pytestmark = [pytest.mark.unit]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def fake_time(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)
    return clock


class _FakeSettingsRepo:
    def __init__(self, raw: str = None):
        self.raw = raw

    def get(self, key: str):
        return self.raw


class _FakePoolSession:
    def __init__(self, alive: bool = True, browser_id: str = None):
        self.browser_id = browser_id or RENDER_POOL_ID
        self.alive = alive
        self.user_data_dir = "/tmp/unused"
        self.process = SimpleNamespace(
            terminate=lambda: None, wait=lambda timeout=None: 0, kill=lambda: None
        )

    def is_alive(self) -> bool:
        return self.alive


def test_renderer_pool_spreads_and_reuses_across_slots(fake_time, monkeypatch):
    """R24 多槽：并发 acquire 按 LRU 分散到不同实例；单槽复用、单槽重建。"""
    pool = web_render._RendererPool()
    created = []

    def _fake_launch(headless, browser_id=None, **kwargs):
        assert headless is True
        assert browser_id in web_render.RENDER_POOL_IDS  # 保留前缀，用户实例解析不受干扰
        session = _FakePoolSession(browser_id=browser_id)
        created.append(session)
        return session

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    fake_time.now = 10  # 初始 last_used=0.0，先拨离 0 避免 tie 歧义
    first = pool.acquire()  # 槽 1
    fake_time.now += 1
    second = pool.acquire()  # 槽 2
    assert first is not second  # LRU 分散到不同槽位（崩溃隔离）
    assert len(created) == 2

    fake_time.now += 1
    third = pool.acquire()  # 槽 1 最久未用 → 复用
    assert third is first
    assert len(created) == 2

    second.alive = False  # 槽 2 进程死亡 → LRU 选中该槽时重建，槽 1 不受波及
    fake_time.now += 1
    fourth = pool.acquire()
    assert fourth is not second
    assert len(created) == 3
    assert first.alive


def test_renderer_pool_falls_over_to_next_slot_on_launch_failure(monkeypatch):
    """首选槽启动失败 → 降级试下一槽，全部失败才抛 RenderError。"""
    pool = web_render._RendererPool()
    calls = []

    def _fake_launch(headless, browser_id=None, **kwargs):
        calls.append(browser_id)
        if browser_id == RENDER_POOL_ID:
            raise browser_cdp.BrowserCDPError("boom")
        return _FakePoolSession(browser_id=browser_id)

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    session = pool.acquire()
    assert session.browser_id == f"{RENDER_POOL_ID}-2"
    assert calls == [RENDER_POOL_ID, f"{RENDER_POOL_ID}-2"]


def test_renderer_pool_rebuilds_after_idle_timeout(monkeypatch):
    pool = web_render._RendererPool()
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)
    created = []

    def _fake_launch(headless, browser_id=None, **kwargs):
        session = _FakePoolSession()
        created.append(session)
        return session

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    first = pool.acquire()
    clock.now += RENDER_IDLE_TIMEOUT_SECONDS + 1
    second = pool.acquire()
    assert second is not first
    assert len(created) == 2


def test_reserved_id_excluded_from_user_instance_resolution():
    """保留 id 不算用户实例：渲染池常驻时 browser_snapshot 仍能免 id 解析。"""
    manager = browser_cdp.BrowserSessionManager()
    manager.register(_FakePoolSession())  # 仅渲染池在场
    assert manager.get(None) is None

    manager.register(_FakePoolSession(browser_id=f"{RENDER_POOL_ID}-2"))  # R24 多槽
    assert manager.get(None) is None  # 前缀槽位同样不算用户实例

    user = SimpleNamespace(browser_id="b1")
    manager.register(user)
    assert manager.get(None) is user  # 唯一用户实例照常免 id

    assert manager.get(RENDER_POOL_ID) is not None  # 显式指名仍可达


# ---------- R42：渲染池自动扩槽（默认配置语义） ----------


def test_pool_auto_extends_to_max_when_unconfigured(fake_time, monkeypatch):
    """未显式配置 → 自动模式上限 MAX=4；持续使用下懒增到 4 槽。"""
    from backend.data import settings_repo

    monkeypatch.setattr(settings_repo, "SettingsRepository", lambda: _FakeSettingsRepo("{}"))
    created: Any = []

    def _fake_launch(headless, browser_id=None, **kwargs):
        created.append(_FakePoolSession(browser_id=browser_id))
        return created[-1]

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)

    pool = web_render._RendererPool()
    ids = set()
    for _ in range(4):
        clock.now += 1
        ids.add(pool.acquire().browser_id)
    assert ids == set(web_render._render_pool_ids(web_render.RENDER_POOL_SIZE_MAX))
    assert len(created) == 4


def test_pool_explicit_config_caps_slots(fake_time, monkeypatch):
    """显式配置 render_pool_size=3 → 上限 3，不自动扩到 MAX。"""
    import json as _json

    from backend.data import settings_repo

    monkeypatch.setattr(
        settings_repo,
        "SettingsRepository",
        lambda: _FakeSettingsRepo(_json.dumps({"render_pool_size": 3})),
    )
    created: Any = []

    def _fake_launch(headless, browser_id=None, **kwargs):
        created.append(_FakePoolSession(browser_id=browser_id))
        return created[-1]

    monkeypatch.setattr(web_render, "launch_browser", _fake_launch)
    clock = _FakeClock()
    monkeypatch.setattr(web_render, "time", clock)

    pool = web_render._RendererPool()
    ids = set()
    for _ in range(4):
        clock.now += 1
        ids.add(pool.acquire().browser_id)
    assert ids == set(web_render._render_pool_ids(3))
    assert len(created) == 3

