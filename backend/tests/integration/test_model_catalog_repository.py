"""Real SQLite coverage for catalog persistence and transactional review."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from backend.data.database import Database
from backend.model_catalog import schemas


@pytest.fixture()
def repo(tmp_path):
    from backend.model_catalog.repository import CatalogRepository

    db = Database(str(tmp_path / "catalog.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


def candidate(**patch):
    return schemas.CandidateModel.model_validate(
        {
            "model_key": {"provider": "vendor", "model_id": "exact-Q4"},
            "native": 32000,
            "price": {"input_per_million": "1.25"},
            "source": "custom_json",
            "pricing_scope": "openrouter",
            **patch,
        }
    )


def endpoint(name="one"):
    return schemas.EndpointKey(endpoint_id=name, model_id="exact-Q4")


def publish(repo, record=None, fields=None):
    record = record or candidate()
    snap = repo.stage([record], record.source)
    item = repo.diff(snap)[0]
    repo.apply(snap, item.id, fields or ["native", "price"], item.base_revision)
    return snap, item


@pytest.mark.parametrize(
    "timestamp", ["yesterday", "2026-09-15T12:00:00", "2026-09-15T12:00:00+08:00"]
)
def test_candidate_rejects_non_utc_rfc3339_time(timestamp):
    with pytest.raises(ValueError, match="UTC RFC3339"):
        candidate(source_updated_at=timestamp)


def test_missing_source_time_preserves_prior_timestamp(repo):
    publish(repo, candidate(source_updated_at="2026-09-15T12:00:00Z"))
    publish(repo, candidate(native=123))
    snap = repo.stage([candidate()], "custom_json")
    assert repo.diff(snap)[0].before.source_updated_at == "2026-09-15T12:00:00Z"


def test_diff_after_is_merged_preview_and_candidate_is_preserved(repo):
    publish(repo)
    snap = repo.stage([candidate(native=64000, price={})], "custom_json")
    item = repo.diff(snap)[0]
    assert item.after.native == 64000
    assert item.after.price.input_per_million == Decimal("1.25")
    assert item.candidate.price.input_per_million is None
    assert item.clear_fields == []
    repo.apply(snap, item.id, ["native", "price"], item.base_revision)
    next_snap = repo.stage([candidate(native=64000, price={})], "custom_json")
    unchanged = repo.diff(next_snap)[0]
    assert unchanged.classification == "unchanged"
    assert unchanged.before == unchanged.after
    assert unchanged.before == item.after


@pytest.mark.parametrize("previous_time", [None, "2026-09-14T12:00:00Z"])
def test_revert_restores_source_timestamp_including_unknown(repo, previous_time):
    publish(repo, candidate(source_updated_at=previous_time))
    snap, item = publish(repo, candidate(native=64000, source_updated_at="2026-09-15T12:00:00Z"))
    rollback = repo.revert(snap, item.id)
    preview = repo.diff(rollback)[0]
    assert preview.after.source_updated_at == previous_time
    assert ("source_updated_at" in preview.clear_fields) == (previous_time is None)
    repo.apply(rollback, preview.id, ["native"], preview.base_revision)
    check = repo.stage([candidate()], "custom_json")
    assert repo.diff(check)[0].before.source_updated_at == previous_time
    assert repo.diff(check)[0].before.native == 32000


def test_contracts_exist():
    assert hasattr(schemas, "CandidateModel")
    assert hasattr(schemas, "SnapshotDiff")


def test_init_idempotent_restart_and_scoped_prices(repo):
    publish(repo)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    repo.bind(endpoint("other"), candidate().model_key, "direct")
    repo.db.init_db()
    repo.db.close()
    assert repo.resolve(endpoint()).price.input_per_million == Decimal("1.25")
    other = repo.resolve(endpoint("other"))
    assert other.price.input_per_million is None
    assert other.limits.native == 32000
    assert repo.resolve(endpoint("unbound")).limits.native is None


def test_stale_review_rejected(repo):
    from backend.model_catalog.repository import CatalogConflict

    snap, item = publish(repo)
    with pytest.raises(CatalogConflict):
        repo.apply(snap, item.id, ["native"], item.base_revision)


def test_parallel_snapshots_have_single_winner(repo):
    from backend.model_catalog.repository import CatalogConflict, CatalogRepository

    ids = [repo.stage([candidate(native=n)], "custom_json") for n in (100, 200)]
    other_db = Database(repo.db.db_path)
    other = CatalogRepository(other_db)

    def review(pair):
        target, snap = pair
        item = target.diff(snap)[0]
        try:
            target.apply(snap, item.id, ["native"], item.base_revision)
            return "applied"
        except CatalogConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(review, zip((repo, other), ids, strict=False))) == [
                "applied",
                "conflict",
            ]
    finally:
        other_db.close()


def test_partial_apply_and_missing_fields_preserve_values(repo):
    publish(repo)
    snap, _ = publish(repo, candidate(native=64000, price={}), ["native", "price"])
    assert repo.diff(snap)[0].status == "applied"
    next_snap = repo.stage([candidate(native=128000, architecture="new")], "custom_json")
    item = repo.diff(next_snap)[0]
    repo.apply(next_snap, item.id, ["architecture"], item.base_revision)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    result = repo.resolve(endpoint())
    assert result.limits.native == 64000
    assert result.price.input_per_million == Decimal("1.25")


def test_override_cas_and_probe_failure_preserve_user_and_last_success(repo):
    from backend.model_catalog.repository import CatalogConflict

    publish(repo)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    assert repo.set_override(endpoint(), {"price": {"input_per_million": "0"}}, 0) == 1
    with pytest.raises(CatalogConflict):
        repo.set_override(endpoint(), {"native": 1}, 0)
    repo.save_probe(endpoint(), {"service": 8000}, adapter="ollama", status="success")
    repo.save_probe(endpoint(), {}, adapter="ollama", status="failed", error="unavailable")
    assert repo.get_probe(endpoint()).status == "failed"
    publish(repo, candidate(native=64000))
    result = repo.resolve(endpoint())
    assert result.limits.service == 8000
    assert result.limits.native == 64000
    assert result.price.input_per_million == 0
    assert repo.get_override(endpoint()).revision == 1
    repo.db.close()
    assert repo.resolve(endpoint()) == result


def test_ignore_does_not_change_catalog_and_terminal_status_is_guarded(repo):
    from backend.model_catalog.repository import CatalogConflict

    snap = repo.stage([candidate()], "custom_json")
    item = repo.diff(snap)[0]
    repo.ignore(snap, item.id)
    assert repo.diff(snap)[0].status == "ignored"
    with pytest.raises(CatalogConflict):
        repo.apply(snap, item.id, ["native"], 0)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    assert repo.resolve(endpoint()).limits.native is None


def test_transaction_rolls_back_entry_when_review_update_fails(repo):
    snap = repo.stage([candidate()], "custom_json")
    item = repo.diff(snap)[0]
    conn = repo.db.get_connection()
    conn.execute(
        "CREATE TRIGGER fail_review BEFORE UPDATE ON model_catalog_snapshot_items "
        "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
        repo.apply(snap, item.id, ["native"], 0)
    assert conn.execute("SELECT COUNT(*) FROM model_catalog_entries").fetchone()[0] == 0
    assert repo.diff(snap)[0].status == "pending"


def test_revert_is_pending_and_restores_only_applied_fields(repo):
    publish(repo)
    snap, item = publish(repo, candidate(native=64000), ["native"])
    rollback = repo.revert(snap, item.id)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    assert repo.resolve(endpoint()).limits.native == 64000
    reverted = repo.diff(rollback)[0]
    assert reverted.status == "pending"
    repo.apply(rollback, reverted.id, ["native"], reverted.base_revision)
    assert repo.resolve(endpoint()).limits.native == 32000


def test_revert_new_field_restores_unknown(repo):
    snap, item = publish(repo, fields=["native"])
    rollback = repo.revert(snap, item.id)
    reverted = repo.diff(rollback)[0]
    repo.apply(rollback, reverted.id, ["native"], reverted.base_revision)
    repo.bind(endpoint(), candidate().model_key, "openrouter")
    assert repo.resolve(endpoint()).limits.native is None


def test_diff_classification_and_source_scope_isolation(repo):
    snap, _ = publish(repo)
    unchanged = repo.stage([candidate()], "custom_json")
    assert repo.diff(unchanged)[0].classification == "unchanged"
    stale = repo.stage([candidate(native=42)], "custom_json")
    publish(repo, candidate(native=99))
    assert repo.diff(stale)[0].classification == "conflict"
    publish(
        repo,
        candidate(
            source="builtin", native=10, pricing_scope="direct", price={"input_per_million": "9"}
        ),
    )
    repo.bind(endpoint(), candidate().model_key, "direct")
    assert repo.resolve(endpoint()).limits.native == 99
    assert repo.resolve(endpoint()).price.input_per_million == 9
    assert repo.diff(snap)[0].before is None


@pytest.mark.parametrize(
    "patch", [{"native": -1}, {"api_key": "not-allowed"}, {"price": {"input_per_million": "-1"}}]
)
def test_invalid_override_is_atomic(repo, patch):
    with pytest.raises(ValueError, match="validation error"):
        repo.set_override(endpoint(), patch, 0)
    assert repo.get_override(endpoint()).revision == 0


def test_stage_validates_entire_batch_and_source(repo):
    with pytest.raises(ValueError, match="snapshot source"):
        repo.stage([candidate()], "different")
    assert (
        repo.db.get_connection()
        .execute("SELECT COUNT(*) FROM model_catalog_snapshots")
        .fetchone()[0]
        == 0
    )


def test_unknown_review_fields_and_missing_item_are_rejected(repo):
    snap = repo.stage([candidate()], "custom_json")
    item = repo.diff(snap)[0]
    with pytest.raises(ValueError, match="catalog value fields"):
        repo.apply(snap, item.id, ["source"], 0)
    with pytest.raises(KeyError):
        repo.ignore(snap, "missing")
    assert repo.diff(snap)[0].status == "pending"
