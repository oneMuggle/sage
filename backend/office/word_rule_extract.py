"""Deterministic Word rule extraction (M3a).

Orchestrates specification/template extraction, merges duplicates, flags
conflicts and builds a draft :class:`WordRulePack` with provenance.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document

from .doc_profile import read_doc_profile
from .errors import OfficeFileNotFoundError, OfficeParseError
from .word_rule_extract_common import (
    KIND_META,
    KIND_ORDER,
    MERGE_FIELDS,
    RawCandidate,
    normal_style_paragraph_format,
)
from .word_rule_extract_spec import extract_spec_candidates, load_spec_paragraphs
from .word_rule_extract_template import extract_template_candidates
from .word_rulepack_models import (
    WordRuleCandidate,
    WordRuleConflict,
    WordRuleExtractionResult,
    WordRuleExtractionSummary,
    WordRulePack,
    WordRuleSpec,
)


def _merge_candidates(
    raw: List[RawCandidate],
) -> Tuple[List[RawCandidate], List[Tuple[str, List[str]]]]:
    merged: List[RawCandidate] = []
    conflicts: List[Tuple[str, List[str]]] = []
    for kind in KIND_ORDER:
        group = [candidate for candidate in raw if candidate.kind == kind]
        if not group:
            continue
        merge_fields = MERGE_FIELDS.get(kind)
        if merge_fields:
            first = group[0]
            base = RawCandidate(
                kind=first.kind,
                params=dict(first.params),
                confidence=first.confidence,
                source=first.source,
                excerpt=first.excerpt,
                paragraph_index=first.paragraph_index,
            )
            conflicted: List[str] = []
            for other in group[1:]:
                for key, value in other.params.items():
                    if key in base.params and base.params[key] != value:
                        conflicted.append(key)
                    else:
                        base.params.setdefault(key, value)
            if conflicted:
                group_id = f"conflict/{kind}"
                for candidate in group:
                    candidate.conflict_group = group_id
                merged.extend(group)
                conflicts.append((kind, sorted(set(conflicted))))
            else:
                base.confidence = max(candidate.confidence for candidate in group)
                merged.append(base)
            continue

        by_params: Dict[str, RawCandidate] = {}
        for candidate in group:
            key = json.dumps(candidate.params, sort_keys=True, ensure_ascii=False)
            existing = by_params.get(key)
            if existing is None or candidate.confidence > existing.confidence:
                by_params[key] = candidate
        if len(by_params) > 1:
            group_id = f"conflict/{kind}"
            for candidate in group:
                candidate.conflict_group = group_id
            merged.extend(by_params.values())
            conflicts.append((kind, ["params"]))
        else:
            merged.extend(by_params.values())
    return merged, conflicts


def _build_pack(
    merged: List[RawCandidate],
    conflicts: List[Tuple[str, List[str]]],
    *,
    pack_id: str,
    pack_name: Optional[str],
    rel_path: str,
) -> Tuple[WordRulePack, List[WordRuleCandidate], List[WordRuleConflict]]:
    counters: Dict[str, int] = defaultdict(int)
    rules: List[WordRuleSpec] = []
    candidates: List[WordRuleCandidate] = []
    ids_by_group: Dict[str, List[str]] = defaultdict(list)
    for raw in merged:
        counters[raw.kind] += 1
        index = counters[raw.kind]
        rule_id = f"extracted/{raw.kind}" + ("" if index == 1 else f"-{index}")
        title, category, severity, fix_hint, fixable = KIND_META[raw.kind]
        rule = WordRuleSpec(
            id=rule_id,
            title=title,
            description=raw.excerpt[:200],
            category=category,
            severity=severity,
            kind=raw.kind,
            params=raw.params,
            source=raw.source,
            fixable=fixable,
            fix_hint=fix_hint,
        )
        rules.append(rule)
        candidates.append(
            WordRuleCandidate(
                rule=rule,
                confidence=round(max(0.0, min(1.0, raw.confidence)), 2),
                source_excerpt=raw.excerpt,
                conflict_group=raw.conflict_group,
            )
        )
        if raw.conflict_group:
            ids_by_group[raw.conflict_group].append(rule_id)
    conflict_models = [
        WordRuleConflict(
            kind=kind,
            rule_ids=ids_by_group.get(f"conflict/{kind}", []),
            message="同一规则类型抽取到不同取值，需要人工选择: " + ", ".join(fields),
        )
        for kind, fields in conflicts
    ]
    pack = WordRulePack(
        id=pack_id,
        name=pack_name or f"从 {Path(rel_path).name} 抽取的规则",
        version="1.0",
        description=f"从 {rel_path} 自动抽取，需人工复核后启用",
        source=rel_path,
        rules=rules,
    )
    return pack, candidates, conflict_models


def _extract_raw(
    file_path: Path,
    *,
    file_type: str,
    workspace_path: Optional[str],
) -> Tuple[str, List[RawCandidate], List[Dict[str, str]], List[Dict[str, Any]]]:
    path = Path(file_path)
    if not path.exists():
        raise OfficeFileNotFoundError(path)
    if not path.is_file():
        raise OfficeParseError("抽取源路径不是文件")
    if file_type not in ("spec", "template"):
        raise OfficeParseError("file_type 只能是 spec 或 template")
    if file_type == "template" and path.suffix.lower() != ".docx":
        raise OfficeParseError("范本抽取仅支持 .docx")

    warnings: List[Dict[str, str]] = []
    if file_type == "spec":
        paragraphs, rel_path, load_warnings = load_spec_paragraphs(
            path, workspace_path
        )
        warnings.extend(load_warnings)
        raw = extract_spec_candidates(paragraphs, rel_path, warnings)
        return rel_path, raw, warnings, paragraphs

    profile = read_doc_profile(path, workspace_path=workspace_path)
    rel_path = str(profile["source_path"])
    warnings.extend(dict(item) for item in profile.get("warnings", []))
    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 — map all parse failures
        raise OfficeParseError(f"Failed to parse DOCX: {exc}") from exc
    raw = extract_template_candidates(
        profile,
        rel_path,
        warnings,
        normal_style_paragraph_format(document),
    )
    return rel_path, raw, warnings, list(profile.get("paragraphs", []))


def _build_result(
    rel_path: str,
    raw: List[RawCandidate],
    warnings: List[Dict[str, str]],
    *,
    file_type: str,
    pack_id: str,
    pack_name: Optional[str],
    llm_used: bool,
) -> WordRuleExtractionResult:
    merged, conflicts = _merge_candidates(raw)
    pack, candidates, conflict_models = _build_pack(
        merged,
        conflicts,
        pack_id=pack_id,
        pack_name=pack_name,
        rel_path=rel_path,
    )
    if pack.rules:
        from .word_audit import validate_rulepack

        validate_rulepack(pack)
    else:
        warnings.append(
            {"code": "no_rules_extracted", "message": "未从源文档中识别到可执行规则"}
        )
    return WordRuleExtractionResult(
        ok=bool(pack.rules),
        source_path=rel_path,
        file_type=file_type,  # type: ignore[arg-type]
        llm_used=llm_used,
        pack=pack,
        candidates=candidates,
        conflicts=conflict_models,
        warnings=warnings,
        summary=WordRuleExtractionSummary(
            rules=len(pack.rules),
            candidates=len(candidates),
            conflicts=len(conflict_models),
            warnings=len(warnings),
        ),
    )


def extract_word_rules(
    file_path: Path,
    *,
    file_type: str = "spec",
    pack_id: str = "extracted-pack",
    pack_name: Optional[str] = None,
    workspace_path: Optional[str] = None,
) -> WordRuleExtractionResult:
    """Deterministic extraction (no LLM), kept for sync callers/tests."""
    rel_path, raw, warnings, _paragraphs = _extract_raw(
        file_path, file_type=file_type, workspace_path=workspace_path
    )
    return _build_result(
        rel_path,
        raw,
        warnings,
        file_type=file_type,
        pack_id=pack_id,
        pack_name=pack_name,
        llm_used=False,
    )


async def extract_word_rules_async(
    file_path: Path,
    *,
    file_type: str = "spec",
    pack_id: str = "extracted-pack",
    pack_name: Optional[str] = None,
    workspace_path: Optional[str] = None,
    use_llm: bool = False,
    llm_client: Optional[Any] = None,
) -> WordRuleExtractionResult:
    """Deterministic extraction plus optional LLM candidates (spec only).

    Every LLM candidate is re-validated by :mod:`word_rule_extract_llm`;
    no LLM config / call failure / parse failure degrades to the
    deterministic result with a warning instead of raising.
    """
    rel_path, raw, warnings, paragraphs = _extract_raw(
        file_path, file_type=file_type, workspace_path=workspace_path
    )
    llm_used = False
    if use_llm:
        if file_type != "spec":
            warnings.append(
                {
                    "code": "llm_template_unsupported",
                    "message": "LLM 补充仅适用于规范文档，模板已使用确定性抽取",
                }
            )
        else:
            client = llm_client
            if client is None:
                try:
                    from backend.orchestration.llm_factory import (
                        build_llm_client_from_settings,
                    )

                    client = build_llm_client_from_settings()
                except Exception as exc:  # noqa: BLE001 — settings failures degrade
                    client = None
                    warnings.append(
                        {
                            "code": "llm_unavailable",
                            "message": f"无法加载 LLM 配置: {str(exc)[:200]}",
                        }
                    )
            if client is None:
                if not any(w["code"] == "llm_unavailable" for w in warnings):
                    warnings.append(
                        {
                            "code": "llm_unavailable",
                            "message": "未配置 LLM，已仅使用确定性抽取",
                        }
                    )
            else:
                from .word_rule_extract_llm import propose_llm_candidates

                llm_raw = await propose_llm_candidates(
                    rel_path, paragraphs, client=client, warnings=warnings
                )
                raw.extend(llm_raw)
                llm_used = True
    return _build_result(
        rel_path,
        raw,
        warnings,
        file_type=file_type,
        pack_id=pack_id,
        pack_name=pack_name,
        llm_used=llm_used,
    )


__all__ = ["extract_word_rules", "extract_word_rules_async"]
