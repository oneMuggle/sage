"""Integration tests for evolution task registration into SchedulerService.

PR-C §5.1: verify _register_evolution_tasks() wires all 5 evolution tasks
into the BackgroundScheduler at lifespan startup.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from backend.services.scheduler import SchedulerService


def _make_service(tmp_path: Path) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=MagicMock(),
        session_repo=MagicMock(),
    )


def test_lifespan_registers_all_five_evolution_tasks(tmp_path):
    """Default schedule registers all 5 evolution tasks."""
    from backend.services._evolution_register import _register_evolution_tasks

    svc = _make_service(tmp_path)
    registered = _register_evolution_tasks(svc, config_path=None)

    expected = {
        "daily_summary",
        "memory_pruning",
        "preference_learning",
        "importance_reevaluation",
        "memory_consolidation",
    }
    assert set(registered.keys()) == expected
    for name in registered:
        job = svc._scheduler.get_job(f"evolution/{name}")
        assert job is not None, f"job missing: {name}"
    assert len(registered) == 5


def test_yaml_override_takes_precedence_over_default(tmp_path):
    """config.yaml memory_consolidation.time='5:30' overrides default '30 4 * * 0'."""
    from backend.services._evolution_register import _register_evolution_tasks

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "evolution": {
                    "tasks": {"memory_consolidation": {"time": "5:30"}}
                }
            }
        )
    )

    svc = _make_service(tmp_path)
    registered = _register_evolution_tasks(svc, config_path=cfg)

    assert registered["memory_consolidation"] == "30 5 * * *"
    # 其他任务仍用默认
    assert registered["memory_pruning"] == "30 3 * * *"


def test_missing_yaml_uses_defaults(tmp_path):
    """config.yaml 不存在 → 默认 5 个仍全部注册。"""
    from backend.services._evolution_register import _register_evolution_tasks

    svc = _make_service(tmp_path)
    registered = _register_evolution_tasks(
        svc, config_path=tmp_path / "nope.yaml"
    )
    assert registered["memory_consolidation"] == "30 4 * * 0"
    assert len(registered) == 5


def test_yaml_malformed_logs_warning_uses_defaults(tmp_path, caplog):
    """YAML 解析失败 → log warning + 默认全部注册成功。"""
    from backend.services._evolution_register import _register_evolution_tasks

    cfg = tmp_path / "config.yaml"
    cfg.write_text(":\n  bad:\n    - : :\n")  # 故意坏 YAML

    svc = _make_service(tmp_path)
    with caplog.at_level(logging.WARNING):
        registered = _register_evolution_tasks(svc, config_path=cfg)
    assert len(registered) == 5
    assert any("config.yaml" in r.message for r in caplog.records)


def test_yaml_invalid_time_field_skips_that_task(tmp_path, caplog):
    """单个任务 time 字段越界 → log warning + 跳过该 override,但仍用默认 cron 注册。"""
    from backend.services._evolution_register import _register_evolution_tasks

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "evolution": {
                    "tasks": {"memory_consolidation": {"time": "25:99"}}
                }
            }
        )
    )

    svc = _make_service(tmp_path)
    with caplog.at_level(logging.WARNING):
        registered = _register_evolution_tasks(svc, config_path=cfg)
    # memory_consolidation 仍在(走默认 cron),但用了 default 30 4 * * 0
    assert "memory_consolidation" in registered
    assert registered["memory_consolidation"] == "30 4 * * 0"
    assert len(registered) == 5
    # 日志有 warning
    assert any("memory_consolidation" in r.message for r in caplog.records)
