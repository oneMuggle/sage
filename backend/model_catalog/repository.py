"""SQLite catalog storage using the application's connection and shared RLock."""
import json
from contextlib import contextmanager
from typing import List, Optional
from uuid import uuid4

from backend.data.database import _SQLITE_LOCK, Database

from .resolver import resolve_layers
from .schemas import (
    CandidateModel,
    ContextLimits,
    EffectiveModel,
    EndpointKey,
    EndpointPatch,
    LayerValues,
    ModelKey,
    OverrideRecord,
    Price,
    ProbeRecord,
    SnapshotDiff,
)
from .snapshots import (
    FIELDS,
    CatalogConflict,
    CatalogNotFoundError,
    canonical_json,
    digest,
    field_value,
    merge_fields,
    selected_fields,
    utc_now,
)


class CatalogRepository:
    def __init__(self, db: Database):
        self.db = db

    @contextmanager
    def _transaction(self):
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            # Never commit or roll back a transaction owned by another repository.
            if conn.in_transaction:
                raise RuntimeError("catalog requires an idle database connection")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _identity(record):
        return (
            record.model_key.provider,
            record.model_key.model_id,
            record.source,
            record.pricing_scope,
        )

    def _entry(self, conn, record):
        row = conn.execute(
            "SELECT data, revision FROM model_catalog_entries WHERE "
            "provider=? AND model_id=? AND source=? AND pricing_scope=?",
            self._identity(record),
        ).fetchone()
        return (
            (CandidateModel.model_validate_json(row["data"]), row["revision"]) if row else (None, 0)
        )

    def bind(self, endpoint: EndpointKey, model_key: ModelKey, pricing_scope: str) -> None:
        if not isinstance(pricing_scope, str) or not pricing_scope.strip():
            raise ValueError("pricing_scope must not be blank")
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO model_catalog_bindings VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint_id, model_id) DO UPDATE SET provider=excluded.provider, "
                "catalog_model_id=excluded.catalog_model_id, pricing_scope=excluded.pricing_scope, "
                "updated_at=excluded.updated_at",
                (
                    endpoint.endpoint_id,
                    endpoint.model_id,
                    model_key.provider,
                    model_key.model_id,
                    pricing_scope,
                    utc_now(),
                ),
            )

    def get_override(self, endpoint: EndpointKey) -> OverrideRecord:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            row = conn.execute(
                "SELECT data, revision FROM model_catalog_overrides "
                "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone()
            if row:
                return OverrideRecord(
                    patch=EndpointPatch.model_validate_json(row["data"]),
                    revision=row["revision"],
                )
            generation = conn.execute(
                "SELECT revision FROM model_catalog_override_generations "
                "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone()
            return OverrideRecord(revision=generation["revision"] if generation else 0)

    def delete_override(self, endpoint: EndpointKey, expected_revision: int) -> int:
        """Delete an override while retaining a monotonic revision tombstone."""
        with self._transaction() as conn:
            current = self.get_override(endpoint)
            if current.revision == 0 or not conn.execute(
                "SELECT 1 FROM model_catalog_overrides WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone():
                raise CatalogNotFoundError("no override to delete")
            if current.revision != expected_revision:
                raise CatalogConflict("override revision changed")
            revision = current.revision + 1
            conn.execute(
                "DELETE FROM model_catalog_overrides "
                "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            )
            conn.execute(
                "INSERT INTO model_catalog_override_generations VALUES (?, ?, ?, ?) "
                "ON CONFLICT(endpoint_id, model_id) DO UPDATE SET revision=excluded.revision, "
                "updated_at=excluded.updated_at",
                (endpoint.endpoint_id, endpoint.model_id, revision, utc_now()),
            )
            return revision

    def set_override(self, endpoint: EndpointKey, patch: dict, expected_revision: int) -> int:
        validated = EndpointPatch.model_validate(patch)
        with self._transaction() as conn:
            current = self.get_override(endpoint)
            if current.revision != expected_revision:
                raise CatalogConflict("override revision changed")
            data = self._merge_patch(current.patch, validated, clear=True)
            revision = current.revision + 1
            conn.execute(
                "INSERT INTO model_catalog_overrides VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint_id, model_id) DO UPDATE SET data=excluded.data, "
                "revision=excluded.revision, updated_at=excluded.updated_at",
                (
                    endpoint.endpoint_id,
                    endpoint.model_id,
                    data.model_dump_json(),
                    revision,
                    utc_now(),
                ),
            )
            conn.execute(
                "INSERT INTO model_catalog_override_generations VALUES (?, ?, ?, ?) "
                "ON CONFLICT(endpoint_id, model_id) DO UPDATE SET revision=excluded.revision, "
                "updated_at=excluded.updated_at",
                (endpoint.endpoint_id, endpoint.model_id, revision, utc_now()),
            )
            return revision

    @staticmethod
    def _merge_patch(current, patch, *, clear=False):
        old = current.model_dump(mode="json")
        incoming = patch.model_dump(mode="json", exclude_unset=True)
        price = {
            **old["price"],
            **{k: v for k, v in incoming.get("price", {}).items() if clear or v is not None},
        }
        return EndpointPatch.model_validate(
            {**old, **{k: v for k, v in incoming.items() if clear or v is not None}, "price": price}
        )

    def save_probe(
        self,
        endpoint: EndpointKey,
        patch: dict,
        *,
        adapter: str,
        status: str,
        error: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        record = ProbeRecord(
            patch=EndpointPatch.model_validate(patch),
            adapter=adapter,
            status=status,
            observed_at=utc_now(),
            error=error,
            base_url=base_url,
        )
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT data, effective_data FROM model_catalog_probes "
                "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone()
            if row:
                old_probe = ProbeRecord.model_validate_json(row[0])
                url_changed = (
                    base_url is not None
                    and old_probe.base_url is not None
                    and old_probe.base_url != base_url
                )
            else:
                url_changed = False
            # If endpoint URL changed, old effective data is stale — reset
            if url_changed:
                effective = EndpointPatch.model_validate(patch) if record.status == "success" else EndpointPatch()
            else:
                effective = EndpointPatch.model_validate_json(row[1]) if row else EndpointPatch()
                if record.status == "success":
                    effective = self._merge_patch(effective, record.patch)
            conn.execute(
                "INSERT INTO model_catalog_probes VALUES (?, ?, ?, ?) "
                "ON CONFLICT(endpoint_id, model_id) DO UPDATE SET "
                "data=excluded.data, effective_data=excluded.effective_data",
                (
                    endpoint.endpoint_id,
                    endpoint.model_id,
                    record.model_dump_json(),
                    effective.model_dump_json(),
                ),
            )

    def get_probe(self, endpoint: EndpointKey) -> Optional[ProbeRecord]:
        with _SQLITE_LOCK:
            row = (
                self.db.get_connection()
                .execute(
                    "SELECT data FROM model_catalog_probes WHERE endpoint_id=? AND model_id=?",
                    (endpoint.endpoint_id, endpoint.model_id),
                )
                .fetchone()
            )
            return ProbeRecord.model_validate_json(row[0]) if row else None

    @staticmethod
    def _layer(patch, source, revision=0, price=None):
        return LayerValues(
            limits=ContextLimits(native=patch.native, service=getattr(patch, "service", None)),
            price=patch.price if price is None else price,
            source=source,
            revision=revision,
        )

    def resolve(self, endpoint: EndpointKey) -> EffectiveModel:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            override = self.get_override(endpoint)
            layers = [self._layer(override.patch, "user_override", override.revision)]
            probe = conn.execute(
                "SELECT effective_data FROM model_catalog_probes "
                "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone()
            if probe:
                layers.append(self._layer(EndpointPatch.model_validate_json(probe[0]), "probe"))
            binding = conn.execute(
                "SELECT * FROM model_catalog_bindings " "WHERE endpoint_id=? AND model_id=?",
                (endpoint.endpoint_id, endpoint.model_id),
            ).fetchone()
            if binding:
                rows = conn.execute(
                    "SELECT * FROM model_catalog_entries WHERE provider=? AND model_id=? "
                    "ORDER BY (source='builtin') ASC, updated_at DESC, source, pricing_scope",
                    (binding["provider"], binding["catalog_model_id"]),
                ).fetchall()
                for row in rows:
                    record = CandidateModel.model_validate_json(row["data"])
                    price = (
                        record.price
                        if record.pricing_scope == binding["pricing_scope"]
                        else Price()
                    )
                    layers.append(self._layer(record, record.source, row["revision"], price))
            return resolve_layers(layers)

    def stage(self, records: List[CandidateModel], source: str) -> str:
        records = [CandidateModel.model_validate(r) for r in records]
        if (
            not isinstance(source, str)
            or not source.strip()
            or any(r.source != source for r in records)
        ):
            raise ValueError("snapshot source must match every candidate source")
        if len({self._identity(r) for r in records}) != len(records):
            raise ValueError("duplicate candidate identity")
        with self._transaction() as conn:
            return self._stage(conn, records, source)

    def _stage(self, conn, records, source, clear_fields=()):
        snapshot_id = uuid4().hex
        conn.execute(
            "INSERT INTO model_catalog_snapshots VALUES (?, ?, ?, ?)",
            (snapshot_id, source, digest(records), utc_now()),
        )
        for record in records:
            before, revision = self._entry(conn, record)
            conn.execute(
                "INSERT INTO model_catalog_snapshot_items "
                "(id, snapshot_id, candidate, base_revision, before_data, clear_fields) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uuid4().hex,
                    snapshot_id,
                    record.model_dump_json(),
                    revision,
                    before.model_dump_json() if before else None,
                    canonical_json(clear_fields),
                ),
            )
        return snapshot_id

    @staticmethod
    def _item(conn, snapshot_id, item_id):
        row = conn.execute(
            "SELECT * FROM model_catalog_snapshot_items WHERE snapshot_id=? AND id=?",
            (snapshot_id, item_id),
        ).fetchone()
        if row is None:
            raise KeyError("snapshot item not found")
        return row

    def diff(self, snapshot_id: str) -> List[SnapshotDiff]:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            if not conn.execute(
                "SELECT 1 FROM model_catalog_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone():
                raise KeyError("snapshot not found")
            rows = conn.execute(
                "SELECT * FROM model_catalog_snapshot_items WHERE snapshot_id=? ORDER BY rowid",
                (snapshot_id,),
            ).fetchall()
            return [self._diff_item(conn, row) for row in rows]

    def _diff_item(self, conn, row):
        candidate = CandidateModel.model_validate_json(row["candidate"])
        before = (
            CandidateModel.model_validate_json(row["before_data"]) if row["before_data"] else None
        )
        clear_fields = json.loads(row["clear_fields"])
        _, revision = self._entry(conn, candidate)
        merged = merge_fields(before, candidate, list(FIELDS), clear_fields)
        classification = (
            "new" if before is None else ("unchanged" if merged == before else "updated")
        )
        if row["status"] == "pending" and revision != row["base_revision"]:
            classification = "conflict"
        return SnapshotDiff(
            id=row["id"],
            base_revision=row["base_revision"],
            before=before,
            after=merged,
            candidate=candidate,
            clear_fields=clear_fields,
            classification=classification,
            status=row["status"],
        )

    def apply(
        self, snapshot_id: str, item_id: str, fields: List[str], expected_revision: int
    ) -> None:
        fields = selected_fields(fields)
        with self._transaction() as conn:
            row = self._item(conn, snapshot_id, item_id)
            after = CandidateModel.model_validate_json(row["candidate"])
            before, revision = self._entry(conn, after)
            if (
                row["status"] != "pending"
                or expected_revision != row["base_revision"]
                or revision != expected_revision
            ):
                raise CatalogConflict("snapshot item or source revision changed")
            merged = merge_fields(before, after, fields, json.loads(row["clear_fields"]))
            conn.execute(
                "INSERT INTO model_catalog_entries VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(provider, model_id, source, pricing_scope) DO UPDATE SET "
                "data=excluded.data, revision=excluded.revision, updated_at=excluded.updated_at",
                (*self._identity(after), merged.model_dump_json(), revision + 1, utc_now()),
            )
            conn.execute(
                "UPDATE model_catalog_snapshot_items SET status='applied', reviewed_at=?, "
                "applied_before=?, applied_fields=? WHERE id=?",
                (
                    utc_now(),
                    before.model_dump_json() if before else None,
                    canonical_json(fields),
                    item_id,
                ),
            )

    def ignore(self, snapshot_id: str, item_id: str) -> None:
        with self._transaction() as conn:
            row = self._item(conn, snapshot_id, item_id)
            if row["status"] != "pending":
                raise CatalogConflict("snapshot item is already reviewed")
            conn.execute(
                "UPDATE model_catalog_snapshot_items SET status='ignored', reviewed_at=? WHERE id=?",
                (utc_now(), item_id),
            )

    def revert(self, snapshot_id: str, item_id: str) -> str:
        """Stage an inverse review, preserving unrelated fields and user overrides."""
        with self._transaction() as conn:
            row = self._item(conn, snapshot_id, item_id)
            if row["status"] != "applied":
                raise CatalogConflict("only applied items can be reverted")
            original = CandidateModel.model_validate_json(row["candidate"])
            current, _ = self._entry(conn, original)
            previous = (
                CandidateModel.model_validate_json(row["applied_before"])
                if row["applied_before"]
                else (
                    CandidateModel(
                        model_key=original.model_key,
                        source=original.source,
                        pricing_scope=original.pricing_scope,
                    )
                )
            )
            fields = json.loads(row["applied_fields"])
            previous_dump = previous.model_dump(mode="json")
            clears = [f for f in fields if field_value(previous_dump, f) is None]
            if previous and previous.source_updated_at is None:
                clears.append("source_updated_at")
            inverse = merge_fields(current, previous, fields, clears)
            return self._stage(conn, [inverse], inverse.source, clears)
