"""MediaStore 单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def test_media_kind_enum():
    from backend.services.multimodal.media_store import MediaKind
    assert MediaKind.IMAGE.value == "image"
    assert MediaKind.AUDIO.value == "audio"


def test_media_ref_api_url():
    from backend.services.multimodal.media_store import MediaRef, MediaKind
    ref = MediaRef(
        id="abc123", kind=MediaKind.AUDIO, mime_type="audio/mpeg",
        file_path="2026/09/12/abc123.mp3", file_size=1024,
        created_at="2026-09-12T10:00:00Z", source="tts",
    )
    assert ref.api_url == "/api/v1/media/abc123"


def test_save_creates_file(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    # PNG magic bytes
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="image_gen")
    assert ref.kind == MediaKind.IMAGE
    assert ref.mime_type == "image/png"
    assert ref.file_size == len(content)
    assert ref.source == "image_gen"
    assert (tmp_path / ref.file_path).exists()
    assert (tmp_path / ref.file_path).read_bytes() == content


def test_save_audio_with_explicit_ext(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    content = b'\xff\xfb\x90\x00' + b'\x00' * 50
    ref = store.save(content=content, kind=MediaKind.AUDIO, source="tts", ext="mp3")
    assert ref.mime_type == "audio/mpeg"
    assert ref.file_path.endswith(".mp3")


def test_load_existing_media(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 10
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="image_gen")
    result = store.load(ref.id)
    assert result is not None
    loaded_ref, loaded_content = result
    assert loaded_ref.id == ref.id
    assert loaded_content == content


def test_load_nonexistent_returns_none(tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(root=tmp_path)
    assert store.load("nonexistent_id") is None


def test_delete_media(tmp_path):
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    store = MediaStore(root=tmp_path)
    ref = store.save(content=b'\x89PNG\r\n\x1a\n' + b'\x00' * 5, kind=MediaKind.IMAGE, source="test")
    assert store.delete(ref.id) is True
    assert store.load(ref.id) is None


def test_delete_nonexistent_returns_false(tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(root=tmp_path)
    assert store.delete("nonexistent") is False


def test_guess_mime_magic_bytes():
    from backend.services.multimodal.media_store import MediaStore, MediaKind
    assert MediaStore._guess_mime(b'\x89PNG\r\n\x1a\n' + b'\x00', MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b'\xff\xd8\xff' + b'\x00', MediaKind.IMAGE) == "image/jpeg"
    assert MediaStore._guess_mime(b'RIFF\x00\x00\x00\x00WAVE', MediaKind.AUDIO) == "audio/wav"
    assert MediaStore._guess_mime(b'ID3\x00' + b'\x00', MediaKind.AUDIO) == "audio/mpeg"
    # fallback
    assert MediaStore._guess_mime(b'\x00\x00\x00', MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b'\x00\x00\x00', MediaKind.AUDIO) == "audio/mpeg"
