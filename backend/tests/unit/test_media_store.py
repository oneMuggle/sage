"""MediaStore 单元测试"""

import pytest

pytestmark = [pytest.mark.unit]


def test_media_kind_enum():
    from backend.services.multimodal.media_store import MediaKind
    assert MediaKind.IMAGE.value == "image"
    assert MediaKind.AUDIO.value == "audio"


def test_media_ref_api_url():
    from backend.services.multimodal.media_store import MediaKind, MediaRef
    ref = MediaRef(
        id="abc123", kind=MediaKind.AUDIO, mime_type="audio/mpeg",
        file_path="2026/09/12/abc123.mp3", file_size=1024,
        created_at="2026-09-12T10:00:00Z", source="tts",
    )
    assert ref.api_url == "/api/v1/media/abc123"


def test_save_creates_file(tmp_path):
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    store = MediaStore(root=tmp_path)
    # PNG magic bytes
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    ref = store.save(content=content, kind=MediaKind.IMAGE, source="image_gen")
    assert ref.kind == MediaKind.IMAGE
    assert ref.mime_type == "image/png"
    assert ref.file_size == len(content)
    assert ref.source == "image_gen"
    assert (tmp_path / ref.file_path).exists()
    assert (tmp_path / ref.file_path).read_bytes() == content


def test_save_audio_with_explicit_ext(tmp_path):
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    store = MediaStore(root=tmp_path)
    content = b"\xff\xfb\x90\x00" + b"\x00" * 50
    ref = store.save(content=content, kind=MediaKind.AUDIO, source="tts", ext="mp3")
    assert ref.mime_type == "audio/mpeg"
    assert ref.file_path.endswith(".mp3")


def test_load_existing_media(tmp_path):
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    store = MediaStore(root=tmp_path)
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
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
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    store = MediaStore(root=tmp_path)
    ref = store.save(content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 5, kind=MediaKind.IMAGE, source="test")
    assert store.delete(ref.id) is True
    assert store.load(ref.id) is None


def test_delete_nonexistent_returns_false(tmp_path):
    from backend.services.multimodal.media_store import MediaStore
    store = MediaStore(root=tmp_path)
    assert store.delete("nonexistent") is False


def test_guess_mime_magic_bytes():
    from backend.services.multimodal.media_store import MediaKind, MediaStore
    assert MediaStore._guess_mime(b"\x89PNG\r\n\x1a\n" + b"\x00", MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b"\xff\xd8\xff" + b"\x00", MediaKind.IMAGE) == "image/jpeg"
    assert MediaStore._guess_mime(b"RIFF\x00\x00\x00\x00WAVE", MediaKind.AUDIO) == "audio/wav"
    assert MediaStore._guess_mime(b"ID3\x00" + b"\x00", MediaKind.AUDIO) == "audio/mpeg"
    # fallback
    assert MediaStore._guess_mime(b"\x00\x00\x00", MediaKind.IMAGE) == "image/png"
    assert MediaStore._guess_mime(b"\x00\x00\x00", MediaKind.AUDIO) == "audio/mpeg"


# ── P0 (2026-11-04): 附件类型分类回归测试 ─────────────────────────────────
#
# 回归根因: commit 0fb10c4bb (#2001) 扩展上传 allowlist 到约 50 种格式,
# 但 MediaStore.load() 的后缀表只补了 .xlsx —— csv/py/ts/json 等全部被
# 判定为 AUDIO,聊天注入循环 `if kind != DOCUMENT: continue` 静默跳过。
# 以下用例以「上传端真实 allowlist」为数据源,保证两侧口径不再漂移。


@pytest.mark.parametrize(
    "ext",
    [
        "txt", "md", "csv", "py", "js", "ts", "jsx", "tsx", "json", "yaml",
        "yml", "html", "css", "sql", "log", "sh", "go", "rs", "java", "cpp",
        "toml", "ini", "xml",
    ],
)
def test_save_then_load_keeps_document_kind_across_text_extensions(tmp_path, ext):
    """上传时判定为 DOCUMENT 的文本/代码附件,load() 后必须仍是 DOCUMENT。"""
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    store = MediaStore(root=tmp_path)
    ref = store.save(
        content=b"print('hello')\n",
        kind=MediaKind.DOCUMENT,
        source="chat_upload",
        metadata={"original_filename": f"sample.{ext}"},
        ext=ext,
    )
    assert ref.kind == MediaKind.DOCUMENT

    loaded = store.load(ref.id)
    assert loaded is not None
    loaded_ref, content = loaded
    assert content == b"print('hello')\n"
    assert loaded_ref.kind == MediaKind.DOCUMENT, (
        f".{ext} 被误判为 {loaded_ref.kind.value}; "
        "MediaStore.load 的后缀回退表必须与上传 allowlist 同口径"
    )


def test_load_legacy_media_without_sidecar_uses_expanded_fallback(tmp_path):
    """历史媒体(无 sidecar)必须走后缀回退;扩展后的文本格式不能再落到 AUDIO。"""
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    root = tmp_path
    (root / "2026" / "10" / "01").mkdir(parents=True)
    cases = {
        "abc123.py": MediaKind.DOCUMENT,
        "abc124.csv": MediaKind.DOCUMENT,
        "abc125.ts": MediaKind.DOCUMENT,
        "abc126.json": MediaKind.DOCUMENT,
        "abc127.mp3": MediaKind.AUDIO,
        "abc128.png": MediaKind.IMAGE,
    }
    for filename in cases:
        (root / "2026" / "10" / "01" / filename).write_bytes(b"hello")

    store = MediaStore(root=root)
    for filename, expected in cases.items():
        media_id = filename.split(".")[0]
        loaded = store.load(media_id)
        assert loaded is not None, filename
        assert loaded[0].kind == expected, (
            f"{filename}: expected {expected.value}, got {loaded[0].kind.value}"
        )


def test_sidecar_persists_original_filename_and_metadata(tmp_path):
    """save() 写 sidecar 后,load() 必须恢复 original_filename/mime/source。"""
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    store = MediaStore(root=tmp_path)
    ref = store.save(
        content=b"col1,col2\n1,2\n",
        kind=MediaKind.DOCUMENT,
        source="chat_upload",
        metadata={"original_filename": "数据 表.csv"},
        ext="csv",
    )
    assert ref.metadata["original_filename"] == "数据 表.csv"

    loaded = store.load(ref.id)
    assert loaded is not None
    loaded_ref = loaded[0]
    assert loaded_ref.kind == MediaKind.DOCUMENT
    assert loaded_ref.source == "chat_upload"
    assert loaded_ref.metadata["original_filename"] == "数据 表.csv"


def test_delete_removes_media_and_sidecar(tmp_path):
    """delete() 必须同时清理媒体文件与 sidecar(旧实现只删第一个匹配项)。"""
    from backend.services.multimodal.media_store import MediaKind, MediaStore

    store = MediaStore(root=tmp_path)
    ref = store.save(
        content=b"hello",
        kind=MediaKind.DOCUMENT,
        source="chat_upload",
        metadata={"original_filename": "a.py"},
        ext="py",
    )
    media_path = tmp_path / ref.file_path
    sidecar = media_path.with_name(media_path.stem + ".meta.json")
    assert media_path.exists()
    assert sidecar.exists()

    assert store.delete(ref.id) is True
    assert not media_path.exists()
    assert not sidecar.exists()
    assert store.load(ref.id) is None
