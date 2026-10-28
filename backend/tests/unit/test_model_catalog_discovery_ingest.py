"""Unit coverage for discovered-model -> catalog-binding reconciliation (Task 12).

Routing candidates come from ``model_catalog_bindings``; before Task 12 nothing
in production ever called ``CatalogRepository.bind()``.  These tests prove the
reconcile path creates bindings (and therefore routing candidates) while never
inventing providers or touching user overrides.
"""

import pytest

from backend.data.database import Database
from backend.model_catalog.discovery_ingest import reconcile_endpoint_bindings
from backend.model_catalog.schemas import CandidateModel, EndpointKey
from backend.model_catalog.snapshots import FIELDS


@pytest.fixture()
def repo(tmp_path):
    from backend.model_catalog.repository import CatalogRepository

    db = Database(str(tmp_path / "catalog.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


def _publish(
    repo,
    provider="openai",
    model_id="gpt-4o",
    pricing_scope="openai",
    source="builtin",
):
    """Stage + apply one catalog entry through the real review pipeline."""
    record = CandidateModel.model_validate(
        {
            "model_key": {"provider": provider, "model_id": model_id},
            "tier": "balanced",
            "native": 128000,
            "price": {"input_per_million": "2.5"},
            "source": source,
            "pricing_scope": pricing_scope,
        }
    )
    snap = repo.stage([record], source)
    item = repo.diff(snap)[0]
    repo.apply(snap, item.id, list(FIELDS), item.base_revision)
    return record


def _settings(*endpoints):
    return {"endpoints": list(endpoints)}


def _bindings(repo):
    return [
        tuple(row)
        for row in repo.db.get_connection()
        .execute(
            "SELECT endpoint_id, model_id, provider, catalog_model_id, pricing_scope "
            "FROM model_catalog_bindings ORDER BY endpoint_id, model_id"
        )
        .fetchall()
    ]


def _discovered(*model_ids):
    return [
        {"id": model_id, "capabilities": ["chat"], "endpointId": "ep-1"}
        for model_id in model_ids
    ]


def test_binds_discovered_model_and_routing_gets_a_candidate(repo):
    """Acceptance: a discovered builtin model makes list_effective_models non-empty."""
    _publish(repo)

    stats = reconcile_endpoint_bindings(
        repo, _settings({"id": "ep-1", "discoveredModels": _discovered("gpt-4o")})
    )

    assert stats == {"bound": 1, "skipped": 0}
    assert _bindings(repo) == [("ep-1", "gpt-4o", "openai", "gpt-4o", "openai")]

    # The routing engine's candidate source must now resolve the binding.
    effective = repo.list_effective_models(endpoint_id="ep-1")
    assert len(effective) == 1
    assert effective[0].model_key is not None
    assert effective[0].model_key.provider == "openai"
    assert effective[0].model_key.model_id == "gpt-4o"
    assert effective[0].limits.native == 128000


def test_ambiguous_bare_id_is_skipped_without_inventing_a_provider(repo):
    """Two providers for the same bare id must not be guessed (R34a/R34b)."""
    _publish(repo, provider="openai", model_id="gpt-4o", pricing_scope="openai")
    _publish(repo, provider="azure", model_id="gpt-4o", pricing_scope="azure")

    stats = reconcile_endpoint_bindings(
        repo, _settings({"id": "ep-1", "discoveredModels": _discovered("gpt-4o")})
    )

    assert stats == {"bound": 0, "skipped": 1}
    assert _bindings(repo) == []


def test_prefixed_catalog_id_matches_suffix_form(repo):
    """OpenRouter-shaped ids bind the full prefixed model_id (R34b rule 2)."""
    _publish(
        repo,
        provider="meta-llama",
        model_id="meta-llama/llama-3.1-70b-instruct",
        pricing_scope="meta-llama",
    )

    stats = reconcile_endpoint_bindings(
        repo,
        _settings(
            {
                "id": "ep-1",
                "discoveredModels": _discovered("llama-3.1-70b-instruct"),
            }
        ),
    )

    assert stats == {"bound": 1, "skipped": 0}
    assert _bindings(repo) == [
        (
            "ep-1",
            "llama-3.1-70b-instruct",
            "meta-llama",
            "meta-llama/llama-3.1-70b-instruct",
            "meta-llama",
        )
    ]


def test_reconcile_is_idempotent_on_row_count(repo):
    """Running twice must not add binding rows (R34c acceptance is row count)."""
    _publish(repo)
    settings = _settings({"id": "ep-1", "discoveredModels": _discovered("gpt-4o")})

    first = reconcile_endpoint_bindings(repo, settings)
    rows_after_first = _bindings(repo)
    second = reconcile_endpoint_bindings(repo, settings)
    rows_after_second = _bindings(repo)

    assert first == {"bound": 1, "skipped": 0}
    assert second == {"bound": 1, "skipped": 0}
    assert len(rows_after_first) == 1
    assert len(rows_after_second) == 1
    assert rows_after_first == rows_after_second


def test_user_override_is_untouched(repo):
    """Bindings and overrides are independent tables (Task 12 must not touch overrides)."""
    _publish(repo)
    endpoint = EndpointKey(endpoint_id="ep-1", model_id="gpt-4o")
    repo.set_override(endpoint, {"native": 4096}, 0)
    before = repo.get_override(endpoint)

    reconcile_endpoint_bindings(
        repo, _settings({"id": "ep-1", "discoveredModels": _discovered("gpt-4o")})
    )

    after = repo.get_override(endpoint)
    assert after.patch.native == 4096
    assert after.patch == before.patch
    assert after.revision == before.revision == 1


def test_malformed_settings_are_ignored(repo):
    """Bad shapes return zeros instead of raising."""
    assert reconcile_endpoint_bindings(repo, None) == {"bound": 0, "skipped": 0}
    assert reconcile_endpoint_bindings(repo, {"endpoints": "not-a-list"}) == {
        "bound": 0,
        "skipped": 0,
    }
    # Endpoint entry without an id cannot be bound.
    assert reconcile_endpoint_bindings(
        repo,
        _settings({"name": "no-id", "discoveredModels": _discovered("gpt-4o")}),
    ) == {"bound": 0, "skipped": 0}
    # Non-dict endpoint entries and malformed discovered entries are ignored.
    assert reconcile_endpoint_bindings(
        repo,
        _settings(
            "not-a-dict",
            {"id": "ep-1", "discoveredModels": [{"name": "x"}, "bad"]},
        ),
    ) == {"bound": 0, "skipped": 0}
    assert _bindings(repo) == []
