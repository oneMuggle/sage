"""Tests for scripts/update_builtin_models.py.

The script is loaded by path (it is not an importable package module), then its
pure functions and the offline --check CLI path are exercised directly.
"""

import http.client
import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "update_builtin_models.py"
_NOW = "2026-10-28T00:00:00.000000Z"
_TIERS = ("fast", "balanced", "powerful")


def _load():
    spec = importlib.util.spec_from_file_location("update_builtin_models", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


MOD = _load()


def _valid_data(count=51):
    """Build a syntactically valid builtin.json document (17 models per tier)."""
    models = []
    for index in range(count):
        models.append(
            {
                "provider": f"provider-{index % 2}",
                "model_id": f"model-{index}",
                "tier": _TIERS[index % 3],
                "native": 128000,
                "price": {
                    "input_per_million": "1.00",
                    "output_per_million": "2.00",
                },
                "source_updated_at": _NOW,
                "pricing_scope": "test",
            }
        )
    return {
        "version": "2.0.0",
        "source": "test",
        "generated_at": _NOW,
        "models": models,
    }


class TestValidate:
    def test_valid_document_has_no_errors(self):
        assert MOD.validate(_valid_data()) == []

    def test_detects_invalid_tier(self):
        data = _valid_data()
        data["models"][5]["tier"] = "ultra"
        errors = MOD.validate(data)
        assert any("models[5]" in error and "ultra" in error for error in errors)

    def test_detects_duplicate_provider_model_id(self):
        data = _valid_data()
        data["models"][1]["provider"] = data["models"][0]["provider"]
        data["models"][1]["model_id"] = data["models"][0]["model_id"]
        errors = MOD.validate(data)
        assert any("duplicate" in error.lower() for error in errors)

    def test_detects_missing_model_id(self):
        data = _valid_data()
        del data["models"][7]["model_id"]
        errors = MOD.validate(data)
        assert any("models[7]" in error and "model_id" in error for error in errors)

    def test_detects_non_string_price_value(self):
        data = _valid_data()
        data["models"][9]["price"]["input_per_million"] = 1.0
        errors = MOD.validate(data)
        assert any("models[9]" in error and "price" in error for error in errors)


class TestHeuristicTier:
    def test_powerful_by_token(self):
        assert MOD.heuristic_tier("anthropic/claude-opus-4", None, None) == "powerful"

    def test_powerful_by_output_price(self):
        assert MOD.heuristic_tier("vendor/plain-model", 0.5, 15.0) == "powerful"

    def test_fast_by_token(self):
        assert MOD.heuristic_tier("google/gemini-2.0-flash", 0.1, 0.4) == "fast"

    def test_fast_by_output_price(self):
        assert MOD.heuristic_tier("vendor/plain-model", 0.1, 1.0) == "fast"

    def test_balanced_fallback(self):
        assert MOD.heuristic_tier("vendor/plain-model", 3.0, 5.0) == "balanced"

    def test_price_rule_short_circuits_before_fast_token(self):
        # Output price >= 15 wins before the "mini" token is considered.
        assert MOD.heuristic_tier("vendor/tiny-mini", 1.0, 20.0) == "powerful"

    def test_is_deterministic(self):
        first = MOD.heuristic_tier("anthropic/claude-sonnet-4", 3.0, 15.0)
        second = MOD.heuristic_tier("anthropic/claude-sonnet-4", 3.0, 15.0)
        assert first == second == "powerful"

    def test_token_tables_are_populated(self):
        assert "opus" in MOD._POWERFUL_TOKENS
        assert "flash" in MOD._FAST_TOKENS


class TestParseOpenrouter:
    def test_maps_fields_and_converts_prices(self):
        payload = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
                }
            ]
        }
        models = MOD.parse_openrouter(payload, _NOW)
        assert len(models) == 1
        model = models[0]
        assert model["provider"] == "openai"
        # 裸 slug, 与 sources.py::_split_model_id 一致, 才能命中 builtin.json 的既有行
        assert model["model_id"] == "gpt-4o"
        assert model["tier"] == "balanced"
        assert model["native"] == 128000
        assert model["price"] == {
            "input_per_million": "2.50",
            "output_per_million": "10.00",
        }
        assert model["source_updated_at"] == _NOW
        assert model["pricing_scope"] == "openrouter"

    def test_slashless_id_falls_back_to_openrouter_provider(self):
        payload = {"data": [{"id": "bare-model", "context_length": 4096}]}
        model = MOD.parse_openrouter(payload, _NOW)[0]
        assert model["provider"] == "openrouter"
        assert model["model_id"] == "bare-model"

    def test_omits_price_when_pricing_missing(self):
        payload = {
            "data": [
                {
                    "id": "meta-llama/llama-3.1-8b-instruct",
                    "context_length": 8000,
                }
            ]
        }
        model = MOD.parse_openrouter(payload, _NOW)[0]
        assert "price" not in model
        assert model["tier"] == "fast"

    def test_omits_price_when_value_not_numeric(self):
        payload = {
            "data": [
                {
                    "id": "vendor/model",
                    "context_length": 1000,
                    "pricing": {"prompt": "n/a", "completion": "0.001"},
                }
            ]
        }
        model = MOD.parse_openrouter(payload, _NOW)[0]
        assert "price" not in model

    def test_skips_blank_id_and_bad_context_length(self):
        payload = {
            "data": [
                {"id": "", "context_length": 1000, "pricing": {}},
                {"id": "vendor/no-context", "pricing": {}},
                {"id": "vendor/zero-context", "context_length": 0, "pricing": {}},
                {"id": "vendor/ok", "context_length": 1000, "pricing": {}},
            ]
        }
        models = MOD.parse_openrouter(payload, _NOW)
        assert [model["model_id"] for model in models] == ["ok"]


class TestMergeModels:
    def test_existing_entries_are_kept_verbatim(self):
        existing = [
            {"provider": "vendor", "model_id": "tiny-model", "tier": "powerful", "native": 1}
        ]
        snapshot = [dict(model) for model in existing]
        fetched = [
            {"provider": "vendor", "model_id": "tiny-model", "tier": "fast", "native": 999},
            {"provider": "zeta", "model_id": "z-model", "tier": "balanced"},
            {"provider": "alpha", "model_id": "a-model", "tier": "fast"},
        ]

        merged, stats = MOD.merge_models(existing, fetched)

        assert stats == {"added": 2, "kept": 1}
        assert merged[0] is existing[0]
        assert merged[0] == snapshot[0]
        assert existing == snapshot
        assert [(model["provider"], model["model_id"]) for model in merged] == [
            ("vendor", "tiny-model"),
            ("alpha", "a-model"),
            ("zeta", "z-model"),
        ]

    def test_fetched_prefixed_id_dedupes_against_bare_existing_row(self):
        """OpenRouter 给 'openai/gpt-4o', builtin.json 存 ('openai','gpt-4o')。

        合并键必须命中, 否则每次刷新都会把 55 条手工条目全部复制一遍。
        """
        existing = [{"provider": "openai", "model_id": "gpt-4o", "tier": "balanced"}]
        fetched = MOD.parse_openrouter(
            {"data": [{"id": "openai/gpt-4o", "context_length": 128000}]}, _NOW
        )

        merged, stats = MOD.merge_models(existing, fetched)

        assert stats == {"added": 0, "kept": 1}
        assert merged == existing


class TestMainCheck:
    def test_real_builtin_json_is_valid(self):
        assert MOD.main(["--check"]) == 0

    def test_check_reports_bad_data_and_returns_one(self, tmp_path, monkeypatch):
        data = _valid_data()
        data["models"][0]["tier"] = "ultra"
        bad_path = tmp_path / "builtin.json"
        bad_path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(MOD, "BUILTIN_PATH", bad_path)

        assert MOD.main(["--check"]) == 1

    def test_check_wins_over_dry_run_and_stays_offline(self, monkeypatch):
        def _fail(*args, **kwargs):
            raise AssertionError("--check must not fetch OpenRouter")

        monkeypatch.setattr(MOD, "fetch_openrouter", _fail)

        assert MOD.main(["--check", "--dry-run"]) == 0


class TestRefreshWrite:
    """写盘路径: 这是唯一能损坏 55 条手工数据的代码, 必须逐条钉住。"""

    _NEW_ENTRY = {"id": "vendor-brand-new/new-model", "context_length": 4096}

    def _prepare(self, tmp_path, monkeypatch, payload):
        path = tmp_path / "builtin.json"
        data = _valid_data()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        monkeypatch.setattr(MOD, "BUILTIN_PATH", path)
        monkeypatch.setattr(MOD, "fetch_openrouter", lambda *args, **kwargs: payload)
        return path, data

    def test_appends_new_model_and_keeps_existing_rows_intact(self, tmp_path, monkeypatch):
        path, data = self._prepare(tmp_path, monkeypatch, {"data": [self._NEW_ENTRY]})

        assert MOD.main([]) == 0

        written = json.loads(path.read_text(encoding="utf-8"))
        written_by_key = {(m["provider"], m["model_id"]): m for m in written["models"]}
        for row in data["models"]:
            assert written_by_key[(row["provider"], row["model_id"])] == row
        assert ("vendor-brand-new", "new-model") in written_by_key
        assert len(written["models"]) == len(data["models"]) + 1

    def test_write_is_deterministic_and_bumps_version(self, tmp_path, monkeypatch):
        path, data = self._prepare(tmp_path, monkeypatch, {"data": [self._NEW_ENTRY]})

        assert MOD.main([]) == 0

        raw = path.read_text(encoding="utf-8")
        written = json.loads(raw)
        keys = [(m["provider"], m["model_id"]) for m in written["models"]]
        assert keys == sorted(keys)
        assert written["version"] == "2.1.0"
        assert MOD._GENERATED_AT_RE.match(written["generated_at"])
        assert raw.endswith("\n")
        assert not path.with_name("builtin.json.tmp").exists()
        assert written["source"] == data["source"]

    def test_nothing_added_leaves_file_byte_identical(self, tmp_path, monkeypatch):
        path, _ = self._prepare(tmp_path, monkeypatch, {"data": []})
        original = path.read_bytes()

        assert MOD.main([]) == 0

        assert path.read_bytes() == original

    def test_dry_run_reports_but_never_writes(self, tmp_path, monkeypatch, capsys):
        path, _ = self._prepare(tmp_path, monkeypatch, {"data": [self._NEW_ENTRY]})
        original = path.read_bytes()

        assert MOD.main(["--dry-run"]) == 0

        assert path.read_bytes() == original
        assert "would write" in capsys.readouterr().out

    def test_dry_run_runs_the_same_validation_gate(self, tmp_path, monkeypatch):
        path = tmp_path / "builtin.json"
        data = _valid_data()
        # 合并会原样保留的手改错误: 启发式永远不会产出 'ultra', 只能靠校验拦住。
        data["models"][0]["tier"] = "ultra"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(MOD, "BUILTIN_PATH", path)
        monkeypatch.setattr(
            MOD, "fetch_openrouter", lambda *args, **kwargs: {"data": [self._NEW_ENTRY]}
        )

        assert MOD.main(["--dry-run"]) == 1
        assert path.read_text(encoding="utf-8") == json.dumps(data)

    def test_fetch_http_exception_is_a_warning_not_a_crash(self, tmp_path, monkeypatch, capsys):
        path, _ = self._prepare(tmp_path, monkeypatch, {"data": []})
        original = path.read_bytes()

        def _boom(*args, **kwargs):
            raise http.client.IncompleteRead(b"")

        monkeypatch.setattr(MOD, "fetch_openrouter", _boom)

        assert MOD.main([]) == 0
        assert path.read_bytes() == original
        assert "warning:" in capsys.readouterr().err
