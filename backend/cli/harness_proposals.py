# ruff: noqa: UP006, UP007, UP035
"""``python -m backend.cli.harness proposals`` 子命令（R85）。"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

from backend.application.kernel.harness_config import (
    project_harness_files_dir,
    user_harness_files_dir,
)
from backend.application.kernel.harness_evidence import (
    create_harness_evidence,
    list_harness_evidence,
)
from backend.application.kernel.harness_files import verify_harness_files
from backend.application.kernel.harness_proposal_engine import (
    adopt_harness_proposal,
    approve_harness_proposal,
    compose_harness_proposal,
    record_harness_probe,
    reject_harness_proposal,
    rollback_harness_proposal,
    stage_harness_candidate,
)
from backend.application.kernel.harness_proposals import (
    create_harness_proposal,
    harness_proposal_view,
    list_harness_proposals,
    load_harness_proposal,
    render_harness_proposal_review,
)


def _emit(text: str) -> None:
    print(text, file=sys.stdout)  # noqa: T201 —— CLI output


def _print_json(payload: Any) -> None:
    _emit(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _root(args: argparse.Namespace) -> Path:
    output = getattr(args, "output", None)
    if output:
        return Path(output).expanduser()
    if getattr(args, "scope", "project") == "user":
        return user_harness_files_dir(getattr(args, "user_home", None))
    return project_harness_files_dir(getattr(args, "workspace", None))


def _read_json_object(path_text: str, label: str) -> Dict[str, Any]:
    path = Path(path_text).expanduser()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{label} 文件读取失败：{path}（{exc}）") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} 文件顶层必须是 JSON 对象：{path}")
    return loaded


def _resolve_candidate_content(payload: Mapping[str, Any], input_path: str) -> Dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return result
    base_dir = Path(input_path).expanduser().resolve().parent
    for candidate in candidates:
        if not isinstance(candidate, MutableMapping):
            continue
        edits = candidate.get("edits")
        if not isinstance(edits, list):
            continue
        for edit in edits:
            if not isinstance(edit, MutableMapping) or "content_file" not in edit:
                continue
            if "content" in edit or "content_base64" in edit:
                raise ValueError("candidate edit 不能同时给出 content 与 content_file")
            content_path = Path(str(edit.pop("content_file"))).expanduser()
            if not content_path.is_absolute():
                content_path = base_dir / content_path
            edit["content"] = content_path.read_bytes()
    return result


def _render_proposal_summary(view: Mapping[str, Any]) -> str:
    lines = [
        "id: {}".format(view["id"]),
        "title: {}".format(view["title"]),
        "status: {}".format(view["status"]),
        "component: {}".format(view["component"]),
        "root: {}".format(view["root"]),
        "base_current: {}".format(view["base_current"]),
        "base_lock: {}".format(view["base_lock_content_sha256"]),
        "candidates:",
    ]
    for candidate in view["candidates"]:
        lines.append(
            "  - {} lane={} edits={}".format(
                candidate["id"], candidate["lane"], len(candidate["edits"])
            )
        )
    lines.append("selected_edits:")
    if view["selected_edits"]:
        lines.extend(
            "  - {} {} from={}".format(item["operation"], item["path"], item["candidate_id"])
            for item in view["selected_edits"]
        )
    else:
        lines.append("  - (none)")
    lines.append("evidence:")
    if view["evidence"]:
        lines.extend(
            "  - {} valid={}".format(item["id"], item.get("valid")) for item in view["evidence"]
        )
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def _static_issues(root: Path, paths: Sequence[str]) -> List[str]:  # noqa: PLR0911 - 静态校验分支
    verification = verify_harness_files(root)
    issues = [
        f"{item.code}:{item.path}" if item.path else item.code
        for item in verification.issues
    ]
    for relative in sorted(set(paths)):
        target = root / Path(relative)
        if target.is_symlink():
            issues.append("symlink:" + relative)
            continue
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append("invalid_utf8:" + relative)
            continue
        suffix = Path(relative).suffix.lower()
        try:
            if suffix == ".json":
                json.loads(text)
            elif suffix in (".yaml", ".yml"):
                import yaml

                parsed = yaml.safe_load(text)
                if relative == "plugins.yaml":
                    if not isinstance(parsed, Mapping):
                        raise ValueError("plugins.yaml top level must be a mapping")
                    section = parsed.get("harness_config")
                    if not isinstance(section, Mapping):
                        raise ValueError("plugins.yaml requires a harness_config mapping")
                    from backend.application.kernel.harness_config import (
                        _apply_layer,
                        _MergeState,
                    )
                    from backend.tools.tool_bundles import bundle_names

                    _apply_layer(
                        section,
                        "staged plugins.yaml",
                        _MergeState(),
                        [],
                        known_bundles=bundle_names(),
                        strict=True,
                    )
            elif Path(relative).name == "SKILL.md":
                from backend.skills.skill_md.frontmatter import parse as parse_skill_md

                metadata, _body = parse_skill_md(text)
                if not metadata.get("name") or not metadata.get("description"):
                    raise ValueError("SKILL.md requires name and description frontmatter")
        except Exception as exc:  # noqa: BLE001 - 静态 probe 汇总全部候选问题
            issues.append(f"static:{relative}:{type(exc).__name__}")
    return issues


def _add_static_metrics(
    root: Path, proposal_id: str, report: Mapping[str, Any]
) -> Any:
    proposal = load_harness_proposal(root, proposal_id)
    normalized = copy.deepcopy(dict(report))
    base_metrics = dict(normalized.get("base_metrics") or {})
    all_paths = [
        edit.path for candidate in proposal.candidates for edit in candidate.edits
    ]
    base_issues = _static_issues(root, all_paths)
    base_metrics["static_errors"] = len(base_issues)
    normalized["base_metrics"] = base_metrics
    candidates_raw = normalized.get("candidates")
    candidates: Dict[str, Any] = (
        dict(candidates_raw) if isinstance(candidates_raw, Mapping) else {}
    )
    static_results: Dict[str, Any] = {"base": base_issues, "candidates": {}}
    with tempfile.TemporaryDirectory(prefix="sage-harness-probe-") as temp_dir:
        for candidate in proposal.candidates:
            entry = candidates.get(candidate.candidate_id)
            if not isinstance(entry, MutableMapping):
                entry = {"metrics": {}, "edits": {}}
                candidates[candidate.candidate_id] = entry
            destination = Path(temp_dir) / candidate.candidate_id
            stage_harness_candidate(root, proposal_id, candidate.candidate_id, destination)
            issues = _static_issues(
                destination, [edit.path for edit in candidate.edits]
            )
            metrics = dict(entry.get("metrics") or {})
            metrics["static_errors"] = len(issues)
            entry["metrics"] = metrics
            static_results["candidates"][candidate.candidate_id] = issues
    normalized["candidates"] = candidates
    return normalized, static_results


def _draft_payload(draft: Any) -> Dict[str, Any]:
    return {
        "id": draft.id,
        "name": draft.name,
        "description": draft.description,
        "when_to_use": draft.when_to_use,
        "content": draft.content,
        "trigger_type": draft.trigger_type,
        "source_session_id": draft.source_session_id,
        "source_context": draft.source_context,
        "status": draft.status,
        "created_at": draft.created_at,
    }


def run_proposals(args: argparse.Namespace) -> int:  # noqa: PLR0911 - CLI 子命令分发
    root = _root(args)
    command = args.proposals_command

    if command == "evidence-add":
        payload = _read_json_object(args.input, "evidence")
        record = create_harness_evidence(
            root,
            str(payload.get("id") or ""),
            str(payload.get("evidence_kind") or payload.get("type") or ""),
            payload.get("source") or {},
            excerpt=str(payload.get("excerpt") or ""),
            metrics=payload.get("metrics") or {},
            created_at=payload.get("created_at"),
            overwrite=args.overwrite,
        )
        if args.json:
            _print_json(record.to_dict())
        else:
            _emit(f"OK: added harness evidence {record.evidence_id}")
        return 0

    if command == "evidence-list":
        records = list_harness_evidence(root)
        if args.json:
            _print_json([item.to_dict() for item in records])
        else:
            _emit(
                "\n".join(
                    f"{item.evidence_id} kind={item.evidence_kind} sha256={item.evidence_sha256}"
                    for item in records
                )
                or "(no evidence)"
            )
        return 0

    if command == "create":
        payload = _resolve_candidate_content(
            _read_json_object(args.input, "proposal"), args.input
        )
        proposal = create_harness_proposal(
            root,
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            candidates=payload.get("candidates") or [],
            evidence=payload.get("evidence") or [],
            author=str(payload.get("author") or "local"),
            proposal_id=payload.get("id") or payload.get("proposal_id"),
            created_at=payload.get("created_at"),
        )
        if args.json:
            _print_json(proposal.to_dict())
        else:
            _emit(f"OK: created harness proposal {proposal.proposal_id} status=draft")
        return 0

    if command == "generate":
        from backend.skills.harness_proposal_service import get_harness_proposal_service

        proposal = asyncio.run(
            get_harness_proposal_service().generate(
                root,
                target_path=args.path,
                goal=args.goal,
                evidence_ids=args.evidence,
                title=args.title,
                summary=args.summary,
                author=args.author,
                proposal_id=args.proposal_id,
            )
        )
        if args.json:
            _print_json(proposal.to_dict())
        else:
            _emit(f"OK: generated harness proposal {proposal.proposal_id} status=draft")
        return 0

    if command == "list":
        proposals = list_harness_proposals(root, status=args.status)
        if args.json:
            _print_json([item.to_dict() for item in proposals])
        else:
            _emit(
                "\n".join(
                    f"{item.proposal_id} status={item.status} component={item.component} {item.title}"
                    for item in proposals
                )
                or "(no proposals)"
            )
        return 0

    if command == "show":
        view = harness_proposal_view(root, args.proposal_id, include_patch=args.patch)
        if args.json:
            _print_json(view)
        elif args.patch or args.review:
            _emit(render_harness_proposal_review(root, args.proposal_id).rstrip())
        else:
            _emit(_render_proposal_summary(view))
        return 0

    if command == "validate":
        view = harness_proposal_view(root, args.proposal_id)
        valid = bool(
            view["base_current"]
            and view["evidence"]
            and all(item.get("valid") for item in view["evidence"])
        )
        payload = dict(view)
        payload["valid"] = valid
        if args.json:
            _print_json(payload)
        else:
            _emit(_render_proposal_summary(view) + f"\nvalid: {valid}")
        return 0 if valid else 1

    if command == "probe":
        report = _read_json_object(args.report, "probe report")
        static_results = None
        if args.static:
            report, static_results = _add_static_metrics(root, args.proposal_id, report)
        proposal = record_harness_probe(root, args.proposal_id, report)
        if args.compose:
            proposal = compose_harness_proposal(root, args.proposal_id)
        payload = proposal.to_dict()
        if static_results is not None:
            payload = {"proposal": payload, "static": static_results}
        if args.json:
            _print_json(payload)
        else:
            _emit(
                f"OK: harness proposal {proposal.proposal_id} status={proposal.status}"
            )
        return 0

    if command == "compose":
        proposal = compose_harness_proposal(root, args.proposal_id)
        if args.json:
            _print_json(proposal.to_dict())
        else:
            _emit(
                f"OK: composed harness proposal {proposal.proposal_id} selected={len(proposal.selected_edits)}"
            )
        return 0

    if command == "submit":
        from backend.skills.harness_proposal_bridge import submit_harness_proposal

        draft = submit_harness_proposal(
            root, args.proposal_id, db_path=args.db_path, actor=args.actor
        )
        if args.json:
            _print_json(_draft_payload(draft))
        else:
            _emit(f"OK: submitted harness proposal draft={draft.id} name={draft.name}")
        return 0

    if command == "approve":
        proposal = approve_harness_proposal(root, args.proposal_id, actor=args.actor)
        if args.json:
            _print_json(proposal.to_dict())
        else:
            _emit(f"OK: approved harness proposal {proposal.proposal_id}")
        return 0

    if command == "reject":
        proposal = reject_harness_proposal(
            root, args.proposal_id, actor=args.actor, reason=args.reason
        )
        if args.json:
            _print_json(proposal.to_dict())
        else:
            _emit(f"OK: rejected harness proposal {proposal.proposal_id}")
        return 0

    if command == "adopt":
        result = adopt_harness_proposal(root, args.proposal_id, actor=args.actor)
        if args.json:
            _print_json(result)
        else:
            _emit(
                "OK: adopted harness proposal {} files={}".format(
                    args.proposal_id, len(result["changed_files"])
                )
            )
        return 0

    if command == "rollback":
        result = rollback_harness_proposal(
            root, args.proposal_id, actor=args.actor, force=args.force
        )
        if args.json:
            _print_json(result)
        else:
            _emit(f"OK: rolled back harness proposal {args.proposal_id}")
        return 0

    raise ValueError(f"unknown proposals command: {command}")


def _add_root_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", help="项目根目录（缺省：SAGE_WORKSPACE 或当前目录）")
    parser.add_argument(
        "--user-home", help="用户主目录（缺省：SAGE_HARNESS_HOME 或系统主目录）"
    )
    parser.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
        help="fileized harness 作用域（默认 project）",
    )
    parser.add_argument("--output", help="显式 fileized harness 根目录")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")


def _add_actor_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor", default="local", help="记录到提案 history 的操作者")


def add_proposals_parser(subparsers: Any) -> None:
    proposals = subparsers.add_parser(
        "proposals", help="管理证据锚定的 harness 提案（Propose–Probe–Compose）"
    )
    sub = proposals.add_subparsers(dest="proposals_command", required=True)

    evidence_add = sub.add_parser("evidence-add", help="导入一份 evidence JSON")
    _add_root_arguments(evidence_add)
    evidence_add.add_argument("--input", required=True, help="evidence JSON 文件")
    evidence_add.add_argument("--overwrite", action="store_true", help="覆盖同 ID evidence")

    evidence_list = sub.add_parser("evidence-list", help="列出 evidence")
    _add_root_arguments(evidence_list)

    create = sub.add_parser("create", help="从 JSON 创建 draft 提案")
    _add_root_arguments(create)
    create.add_argument("--input", required=True, help="proposal JSON 文件")

    generate = sub.add_parser("generate", help="用 review LLM 生成单文件双候选")
    _add_root_arguments(generate)
    generate.add_argument("--path", required=True, help="目标托管文件相对路径")
    generate.add_argument("--goal", required=True, help="离线提案目标")
    generate.add_argument(
        "--evidence", action="append", required=True, help="evidence id，可重复"
    )
    generate.add_argument("--title", help="覆盖 LLM 标题")
    generate.add_argument("--summary", help="覆盖 LLM 摘要")
    generate.add_argument("--author", default="llm-review", help="提案作者")
    generate.add_argument("--proposal-id", help="显式 proposal id")

    listing = sub.add_parser("list", help="列出提案")
    _add_root_arguments(listing)
    listing.add_argument("--status", help="按状态过滤")

    show = sub.add_parser("show", help="查看提案与可选 diff")
    _add_root_arguments(show)
    show.add_argument("proposal_id")
    show.add_argument("--patch", action="store_true", help="附带 unified diff")
    show.add_argument("--review", action="store_true", help="输出 Markdown review packet")

    validate = sub.add_parser("validate", help="校验提案基线与 evidence")
    _add_root_arguments(validate)
    validate.add_argument("proposal_id")

    probe = sub.add_parser("probe", help="导入离线 Probe 报告")
    _add_root_arguments(probe)
    probe.add_argument("proposal_id")
    probe.add_argument("--report", required=True, help="probe JSON 报告")
    probe.add_argument("--static", action="store_true", help="叠加隔离 staging 静态校验")
    probe.add_argument("--compose", action="store_true", help="记录后立即 Compose")

    for name, help_text in (
        ("compose", "按 Probe 证据筛选候选"),
        ("approve", "人工批准提案（尚未采纳）"),
        ("adopt", "采纳已批准提案"),
    ):
        child = sub.add_parser(name, help=help_text)
        _add_root_arguments(child)
        child.add_argument("proposal_id")
        _add_actor_argument(child)

    submit = sub.add_parser("submit", help="提交到既有 SkillDraft 待审队列")
    _add_root_arguments(submit)
    submit.add_argument("proposal_id")
    submit.add_argument("--db-path", help="SkillDraft SQLite 路径")
    _add_actor_argument(submit)

    reject = sub.add_parser("reject", help="拒绝提案")
    _add_root_arguments(reject)
    reject.add_argument("proposal_id")
    reject.add_argument("--reason", default="", help="拒绝理由")
    _add_actor_argument(reject)

    rollback = sub.add_parser("rollback", help="回滚已采纳提案")
    _add_root_arguments(rollback)
    rollback.add_argument("proposal_id")
    rollback.add_argument(
        "--force", action="store_true", help="允许覆盖采纳后的后续 harness 变更"
    )
    _add_actor_argument(rollback)
