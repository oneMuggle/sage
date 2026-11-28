"""文献调研运行目录 CLI（供本地调试 / skill 脚本调用）。

用法::

    python -m backend.literature.cli init --root runs --topic 主题 --site <site_id>
    python -m backend.literature.cli guidance --site <site_id> --query 机器学习
    python -m backend.literature.cli record-papers --run runs/<id> --json papers.json
    python -m backend.literature.cli gate --run runs/<id>
    python -m backend.literature.cli export --run runs/<id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .export import export_run
from .gates import (
    SUPPORTED_REFERENCE_STYLES,
    extract_claims,
    run_gates,
    verify_claims,
)
from .guidance import render_search_guidance
from .ledger import build_ledger, ledger_stats
from .models import profile_from_dict
from .profile_store import get_default_store
from .recording import write_profile_draft
from .report import build_verification_report
from .rubric import review_run
from .run_store import (
    create_run,
    list_evidence,
    list_papers,
    load_claims,
    load_run,
    read_draft,
    record_evidence,
    record_papers,
    record_query,
    run_status,
    save_claims,
    save_draft,
    save_outline,
)
from .support import apply_claim_support, summarize_claim_support
from .verify import (
    apply_evidence_support,
    default_lookups,
    verify_run_access,
    verify_run_metadata,
)


def _print(data: Any) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _read_json_arg(path: str) -> Any:
    return json.loads(_read_text(path))


def _rows_arg(path: str, key: str) -> List[Dict[str, Any]]:
    data = _read_json_arg(path)
    if isinstance(data, dict):
        data = data.get(key, [])
    if not isinstance(data, list):
        raise ValueError(f"{path} 必须是数组，或包含数组字段 {key!r}")
    return data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.literature.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="创建运行目录")
    init.add_argument("--root", required=True)
    init.add_argument("--topic", required=True)
    init.add_argument("--site", required=True)
    init.add_argument("--run-id", default=None)

    guidance = sub.add_parser("guidance", help="输出站点检索指导")
    guidance.add_argument("--site", required=True)
    guidance.add_argument("--query", required=True)
    guidance.add_argument("--limit", type=int, default=10)
    guidance.add_argument("--page-url", default=None)
    guidance.add_argument("--page-title", default=None)

    query = sub.add_parser("record-query")
    query.add_argument("--run", required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--site", required=True)
    query.add_argument("--result-count", type=int, required=True)
    query.add_argument("--note", default=None)

    papers = sub.add_parser("record-papers")
    papers.add_argument("--run", required=True)
    papers.add_argument("--json", required=True)

    evidence = sub.add_parser("record-evidence")
    evidence.add_argument("--run", required=True)
    evidence.add_argument("--json", required=True)

    outline = sub.add_parser("save-outline")
    outline.add_argument("--run", required=True)
    outline.add_argument("--json", required=True)

    draft = sub.add_parser("save-draft")
    draft.add_argument("--run", required=True)
    draft.add_argument("--md", required=True)

    gate = sub.add_parser("gate")
    gate.add_argument("--run", required=True)

    extract = sub.add_parser("extract-claims")
    extract.add_argument("--run", required=True)

    verify = sub.add_parser("verify-claims")
    verify.add_argument("--run", required=True)

    verify_meta = sub.add_parser("verify-metadata")
    verify_meta.add_argument("--run", required=True)
    verify_meta.add_argument("--min-consensus", type=int, default=2)

    apply_support = sub.add_parser("apply-claim-support")
    apply_support.add_argument("--run", required=True)
    apply_support.add_argument("--json", required=True)

    build_ledger_cmd = sub.add_parser("build-ledger")
    build_ledger_cmd.add_argument("--run", required=True)
    build_ledger_cmd.add_argument("--external", default=None)

    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("--run", required=True)

    rubric_cmd = sub.add_parser("rubric", help="四维 rubric 评审（方法/覆盖/逻辑/写作）")
    rubric_cmd.add_argument("--run", required=True)

    export = sub.add_parser("export")
    export.add_argument("--run", required=True)
    export.add_argument("--style", choices=list(SUPPORTED_REFERENCE_STYLES), default="gbt7714")

    status = sub.add_parser("status")
    status.add_argument("--run", required=True)

    validate = sub.add_parser("validate-profile")
    validate.add_argument("--path", required=True)

    record = sub.add_parser("draft-profile")
    record.add_argument("--observation", required=True)
    record.add_argument("--out", required=True)

    verify_access = sub.add_parser(
        "verify-access", help="Unpaywall OA 可得性轴（无 email 时全部 unknown）"
    )
    verify_access.add_argument("--run", required=True)
    verify_access.add_argument(
        "--site", default="", help="站点 id；读取 compliance.contact_email 装配 OA 轴"
    )

    discover = sub.add_parser(
        "discover-backends", help="枚举站点可用文献库并写回 backends sidecar"
    )
    discover.add_argument("--site", required=True, help="站点 id")
    discover.add_argument("--snapshot", required=True, help="库清单页快照文件路径")
    discover.add_argument("--entry-url", default="", help="库清单页 URL")
    discover.add_argument("--backend-id", default="", help="只探测这一个后端")

    return parser


def _dispatch(args: argparse.Namespace) -> int:  # noqa: PLR0911 — 每个子命令独立 return，扁平可读
    if args.command == "init":
        run = create_run(Path(args.root), args.topic, args.site, run_id=args.run_id)
        _print({"ok": True, "run_id": run.run_id, "run_dir": str(run.run_dir)})
        return 0

    if args.command == "guidance":
        profile = get_default_store().get(args.site)
        text = render_search_guidance(
            profile,
            args.query,
            limit=args.limit,
            page_url=args.page_url,
            page_title=args.page_title,
        )
        _print({"ok": True, "site": args.site, "guidance": text})
        return 0

    if args.command == "validate-profile":
        raw = yaml.safe_load(_read_text(args.path)) or {}
        profile = profile_from_dict(raw, source_path=args.path, source_layer="user")
        _print({"ok": True, "id": profile.id, "status": profile.status})
        return 0

    if args.command == "draft-profile":
        raw = _read_json_arg(args.observation)
        profile = write_profile_draft(raw, Path(args.out))
        _print(
            {
                "ok": True,
                "id": profile.id,
                "status": profile.status,
                "path": args.out,
            }
        )
        return 0

    if args.command == "discover-backends":
        from .backends import parse_backend_entries
        from .knowledge import read_sidecar, sidecar_path, write_sidecar
        from .models import parse_backends
        from .profile_store import user_sites_dir

        snapshot_text = Path(args.snapshot).read_text(encoding="utf-8")
        discovered = parse_backend_entries(snapshot_text, args.entry_url or "https://")
        if args.backend_id:
            discovered = [item for item in discovered if item.id == args.backend_id]
        target = sidecar_path(user_sites_dir(), args.site, "backends")
        existing = parse_backends(read_sidecar(target).get("backends"))
        existing_by_id = {backend.id: backend for backend in existing}
        merged = [existing_by_id.get(item.id, item) for item in discovered]
        write_sidecar(
            target,
            {
                "backends": [
                    {
                        "id": backend.id,
                        "label": backend.label,
                        "entry_url": backend.entry_url,
                        "status": backend.status,
                        "reason": backend.reason,
                        "capabilities": dict(backend.capabilities),
                        "overrides": dict(backend.overrides),
                        "checked_at": backend.checked_at,
                    }
                    for backend in merged
                ]
            },
        )
        _print({"ok": True, "path": str(target), "total": len(merged)})
        return 0

    run = load_run(Path(args.run))

    if args.command == "record-query":
        record_query(run, args.query, args.site, args.result_count, note=args.note)
        _print({"ok": True, "queries": run_status(run)["queries"]})
        return 0

    if args.command == "record-papers":
        added = record_papers(run, _rows_arg(args.json, "papers"))
        _print({"ok": True, "added": added, "papers": run_status(run)["papers"]})
        return 0

    if args.command == "record-evidence":
        added = record_evidence(run, _rows_arg(args.json, "evidence"))
        _print({"ok": True, "added": added, "evidence": run_status(run)["evidence"]})
        return 0

    if args.command == "save-outline":
        outline = save_outline(run, _read_json_arg(args.json))
        _print({"ok": True, "sections": len(outline.sections)})
        return 0

    if args.command == "save-draft":
        save_draft(run, _read_text(args.md))
        _print({"ok": True, "draft": str(run.run_dir / "draft.md")})
        return 0

    if args.command == "gate":
        report = run_gates(run)
        _print(report.to_dict())
        return 0 if report.ok else 1

    if args.command == "extract-claims":
        claims = extract_claims(read_draft(run))
        save_claims(run, claims)
        _print({"ok": True, "claims": len(claims)})
        return 0

    if args.command == "verify-claims":
        claims = extract_claims(read_draft(run))
        paper_keys = {p.paper_key for p in list_papers(run)}
        verified = verify_claims(claims, paper_keys)
        verified = apply_evidence_support(verified, list_evidence(run))
        save_claims(run, verified)
        verdicts: Dict[str, int] = {}
        for claim in verified:
            verdicts[claim.verdict] = verdicts.get(claim.verdict, 0) + 1
        _print(
            {
                "ok": True,
                "claims": len(verified),
                "verdicts": verdicts,
                "items": [claim.to_dict() for claim in verified],
            }
        )
        return 0 if not verdicts.get("unresolved") and not verdicts.get("unsupported") else 1

    if args.command == "verify-access":
        profile = get_default_store().get(args.site) if args.site else None
        report = verify_run_access(run, profile=profile)
        _print({"ok": True, **report})
        return 0

    if args.command == "verify-metadata":
        report = verify_run_metadata(run, default_lookups(), args.min_consensus)
        _print({"ok": True, **report})
        return 0 if not report.get("unverified") else 1

    if args.command == "apply-claim-support":
        judgments = _rows_arg(args.json, "judgments")
        updated = apply_claim_support(load_claims(run), judgments)
        save_claims(run, updated)
        summary = summarize_claim_support(updated)
        _print({"ok": True, "claims": len(updated), "verdicts": summary})
        return 1 if summary.get("unsupported") or summary.get("unresolved") else 0

    if args.command == "build-ledger":
        external = _rows_arg(args.external, "entries") if args.external else None
        ledger = build_ledger(run, external)
        _print(
            {
                "ok": True,
                "entries": len(ledger.entries),
                "by_source": ledger_stats(ledger),
            }
        )
        return 0

    if args.command == "report":
        report = build_verification_report(run)
        _print(
            {
                "ok": True,
                "summary": report["summary"],
                "metadata": {
                    key: report.get("metadata", {}).get(key, 0)
                    for key in ("verified", "partial", "unverified", "skipped")
                },
                "paths": report.get("paths"),
            }
        )
        return 0

    if args.command == "rubric":
        review = review_run(run)
        _print(
            {
                "ok": True,
                "total_score": review["total_score"],
                "max_score": review["max_score"],
                "band": review["band"],
                "dimensions": [
                    {
                        "id": dimension["id"],
                        "score": dimension["score"],
                        "issues": dimension["issues"],
                    }
                    for dimension in review["dimensions"]
                ],
                "paths": review.get("paths"),
            }
        )
        return 0

    if args.command == "export":
        paths = export_run(run, style=args.style)
        _print({"ok": True, "paths": {key: str(value) for key, value in paths.items()}})
        return 0

    if args.command == "status":
        _print({"ok": True, "status": run_status(run)})
        return 0

    raise ValueError(f"未知命令: {args.command}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (ValueError, OSError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
