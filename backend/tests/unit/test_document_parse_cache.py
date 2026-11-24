from __future__ import annotations

from backend.data.database import Database
from backend.domain.document_parse import ParseResult
from backend.services.document_parse.cache import SqliteParseCache


def test_roundtrip(tmp_path) -> None:
    db = Database(str(tmp_path / "t.db"))
    db.init_db()
    cache = SqliteParseCache(db)
    result = ParseResult(
        text="hello",
        engine_used="mineru",
        structured={"pages": [1]},
        tier_used="standard",
        quality_score=0.9,
        duration_ms=12,
        warnings=["partial_result"],
        media_url=None,
        assets={"images/a.png": "/api/v1/media/x"},
    )
    cache.put("h1", "mineru", result)
    got = cache.get("h1", "mineru")
    assert got is not None
    assert got.text == "hello"
    assert got.structured == {"pages": [1]}
    assert got.tier_used == "standard"
    assert got.cached is True
    assert got.assets == {"images/a.png": "/api/v1/media/x"}
    assert cache.get("h1", "local") is None


def test_broken_db_never_raises() -> None:
    class Boom:
        def get_connection(self):
            raise RuntimeError("down")

    cache = SqliteParseCache(Boom())
    cache.put("h", "local", ParseResult(text="t", engine_used="local"))
    assert cache.get("h", "local") is None
