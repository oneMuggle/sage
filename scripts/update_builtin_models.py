"""Refresh backend/builtin.json from OpenRouter's public model list.

Tier heuristics are deterministic (see heuristic_tier); existing entries are never
modified (additive merge). Offline-safe: fetch failure is a warning, not an error.

Usage:
    python scripts/update_builtin_models.py --check     # offline structural check
    python scripts/update_builtin_models.py --dry-run   # fetch + report only
    python scripts/update_builtin_models.py             # fetch + merge + write

Tier rules (heuristic_tier, evaluated in order, first match wins):
    1. model id contains a powerful token (opus, o1, o3, r1, reasoning, ultra,
       405b, 70b, 72b, 34b, 32b) -> powerful
    2. output price >= 15.0 USD/M -> powerful
    3. model id contains a fast token (flash, mini, lite, small, nano, tiny,
       haiku, 8b, 7b, 4b, 3b) -> fast
    4. output price <= 1.0 USD/M and price is known -> fast
    5. otherwise -> balanced

Python 3.8 compatible: intentionally no PEP 604 / PEP 585 annotations.
"""

import argparse
import http.client
import json
import math
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BUILTIN_PATH = Path(__file__).resolve().parent.parent / "backend" / "builtin.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
FETCH_TIMEOUT_S = 15.0

VALID_TIERS = ("fast", "balanced", "powerful")
MIN_MODELS = 50
MIN_MODELS_PER_TIER = 10

_POWERFUL_TOKENS = frozenset(
    {
        "opus",
        "o1",
        "o3",
        "r1",
        "reasoning",
        "ultra",
        "405b",
        "70b",
        "72b",
        "34b",
        "32b",
    }
)
_FAST_TOKENS = frozenset(
    {
        "flash",
        "mini",
        "lite",
        "small",
        "nano",
        "tiny",
        "haiku",
        "8b",
        "7b",
        "4b",
        "3b",
    }
)

_TOKEN_SPLIT_RE = re.compile(r"[-/:]")
_GENERATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def heuristic_tier(model_id, input_per_million, output_per_million):
    """Map a model id and its per-million prices to a routing tier.

    The five rules above are evaluated in order and short-circuit. The function
    depends only on its arguments, so repeated calls always yield the same tier.
    """
    tokens = _tokenize(model_id)
    if tokens & _POWERFUL_TOKENS:
        return "powerful"
    if output_per_million is not None and output_per_million >= 15.0:
        return "powerful"
    if tokens & _FAST_TOKENS:
        return "fast"
    if output_per_million is not None and output_per_million <= 1.0:
        return "fast"
    return "balanced"


def parse_openrouter(payload, now):
    """Convert an OpenRouter /models payload into builtin.json model entries.

    Accepts either the raw response object ({"data": [...]}) or a bare list of
    entries. Invalid entries (non-string/blank id, non-positive integer
    context_length) are skipped rather than raising.

    Split rule mirrors backend/model_catalog/sources.py::_split_model_id so the
    merge key (provider, model_id) matches the rows already in builtin.json:
    ``openai/gpt-4o`` -> provider ``openai``, model_id ``gpt-4o``. A slashless
    id falls back to provider ``openrouter`` with the raw id as model_id.
    """
    if isinstance(payload, dict):
        entries = payload.get("data")
    else:
        entries = payload
    if not isinstance(entries, list):
        return []

    models = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        context_length = entry.get("context_length")
        if isinstance(context_length, bool) or not isinstance(context_length, int):
            continue
        if context_length <= 0:
            continue

        pricing = entry.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {}
        input_price = _per_million(pricing.get("prompt"))
        output_price = _per_million(pricing.get("completion"))
        provider, model_id = _split_openrouter_id(raw_id)

        model = {
            "provider": provider,
            "model_id": model_id,
            # 启发式看完整 id: 'opus'/'70b' 这类词元可能只出现在 vendor 前缀之后。
            "tier": heuristic_tier(raw_id, input_price, output_price),
            "native": context_length,
        }
        if input_price is not None and output_price is not None:
            model["price"] = {
                "input_per_million": f"{input_price:.2f}",
                "output_per_million": f"{output_price:.2f}",
            }
        model["source_updated_at"] = now
        model["pricing_scope"] = "openrouter"
        models.append(model)
    return models


def merge_models(existing, fetched):
    """Additively merge fetched models into existing ones.

    Existing (provider, model_id) entries are preserved as the same objects with
    no field changes. Only unseen fetched keys are appended, sorted by
    (provider, model_id). Returns (merged, {"added": n, "kept": m}).
    """
    merged = list(existing)
    seen = {(model.get("provider"), model.get("model_id")) for model in existing}
    added = []
    for model in fetched:
        key = (model.get("provider"), model.get("model_id"))
        if key in seen:
            continue
        seen.add(key)
        added.append(model)
    added.sort(key=_model_sort_key)
    merged.extend(added)
    return merged, {"added": len(added), "kept": len(existing)}


def validate(data):
    """Return a list of structural errors for a builtin.json document.

    An empty list means the document is valid. Errors name the offending model
    (model_id when available, otherwise its index) so a human can fix it.
    """
    if not isinstance(data, dict):
        return ["root: expected a JSON object"]
    models = data.get("models")
    if not isinstance(models, list):
        return ["models: expected a list"]

    errors = []
    if len(models) < MIN_MODELS:
        errors.append(
            f"models: need at least {MIN_MODELS} entries, got {len(models)}"
        )

    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str) or not _GENERATED_AT_RE.match(generated_at):
        errors.append(
            "generated_at: expected a UTC timestamp like "
            f"2026-10-28T00:00:00.000000Z, got {generated_at!r}"
        )

    tier_counts = {"fast": 0, "balanced": 0, "powerful": 0}
    seen = {}
    for index, model in enumerate(models):
        label = _model_label(index, model)
        if not isinstance(model, dict):
            errors.append(f"{label}: expected an object")
            continue

        provider = model.get("provider")
        model_id = model.get("model_id")
        if not isinstance(provider, str) or not provider.strip():
            errors.append(f"{label}: 'provider' must be a non-empty string")
        if not isinstance(model_id, str) or not model_id.strip():
            errors.append(f"{label}: 'model_id' must be a non-empty string")

        tier = model.get("tier")
        if tier not in VALID_TIERS:
            errors.append(
                f"{label}: invalid tier {tier!r} "
                f"(expected one of {', '.join(VALID_TIERS)})"
            )
        else:
            tier_counts[tier] += 1

        if "native" in model:
            native = model.get("native")
            if isinstance(native, bool) or not isinstance(native, int) or native <= 0:
                errors.append(f"{label}: 'native' must be a positive integer")

        if "price" in model:
            errors.extend(_validate_price(label, model.get("price")))

        if isinstance(provider, str) and isinstance(model_id, str):
            key = (provider, model_id)
            if key in seen:
                errors.append(
                    f"{label}: duplicate (provider, model_id) key, "
                    f"first seen at models[{seen[key]}]"
                )
            else:
                seen[key] = index

    for tier in VALID_TIERS:
        if tier_counts[tier] < MIN_MODELS_PER_TIER:
            errors.append(
                f"tier {tier!r}: only {tier_counts[tier]} models; "
                f"need at least {MIN_MODELS_PER_TIER}"
            )
    return errors


def fetch_openrouter(url=OPENROUTER_URL, timeout=FETCH_TIMEOUT_S):
    """Fetch and decode OpenRouter's public model list. May raise OSError/ValueError."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "sage-builtin-refresh/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body.decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="update_builtin_models",
        description="Refresh backend/builtin.json from OpenRouter's public model list.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate builtin.json offline and exit (never touches the network)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and report changes without writing builtin.json",
    )
    args = parser.parse_args(argv)

    if args.check:
        return _run_check()
    return _run_refresh(dry_run=args.dry_run)


def _run_check():
    try:
        data = _read_builtin()
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {BUILTIN_PATH} ({exc})", file=sys.stderr)
        return 1

    errors = validate(data)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"ok: {len(data['models'])} models")
    return 0


def _run_refresh(dry_run):
    # URLError/socket.timeout → OSError; JSONDecodeError → ValueError;
    # IncompleteRead 等 → HTTPException。三者都只告警、不改盘（R33e）。
    try:
        payload = fetch_openrouter()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        print(
            f"warning: OpenRouter fetch failed ({exc}); builtin.json unchanged",
            file=sys.stderr,
        )
        return 0

    try:
        data = _read_builtin()
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {BUILTIN_PATH} ({exc})", file=sys.stderr)
        return 1

    existing = data.get("models") if isinstance(data, dict) else None
    if not isinstance(existing, list):
        print(f"error: {BUILTIN_PATH} has no 'models' list", file=sys.stderr)
        return 1

    now = _utc_now()
    fetched = parse_openrouter(payload, now)
    merged, stats = merge_models(existing, fetched)
    print(f"added: {stats['added']}, kept: {stats['kept']}")

    candidate = dict(data)
    candidate["models"] = sorted(merged, key=_model_sort_key)
    if stats["added"] > 0:
        candidate["generated_at"] = now
        bumped = _bump_minor(data.get("version"))
        if bumped is not None:
            candidate["version"] = bumped

    # --dry-run 也走同一道校验：否则它会报告一个真实写盘会拒绝的结果。
    errors = validate(candidate)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if stats["added"] == 0:
        print("unchanged")
        return 0

    if dry_run:
        print(f"would write {len(candidate['models'])} models")
        return 0

    _atomic_write_json(BUILTIN_PATH, candidate)
    print(f"wrote {len(candidate['models'])} models")
    return 0


def _atomic_write_json(path, payload):
    """写临时文件 → fsync → 原子替换。

    builtin.json 是路由的离线事实源；直接 truncate 后写盘若中途失败，会让
    seed_if_empty 静默种出空目录。os.replace 保证读者只会看到旧文件或新文件。
    """
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _read_builtin():
    with BUILTIN_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _split_openrouter_id(raw_id):
    """Mirror backend/model_catalog/sources.py::_split_model_id.

    ``openai/gpt-4o`` → ('openai', 'gpt-4o'); a slashless id → ('openrouter', raw).
    Keeping the bare slug is what makes the (provider, model_id) merge key line up
    with the rows already in builtin.json.
    """
    if "/" in raw_id:
        provider, _, model_id = raw_id.partition("/")
        return provider or "openrouter", model_id or raw_id
    return "openrouter", raw_id


def _tokenize(model_id):
    if not isinstance(model_id, str):
        return set()
    return set(_TOKEN_SPLIT_RE.split(model_id.lower()))


def _as_float(value):
    """Return a finite float for a numeric JSON value, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _per_million(per_token_price):
    """Convert a per-token price to USD per million tokens, or None if unusable."""
    value = _as_float(per_token_price)
    if value is None:
        return None
    return value * 1_000_000


def _model_sort_key(model):
    return (model.get("provider") or "", model.get("model_id") or "")


def _model_label(index, model):
    if isinstance(model, dict):
        model_id = model.get("model_id")
        if isinstance(model_id, str) and model_id:
            return f"models[{index}] ({model_id})"
    return f"models[{index}]"


def _validate_price(label, price):
    if not isinstance(price, dict):
        return [f"{label}: 'price' must be an object"]
    errors = []
    for field in ("input_per_million", "output_per_million"):
        value = price.get(field)
        if not isinstance(value, str):
            errors.append(f"{label}: price.{field} must be a string, got {value!r}")
            continue
        if _as_float(value) is None:
            errors.append(
                f"{label}: price.{field} must parse to a finite number, got {value!r}"
            )
    return errors


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _bump_minor(version):
    """``2.0.0`` → ``2.1.0``; anything unparseable → None (keep the original).

    不硬编码 fallback:遇到 ``3.x`` 这类意外文档时写死 2.1.0 会把版本改小。
    """
    if isinstance(version, str):
        parts = version.split(".")
        if len(parts) >= 2:
            try:
                major = int(parts[0])
                minor = int(parts[1])
            except ValueError:
                return None
            return f"{major}.{minor + 1}.0"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
