# backend/tests/unit/test_artifact_reader.py
from unittest.mock import patch

from backend.data import artifact_reader, artifact_repo


def test_read_text_markdown(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "doc.md", "markdown", 14)

    result = artifact_reader.read_text(aid)

    assert result["ok"] is True
    assert result["kind"] == "markdown"
    assert result["content"] == "# Hello\n\nWorld"
    assert result["truncated"] is False


def test_read_text_truncates_long_content(tmp_path):
    f = tmp_path / "big.md"
    f.write_text("x" * 600_000, encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "big.md", "markdown", 600_000)

    result = artifact_reader.read_text(aid)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["content"]) <= 500_000


def test_read_text_missing_file(tmp_path):
    aid = artifact_repo.record_artifact("sess_001", str(tmp_path / "gone.md"), "gone.md", "markdown", 0)
    result = artifact_reader.read_text(aid)
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_read_text_missing_artifact():
    result = artifact_reader.read_text("nonexistent")
    assert result["ok"] is False


def test_read_image_returns_data_url(tmp_path):
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    f = tmp_path / "pixel.png"
    f.write_bytes(png_bytes)
    aid = artifact_repo.record_artifact("sess_001", str(f), "pixel.png", "image", len(png_bytes))

    result = artifact_reader.read_image(aid)

    assert result["ok"] is True
    assert result["kind"] == "image"
    assert result["data_url"].startswith("data:image/png;base64,")


def test_reveal_in_file_manager(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("test", encoding="utf-8")
    aid = artifact_repo.record_artifact("sess_001", str(f), "doc.md", "markdown", 4)

    with patch("subprocess.run", return_value=None) as mock_run:
        result = artifact_reader.reveal_in_file_manager(aid)

    assert result["ok"] is True
    mock_run.assert_called_once()
