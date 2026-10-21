"""Harness 子系统单元测试（阶段 1）。

覆盖范围：
- Domain：HarnessComponent / EffectivenessMetrics（不可变 + needs_improvement 阈值）
- Adapter：SqliteHarnessAdapter（CRUD + record_usage 累积）
- Service：HarnessService（类型校验 + record_usage 永不抛出）
- Recorder：HarnessRecorder（懒注册 + fire-and-forget + flush_pending）
- HarnessProbe（计时 + success 推断 + 异常传播）
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.adapters.out.harness import SqliteHarnessAdapter
from backend.application.services.harness_recorder import (
    HarnessProbe,
    HarnessRecorder,
    flush_pending,
    get_recorder,
    install_recorder,
    record_skill_usage,
    record_tool_usage,
)
from backend.application.services.harness_service import (
    HarnessService,
    InvalidComponentTypeError,
)
from backend.domain.harness_component import (
    EffectivenessMetrics,
    HarnessComponent,
)

pytestmark = pytest.mark.unit


class _FakeResult:
    """模拟 ToolResult.success 属性，让 probe 推断 success。"""

    def __init__(self, success: bool) -> None:
        self.success = success


# ============================================================
# Domain
# ============================================================


class TestHarnessComponent:
    def test_frozen_immutable(self):
        c = HarnessComponent(id="tool:bash", type="tool_guidance", name="bash")
        with pytest.raises(AttributeError):
            c.name = "new"  # type: ignore[misc]

    def test_defaults(self):
        c = HarnessComponent(id="t:1", type="tool_guidance", name="x")
        assert c.version == "1.0.0"
        assert c.config == {}
        assert c.effectiveness.usage_count == 0
        assert c.effectiveness.success_rate == 1.0

    def test_is_plugin_is_skill(self):
        plugin = HarnessComponent(id="p:1", type="plugins", name="p")
        skill = HarnessComponent(id="s:1", type="skills", name="s")
        assert plugin.is_plugin()
        assert not plugin.is_skill()
        assert skill.is_skill()
        assert not skill.is_plugin()

    @pytest.mark.parametrize(
        ("success_rate", "avg_latency_ms", "satisfaction", "expected"),
        [
            (0.9, 500.0, None, False),  # 全达标
            (0.7, 500.0, None, True),  # 成功率 < 0.8
            (0.95, 1500.0, None, True),  # 延迟 > 1000ms
            (0.95, 500.0, 0.3, True),  # 满意度 < 0.5
        ],
    )
    def test_needs_improvement_thresholds(
        self, success_rate, avg_latency_ms, satisfaction, expected
    ):
        metrics = EffectivenessMetrics(
            usage_count=100,
            success_rate=success_rate,
            avg_latency_ms=avg_latency_ms,
            user_satisfaction=satisfaction,
        )
        c = HarnessComponent(
            id="t:1", type="tool_guidance", name="x", effectiveness=metrics
        )
        assert c.needs_improvement() is expected


class TestEffectivenessMetricsFromUsageData:
    def test_zero_usage(self):
        m = EffectivenessMetrics.from_usage_data(0, 0, 0.0)
        assert m.usage_count == 0
        assert m.success_rate == 1.0
        assert m.avg_latency_ms == 0.0

    def test_success_rate_calculation(self):
        m = EffectivenessMetrics.from_usage_data(10, 7, 1000.0)
        assert m.usage_count == 10
        assert abs(m.success_rate - 0.7) < 1e-9
        assert abs(m.avg_latency_ms - 100.0) < 1e-9

    def test_user_satisfaction(self):
        m = EffectivenessMetrics.from_usage_data(
            usage_count=10,
            success_count=10,
            total_latency_ms=100.0,
            user_satisfaction_sum=4.5,
            user_satisfaction_count=3,
            last_used_at="2026-10-21T00:00:00Z",
        )
        assert abs(m.user_satisfaction - 1.5) < 1e-9
        assert m.last_used_at == "2026-10-21T00:00:00Z"


# ============================================================
# Adapter
# ============================================================


class TestSqliteHarnessAdapter:
    @pytest.fixture(autouse=True)
    def _db(self, setup_test_db):
        self.adapter = SqliteHarnessAdapter()

    @pytest.mark.asyncio()
    async def test_register_then_get(self):
        c = await self.adapter.register_component(
            "tool:bash", "tool_guidance", "bash", {"env": "linux"}
        )
        assert c.id == "tool:bash"
        assert c.type == "tool_guidance"
        assert c.config == {"env": "linux"}
        assert c.effectiveness.usage_count == 0

        fetched = await self.adapter.get_component("tool:bash")
        assert fetched is not None
        assert fetched.id == c.id
        assert fetched.config == c.config

    @pytest.mark.asyncio()
    async def test_register_idempotent(self):
        await self.adapter.register_component("tool:a", "tool_guidance", "a")
        await self.adapter.register_component("tool:a", "tool_guidance", "a", {"x": 1})
        fetched = await self.adapter.get_component("tool:a")
        assert fetched is not None
        assert fetched.config == {"x": 1}  # 第二次注册覆盖 config

    @pytest.mark.asyncio()
    async def test_list_all_and_by_type(self):
        await self.adapter.register_component("tool:a", "tool_guidance", "a")
        await self.adapter.register_component("skill:b", "skills", "b")
        await self.adapter.register_component("tool:c", "tool_guidance", "c")

        all_ = await self.adapter.list_components()
        assert sorted(c.id for c in all_) == ["skill:b", "tool:a", "tool:c"]

        tools = await self.adapter.list_components("tool_guidance")
        assert sorted(c.id for c in tools) == ["tool:a", "tool:c"]

    @pytest.mark.asyncio()
    async def test_get_missing_returns_none(self):
        assert await self.adapter.get_component("ghost") is None

    @pytest.mark.asyncio()
    async def test_record_usage_accumulates(self):
        await self.adapter.register_component("tool:a", "tool_guidance", "a")
        await self.adapter.record_usage("tool:a", success=True, latency_ms=100.0)
        await self.adapter.record_usage("tool:a", success=False, latency_ms=200.0)
        await self.adapter.record_usage("tool:a", success=True, latency_ms=300.0)

        c = await self.adapter.get_component("tool:a")
        assert c is not None
        assert c.effectiveness.usage_count == 3
        assert c.effectiveness.success_rate == pytest.approx(2 / 3)
        assert c.effectiveness.avg_latency_ms == pytest.approx(200.0)

    @pytest.mark.asyncio()
    async def test_record_usage_unknown_component_is_noop(self):
        # 不存在时静默忽略（埋点不应影响主路径）
        await self.adapter.record_usage("tool:ghost", True, 50.0)

    @pytest.mark.asyncio()
    async def test_update_component(self):
        await self.adapter.register_component("tool:a", "tool_guidance", "a", {"v": 1})
        updated = await self.adapter.update_component("tool:a", {"v": 2, "extra": "ok"})
        assert updated is not None
        assert updated.config == {"v": 2, "extra": "ok"}

        # 不存在时返回 None
        assert await self.adapter.update_component("tool:ghost", {}) is None

    @pytest.mark.asyncio()
    async def test_iso_timestamps(self):
        c = await self.adapter.register_component("tool:a", "tool_guidance", "a")
        assert c.created_at is not None
        assert c.updated_at is not None
        assert "T" in c.created_at  # ISO-8601
        assert "Z" in c.created_at


# ============================================================
# Service
# ============================================================


class TestHarnessService:
    @pytest.fixture(autouse=True)
    def _setup(self, setup_test_db):
        self.service = HarnessService(SqliteHarnessAdapter())

    @pytest.mark.asyncio()
    async def test_invalid_type_raises(self):
        with pytest.raises(InvalidComponentTypeError):
            await self.service.list_components("bogus_type")

    @pytest.mark.asyncio()
    async def test_register_and_get(self):
        c = await self.service.register_component(
            "tool:a", "tool_guidance", "a", {"env": "linux"}
        )
        assert c.id == "tool:a"
        fetched = await self.service.get_component("tool:a")
        assert fetched is not None
        assert fetched.id == "tool:a"

    @pytest.mark.asyncio()
    async def test_list_needing_improvement(self):
        await self.service.register_component("tool:good", "tool_guidance", "good")
        await self.service.register_component("tool:bad", "tool_guidance", "bad")

        # 让 bad 触发改进阈值（成功率 < 0.8）
        for _ in range(10):
            await self.service.record_usage("tool:bad", success=False, latency_ms=50.0)
        # 给 good 一次成功
        await self.service.record_usage("tool:good", success=True, latency_ms=50.0)

        needing = await self.service.list_needing_improvement()
        ids = {c.id for c in needing}
        assert "tool:bad" in ids
        assert "tool:good" not in ids

    @pytest.mark.asyncio()
    async def test_record_usage_never_raises(self):
        # 即使组件不存在，service 层也不应抛出（adapter 静默忽略）
        await self.service.record_usage("tool:ghost", True, 50.0)

    @pytest.mark.asyncio()
    async def test_register_invalid_type(self):
        with pytest.raises(InvalidComponentTypeError):
            await self.service.register_component("x", "not_a_real_type", "x")


# ============================================================
# Recorder
# ============================================================


class TestHarnessRecorder:
    @pytest.fixture(autouse=True)
    def _setup(self, setup_test_db):
        install_recorder(None)  # 清理上一用例残留
        self.service = HarnessService(SqliteHarnessAdapter())
        self.recorder = HarnessRecorder(self.service)
        install_recorder(self.recorder)
        yield
        install_recorder(None)

    @pytest.mark.asyncio()
    async def test_record_tool_creates_component_and_increments(self):
        await self.recorder.record_tool("bash", True, 100.0)
        await self.recorder.record_tool("bash", False, 200.0)
        c = await self.service.get_component("tool:bash")
        assert c is not None
        assert c.effectiveness.usage_count == 2
        assert c.effectiveness.success_rate == pytest.approx(0.5)

    @pytest.mark.asyncio()
    async def test_record_skill_uses_skill_prefix(self):
        await self.recorder.record_skill("review-code", True, 50.0)
        c = await self.service.get_component("skill:review-code")
        assert c is not None
        assert c.type == "skills"
        assert c.effectiveness.usage_count == 1

    @pytest.mark.asyncio()
    async def test_known_cache_avoids_duplicate_register(self):
        # 注册两次，DB 只写一次（_known 缓存）
        ok1 = await self.recorder.ensure_component("tool:a", "tool_guidance", "a")
        ok2 = await self.recorder.ensure_component("tool:a", "tool_guidance", "a")
        assert ok1
        assert ok2
        assert "tool:a" in self.recorder._known

    @pytest.mark.asyncio()
    async def test_record_never_raises(self):
        # 故意破坏 service 让 register 抛异常
        broken = HarnessRecorder(self.service)
        broken._service = None  # type: ignore[assignment]
        await broken.record("tool:x", "tool_guidance", "x", True, 10.0)  # 应吞异常


class TestRecordFireAndForget:
    @pytest.fixture(autouse=True)
    def _setup(self, setup_test_db):
        install_recorder(None)
        self.service = HarnessService(SqliteHarnessAdapter())
        install_recorder(HarnessRecorder(self.service))
        yield
        install_recorder(None)

    def test_record_tool_usage_from_sync_context(self):
        """fire-and-forget 在同步上下文也能 dispatch（线程池兜底）。"""
        record_tool_usage("bash", True, 50.0)
        record_tool_usage("bash", True, 100.0)
        assert flush_pending(timeout=3.0)

        c = asyncio.run(self.service.get_component("tool:bash"))
        assert c is not None
        assert c.effectiveness.usage_count == 2

    def test_record_skill_usage_from_sync(self):
        record_skill_usage("review-code", True, 75.0)
        assert flush_pending(timeout=3.0)
        c = asyncio.run(self.service.get_component("skill:review-code"))
        assert c is not None
        assert c.effectiveness.usage_count == 1

    def test_no_recorder_is_noop(self):
        install_recorder(None)
        record_tool_usage("bash", True, 50.0)  # 不应抛
        record_skill_usage("review-code", True, 50.0)

    def test_get_recorder_returns_installed(self):
        assert get_recorder() is not None


class TestHarnessProbe:
    @pytest.fixture(autouse=True)
    def _setup(self, setup_test_db):
        install_recorder(None)
        self.service = HarnessService(SqliteHarnessAdapter())
        install_recorder(HarnessRecorder(self.service))
        yield
        install_recorder(None)

    def test_probe_measures_latency_and_success(self):
        with HarnessProbe("tool", "bash") as probe:
            time.sleep(0.01)  # 模拟耗时
            probe.result = _FakeResult(success=True)
        assert probe.success is True
        assert probe.latency_ms >= 10  # 至少 10ms
        flush_pending(timeout=3.0)
        c = asyncio.run(self.service.get_component("tool:bash"))
        assert c is not None
        assert c.effectiveness.success_rate == 1.0

    def test_probe_records_failure_on_exception(self):
        with pytest.raises(RuntimeError), HarnessProbe("tool", "bash") as probe:
            raise RuntimeError("boom")
        assert probe.success is False
        flush_pending(timeout=3.0)
        c = asyncio.run(self.service.get_component("tool:bash"))
        assert c is not None
        assert c.effectiveness.success_rate == 0.0

    def test_probe_records_failure_when_result_is_none(self):
        # 模拟取消 / 无结果路径
        with HarnessProbe("tool", "bash") as probe:
            pass  # 未设置 probe.result
        assert probe.success is False
        flush_pending(timeout=3.0)
        c = asyncio.run(self.service.get_component("tool:bash"))
        assert c is not None
        assert c.effectiveness.success_rate == 0.0

    def test_probe_skill_kind(self):
        with HarnessProbe("skill", "review-code") as probe:
            probe.result = _FakeResult(success=True)
        flush_pending(timeout=3.0)
        c = asyncio.run(self.service.get_component("skill:review-code"))
        assert c is not None
        assert c.type == "skills"
