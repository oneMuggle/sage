"""Wiki 项目设置：持久化与任务路由解析。"""

from __future__ import annotations

import json

import pytest

from backend.wiki.settings import (
    ReasoningConfig,
    TaskRoutingConfig,
    WikiSettings,
    load_settings,
    resolve_model_for_task,
    save_settings,
)

pytestmark = pytest.mark.unit


def test_load_settings_missing_returns_defaults(tmp_path) -> None:
    settings = load_settings(tmp_path)
    assert settings.task_routing.chat_model is None
    assert settings.reasoning.chat_mode == "auto"
    assert settings.reasoning.ingest_mode == "off"


def test_save_then_load_roundtrip(tmp_path) -> None:
    original = WikiSettings(
        task_routing=TaskRoutingConfig(
            chat_model="m-chat",
            ingest_model="m-ingest",
            research_model=None,
        ),
        reasoning=ReasoningConfig(chat_mode="high", ingest_mode="off"),
    )

    save_settings(tmp_path, original)

    path = tmp_path / ".llm-wiki" / "settings.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["task_routing"]["chat_model"] == "m-chat"
    assert payload["reasoning"]["ingest_mode"] == "off"
    assert load_settings(tmp_path) == original


def test_load_settings_corrupt_file_falls_back(tmp_path) -> None:
    path = tmp_path / ".llm-wiki" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_settings(tmp_path) == WikiSettings()


def test_from_dict_ignores_unknown_keys(tmp_path) -> None:
    path = tmp_path / ".llm-wiki" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "task_routing": {"chat_model": "x", "unknown": 1},
                "reasoning": {"chat_mode": "medium"},
                "extra": True,
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)
    assert settings.task_routing.chat_model == "x"
    assert settings.reasoning.chat_mode == "medium"
    assert settings.reasoning.ingest_mode == "off"


@pytest.mark.parametrize(
    ("task", "expected"),
    [("chat", "c"), ("ingest", "i"), ("research", "r")],
)
def test_resolve_model_for_task_routes_each_task(task: str, expected: str) -> None:
    settings = WikiSettings(
        task_routing=TaskRoutingConfig(
            chat_model="c", ingest_model="i", research_model="r"
        )
    )
    assert resolve_model_for_task(settings, task, "default") == expected


def test_resolve_model_for_task_falls_back_to_default() -> None:
    assert resolve_model_for_task(WikiSettings(), "chat", "default") == "default"


def test_resolve_model_for_task_unknown_task_uses_default() -> None:
    settings = WikiSettings(task_routing=TaskRoutingConfig(chat_model="c"))
    assert resolve_model_for_task(settings, "unknown", "default") == "default"
