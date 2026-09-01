"""Security regressions for Vision ingest temporary-file handling."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.wiki import file_parser, vision_ingest
from backend.wiki.extract import MAX_FILE_BYTES
from backend.wiki.ingest import IngestConfig
from backend.wiki.vision import VisionConfig, VisionProvider
from backend.wiki.vision_ingest import VisionIngestConfig, ingest_with_vision


@pytest.fixture()
def vision_config(tmp_path: Path) -> VisionIngestConfig:
    return VisionIngestConfig(
        ingest_config=IngestConfig("http://llm.test", "key", "model", "http://embed.test", "key", "embed"),
        vision_config=VisionConfig(VisionProvider.OLLAMA, "http://vision.test", "key", "vision"),
        project_root=tmp_path,
        auto_caption=False,
    )


@pytest.mark.asyncio()
async def test_parser_uses_held_snapshot_when_snapshot_path_is_replaced(
    tmp_path, vision_config, monkeypatch
):
    source = tmp_path / "source.md"
    source.write_bytes(b"original snapshot")
    captured = {}

    async def fake_ingest_source(**kwargs):
        captured.update(kwargs)
        return "ok"

    real_parse = file_parser.parse_document

    def replace_path_then_parse(path, *, opened_fd, max_file_bytes):
        captured["snapshot_path"] = path
        path.unlink()
        path.write_bytes(b"attacker content")
        parsed = real_parse(path, opened_fd=opened_fd, max_file_bytes=max_file_bytes)
        captured["parsed_text"] = parsed
        return parsed

    monkeypatch.setattr(file_parser, "parse_document", replace_path_then_parse)
    monkeypatch.setattr("backend.wiki.vision_ingest.ingest_source", fake_ingest_source)

    result = await ingest_with_vision(
        vision_config, source, AsyncMock(), AsyncMock()
    )

    assert result == "ok"
    assert captured["parsed_text"] == "original snapshot"
    assert captured["source_content"] == b"original snapshot"


@pytest.mark.asyncio()
async def test_enhanced_content_does_not_reopen_a_temporary_path(
    tmp_path, vision_config, monkeypatch
):
    source = tmp_path / "source.md"
    source.write_bytes(b"source")
    captured = {}

    async def fake_ingest_source(**kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        "backend.wiki.file_parser.parse_document", lambda *args, **kwargs: "parsed"
    )
    monkeypatch.setattr("backend.wiki.vision_ingest.ingest_source", fake_ingest_source)

    def fail_path_open(self, *args, **kwargs):
        raise AssertionError("Vision ingest must not reopen an enhanced temp pathname")

    monkeypatch.setattr(Path, "open", fail_path_open)
    result = await ingest_with_vision(
        vision_config, source, AsyncMock(), AsyncMock()
    )

    assert result == "ok"
    assert captured["source_content"] == b"source"
    assert captured["processed_content"] == "parsed"


@pytest.mark.asyncio()
async def test_source_over_limit_is_rejected_before_snapshot_creation(
    tmp_path, vision_config
):
    source = tmp_path / "large.md"
    source.write_bytes(b"x" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="source exceeds configured ingest limit"):
        await ingest_with_vision(vision_config, source, AsyncMock(), AsyncMock())


@pytest.mark.asyncio()
async def test_snapshot_cleanup_error_does_not_mask_ingest_result(
    tmp_path, vision_config, monkeypatch
):
    source = tmp_path / "source.md"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        "backend.wiki.file_parser.parse_document", lambda *args, **kwargs: "parsed"
    )
    monkeypatch.setattr(
        "backend.wiki.vision_ingest.ingest_source", AsyncMock(return_value="ok")
    )

    def fail_unlink(self, *args, **kwargs):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    assert await ingest_with_vision(vision_config, source, AsyncMock(), AsyncMock()) == "ok"


def test_bounded_read_rejects_hardlink_to_outside(tmp_path: Path):
    outside = tmp_path / "outside.md"
    linked = tmp_path / "source.md"
    outside.write_bytes(b"outside secret")
    try:
        linked.hardlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks are not supported")

    with pytest.raises(OSError, match="多链接"):
        vision_ingest._read_bounded_file(linked)

    assert outside.read_bytes() == b"outside secret"


def test_bounded_read_fails_closed_when_no_follow_is_unavailable(monkeypatch, tmp_path):
    source = tmp_path / "source.md"
    source.write_bytes(b"source")
    monkeypatch.delattr(vision_ingest.os, "O_NOFOLLOW", raising=False)

    with pytest.raises(OSError, match="O_NOFOLLOW"):
        vision_ingest._read_bounded_file(source)
