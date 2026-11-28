"""运行目录日志扩展（spec §7.4 / §5.5）。"""

from pathlib import Path

import pytest

from backend.literature.run_store import (
    count_downloads,
    create_run,
    read_jsonl,
    record_download,
    record_query,
)

pytestmark = pytest.mark.unit


def test_record_query_includes_transport_fields(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_query(
        run,
        "关键词",
        "demo-site",
        3,
        transport="http",
        fallback_reason="host_404",
        backend_id="db3",
    )
    rows = read_jsonl(run.run_dir / "query_log.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["transport"] == "http"
    assert row["fallback_reason"] == "host_404"
    assert row["backend_id"] == "db3"
    assert row["query"] == "关键词"
    assert row["at"]


def test_record_query_defaults_to_browser_transport(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_query(run, "关键词", "demo-site", 1)
    rows = read_jsonl(run.run_dir / "query_log.jsonl")
    assert rows[0]["transport"] == "browser"
    assert rows[0]["fallback_reason"] == ""


def test_record_download_appends_to_downloads_log(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_download(run, "demo.example", "https://demo.example/a.pdf", True, "http")
    record_download(run, "demo.example", "https://demo.example/b.pdf", False, "browser", "host_404")
    rows = read_jsonl(run.run_dir / "downloads.jsonl")
    assert len(rows) == 2
    assert rows[0]["domain"] == "demo.example"
    assert rows[0]["ok"] is True
    assert rows[0]["transport"] == "http"
    assert rows[1]["ok"] is False
    assert rows[1]["reason"] == "host_404"
    assert rows[1]["at"]


def test_count_downloads_counts_only_successful(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_download(run, "demo.example", "https://demo.example/a.pdf", True, "http")
    record_download(run, "demo.example", "https://demo.example/b.pdf", False, "http")
    assert count_downloads(run) == 1
