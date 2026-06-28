"""theme_storage 单元测试 — TDD"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.theme_storage import ThemeStorage


@pytest.fixture()
def storage(tmp_path: Path) -> ThemeStorage:
    """使用临时目录作为存储根"""
    return ThemeStorage(storage_dir=tmp_path)


@pytest.fixture()
def sample_payload() -> dict:
    return {
        "id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "name": "Test Theme",
        "css": ":root { --bg-base: #fff; }",
        "appearance": "light",
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
    }


class TestThemeStorageSave:
    def test_save_creates_file(
        self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path
    ) -> None:
        theme_id = storage.save(sample_payload)
        assert theme_id == sample_payload["id"]
        file_path = tmp_path / f"{sample_payload['id']}.json"
        assert file_path.exists()

    def test_save_writes_valid_json(
        self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path
    ) -> None:
        storage.save(sample_payload)
        file_path = tmp_path / f"{sample_payload['id']}.json"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["name"] == "Test Theme"
        assert data["css"] == ":root { --bg-base: #fff; }"

    def test_save_overwrites_existing(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        sample_payload["name"] = "Updated"
        storage.save(sample_payload)
        result = storage.get(sample_payload["id"])
        assert result is not None
        assert result["name"] == "Updated"

    def test_save_uses_atomic_write(
        self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path
    ) -> None:
        """保存后不应残留 .tmp 文件"""
        storage.save(sample_payload)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_rejects_missing_id(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="id"):
            storage.save({"name": "x", "css": ":root {}", "appearance": "light"})

    def test_save_rejects_missing_name(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="name"):
            storage.save({"id": "abc", "css": ":root {}", "appearance": "light"})

    def test_save_rejects_missing_css(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="css"):
            storage.save({"id": "abc", "name": "x", "appearance": "light"})

    def test_save_rejects_invalid_appearance(self, storage: ThemeStorage) -> None:
        with pytest.raises(ValueError, match="appearance"):
            storage.save({"id": "abc", "name": "x", "css": ":root {}", "appearance": "sepia"})


class TestThemeStorageList:
    def test_list_empty(self, storage: ThemeStorage) -> None:
        assert storage.list() == []

    def test_list_returns_all(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        second = {
            **sample_payload,
            "id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
            "name": "Other",
        }
        storage.save(second)
        result = storage.list()
        assert len(result) == 2

    def test_list_skips_corrupted_json(
        self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path
    ) -> None:
        storage.save(sample_payload)
        (tmp_path / "corrupted.json").write_text("{bad json", encoding="utf-8")
        result = storage.list()
        assert len(result) == 1
        assert result[0]["id"] == sample_payload["id"]


class TestThemeStorageGet:
    def test_get_existing(self, storage: ThemeStorage, sample_payload: dict) -> None:
        storage.save(sample_payload)
        result = storage.get(sample_payload["id"])
        assert result is not None
        assert result["name"] == "Test Theme"

    def test_get_missing(self, storage: ThemeStorage) -> None:
        assert storage.get("nonexistent-id") is None


class TestThemeStorageDelete:
    def test_delete_existing(
        self, storage: ThemeStorage, sample_payload: dict, tmp_path: Path
    ) -> None:
        storage.save(sample_payload)
        assert storage.delete(sample_payload["id"]) is True
        assert not (tmp_path / f"{sample_payload['id']}.json").exists()

    def test_delete_missing(self, storage: ThemeStorage) -> None:
        assert storage.delete("nonexistent-id") is False
