#!/usr/bin/env python3
"""Validate dependency-audit reports against an explicit, expiring policy."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Tuple  # noqa: UP035

# Keep typing.Tuple: this standalone script must import on Python 3.8.

REQUIRED_FIELDS = (
    "source", "package", "package_version", "advisory", "affected_path",
    "actual_reachability", "controls", "owner", "review_by",
)
Key = Tuple[str, str, str, str, str]  # noqa: UP006
LEVELS = ("low", "moderate", "high", "critical")
GHSA_PATTERN = re.compile(r"^GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$")
NUMERIC_ADVISORY_PATTERN = re.compile(r"^[0-9]+$")
PYSEC_PATTERN = re.compile(r"^PYSEC-[0-9]+-[0-9]+$")
CVE_PATTERN = re.compile(r"^CVE-[0-9]{4}-[0-9]+$")
PIP_ALIAS_PATTERN = re.compile(r"^X[0-9]+-[0-9]{4}-[0-9]+$")


def report_error(message: str, failures: list[str]) -> None:
    failures.append(message)
    escaped_message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error::{escaped_message}")


def read_json(path: str, failures: list[str]) -> Any | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report_error(f"{path}: report parse failure ({exc})", failures)
        return None


def valid_advisory_id(value: Any) -> bool:
    return isinstance(value, str) and (
        GHSA_PATTERN.fullmatch(value) is not None
        or NUMERIC_ADVISORY_PATTERN.fullmatch(value) is not None
    )


def valid_pip_advisory_id(value: Any) -> bool:
    return isinstance(value, str) and (
        PYSEC_PATTERN.fullmatch(value) is not None
        or CVE_PATTERN.fullmatch(value) is not None
        or GHSA_PATTERN.fullmatch(value) is not None
    )


def valid_pip_alias(value: Any) -> bool:
    return valid_pip_advisory_id(value) or (
        isinstance(value, str) and PIP_ALIAS_PATTERN.fullmatch(value) is not None
    )


def advisory_id(advisory: Any) -> str | None:
    if not isinstance(advisory, dict):
        return None
    source = advisory.get("source")
    if valid_advisory_id(source):
        return source
    url = advisory.get("url")
    if isinstance(url, str):
        candidate = url.rsplit("/", 1)[-1]
        if valid_advisory_id(candidate):
            return candidate
    return None


def valid_policy_advisory(source: Any, advisory: Any) -> bool:
    if not isinstance(advisory, str) or not advisory.strip():
        return False
    if source == "npm":
        return valid_advisory_id(advisory)
    return source == "pip" and valid_pip_advisory_id(advisory)


def policy_advisory_url(source: str, advisory: str) -> str:
    if source == "npm" and (advisory.startswith("GHSA-") or advisory.isdigit()):
        return f"https://github.com/advisories/{advisory}"
    if source == "pip":
        return f"https://osv.dev/vulnerability/{advisory}"
    return ""


def validate_policy(policy: Any, failures: list[str]) -> set[Key]:
    if not isinstance(policy, dict) or policy.get("default_action") != "fail":
        report_error("policy: default_action must be exactly 'fail'", failures)
        return set()
    entries = policy.get("exceptions")
    if not isinstance(entries, list):
        report_error("policy: exceptions must be a list", failures)
        return set()
    keys: set[Key] = set()
    today = dt.datetime.now(dt.timezone.utc).date()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            report_error(f"policy exception {index}: must be an object", failures)
            continue
        missing = [
            field for field in REQUIRED_FIELDS
            if not isinstance(entry.get(field), str) or not entry[field].strip()
        ]
        if "advisory_url" not in entry or not isinstance(entry.get("advisory_url"), str):
            missing.append("advisory_url")
        if missing:
            report_error(f"policy exception {index}: missing fields: {', '.join(missing)}", failures)
            continue
        source = entry["source"]
        advisory = entry["advisory"]
        if source not in {"npm", "pip"}:
            report_error(f"policy exception {index}: invalid source", failures)
            continue
        if not valid_policy_advisory(source, advisory):
            report_error(f"policy exception {index}: invalid advisory", failures)
            continue
        expected_url = policy_advisory_url(source, advisory)
        if entry["advisory_url"] != expected_url:
            report_error(f"policy exception {index}: advisory_url does not match source/advisory", failures)
        try:
            review_by = dt.date.fromisoformat(str(entry["review_by"]))
        except ValueError:
            report_error(f"policy exception {index}: review_by must be YYYY-MM-DD", failures)
            continue
        if review_by < today:
            report_error(f"policy exception {index}: review_by {review_by} is expired", failures)
        key = tuple(str(entry[field]) for field in REQUIRED_FIELDS[:5])
        if key in keys:
            report_error(f"policy exception {index}: duplicate {key}", failures)
        keys.add(key)  # type: ignore[arg-type]
    return keys


def package_identity_from_node(node: Any) -> str | None:
    if not isinstance(node, str) or not node.startswith("node_modules/"):
        return None
    package = node[len("node_modules/"):]
    if not package or package.startswith("/"):
        return None
    if package.startswith("@"):
        scope, separator, name = package.partition("/")
        if not separator or not scope[1:] or not name or "/" in name:
            return None
        return package
    if "/" in package:
        return None
    return package


def package_versions(
    lock: Any, failures: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    if lock is None:
        return {}, {}
    packages = lock.get("packages") if isinstance(lock, dict) else None
    if not isinstance(packages, dict):
        report_error("package-lock.json: invalid package-lock structure", failures)
        return {}, {}
    versions: dict[str, str] = {}
    identities: dict[str, str] = {}
    for node, value in packages.items():
        if not isinstance(node, str) or not isinstance(value, dict) or node == "":
            continue
        version = value.get("version")
        if not isinstance(version, str) or not version:
            continue
        derived_identity = package_identity_from_node(node)
        if derived_identity is None:
            continue
        declared_identity = value.get("name")
        if declared_identity is not None and (
            not isinstance(declared_identity, str)
            or declared_identity.strip() != derived_identity
        ):
            continue
        versions[node] = version
        identities[node] = derived_identity
    return versions, identities


def npm_findings(
    report: Any,
    path: str,
    versions: dict[str, str],
    identities: dict[str, str],
    failures: list[str],
) -> tuple[set[Key], dict[str, int], bool]:
    empty = {level: 0 for level in LEVELS}
    if not isinstance(report, dict):
        report_error(f"{path}: invalid npm audit report structure", failures)
        return set(), empty, False
    # npm 11+ emits an HTTP error envelope (statusCode/message/uri/method)
    # when the security advisories endpoint is unreachable (e.g. registry 503
    # behind Cloudflare). Surface that as a transient infrastructure failure
    # distinct from a malformed audit report, and report has_valid_advisory=True
    # so the outcome gate does not pile on a redundant "command failed
    # without findings" error for the same root cause.
    if (
        "vulnerabilities" not in report
        and isinstance(report.get("statusCode"), int)
        and report["statusCode"] >= 400
        and isinstance(report.get("message"), str)
    ):
        report_error(
            f"{path}: npm registry returned HTTP {report['statusCode']} "
            f"({report['message']}) — transient infrastructure failure, re-run CI",
            failures,
        )
        return set(), empty, True
    if not isinstance(report.get("vulnerabilities"), dict):
        report_error(f"{path}: invalid npm audit report structure", failures)
        return set(), empty, False
    metadata = report.get("metadata")
    counts = metadata.get("vulnerabilities") if isinstance(metadata, dict) else None
    if not isinstance(counts, dict) or any(
        level not in counts or isinstance(counts[level], bool) or not isinstance(counts[level], int) or counts[level] < 0
        for level in LEVELS
    ):
        report_error(f"{path}: metadata.vulnerabilities must contain non-negative integer counts", failures)
        normalized = {level: 0 for level in LEVELS}
    else:
        normalized = {level: counts[level] for level in LEVELS}
    findings: set[Key] = set()
    has_valid_advisory = False
    parseable_severities: set[str] = set()
    for package, item in report["vulnerabilities"].items():
        if not isinstance(package, str) or not package.strip() or not isinstance(item, dict):
            report_error(f"{path}: vulnerability item must be an object with a non-empty package name", failures)
            continue
        item_name = item.get("name")
        if not isinstance(item_name, str) or not item_name.strip():
            report_error(f"{path}: {package}: name must be a non-empty string", failures)
            continue
        if package != item_name.strip():
            report_error(f"{path}: {package}: vulnerability key and name must match", failures)
            continue
        item_name = item_name.strip()
        item_severity = item.get("severity")
        if item_severity not in LEVELS:
            report_error(f"{path}: {package}: item severity is invalid", failures)
            continue
        item_version = item.get("version")
        if item_version is not None and (
            not isinstance(item_version, str) or not item_version.strip()
        ):
            report_error(f"{path}: {package}: version must be a non-empty string", failures)
            continue
        nodes = item.get("nodes")
        if not isinstance(nodes, list) or not nodes or any(
            not isinstance(node, str) or not node.strip() or node not in versions or node not in identities
            for node in nodes
        ):
            report_error(f"{path}: {package}: nodes must exist in package-lock", failures)
            continue
        lock_identities = {identities[node] for node in nodes}
        lock_versions = {versions[node] for node in nodes}
        if lock_identities != {package} or len(lock_versions) != 1:
            report_error(f"{path}: {package}: nodes must match package identity and version", failures)
            continue
        if item_version is not None and item_version.strip() not in lock_versions:
            report_error(f"{path}: {package}: nodes must exist in package-lock and match version", failures)
            continue
        version = item_version.strip() if item_version is not None else next(iter(lock_versions))
        via = item.get("via")
        if not isinstance(via, list):
            report_error(f"{path}: {package}: via must be a list", failures)
            continue
        valid_advisories_by_severity = {level: False for level in LEVELS}
        for node in nodes:
            for advisory in via:
                if isinstance(advisory, str):
                    if not advisory.strip():
                        report_error(f"{path}: {package}: via dependency reference must be non-empty", failures)
                    continue
                if not isinstance(advisory, dict):
                    report_error(f"{path}: {package}: every via entry must be an object or non-empty dependency reference", failures)
                    continue
                severity = advisory.get("severity")
                if severity not in LEVELS:
                    report_error(f"{path}: {package}: via severity is invalid", failures)
                    continue
                identifier = advisory_id(advisory)
                if identifier is None:
                    report_error(f"{path}: {package}: via lacks a valid advisory ID", failures)
                    continue
                expected_url = policy_advisory_url("npm", identifier)
                if advisory.get("url") != expected_url:
                    report_error(f"{path}: {package}: advisory URL does not match advisory ID", failures)
                    continue
                valid_advisories_by_severity[severity] = True
                has_valid_advisory = True
                parseable_severities.add(severity)
                if severity in {"high", "critical"}:
                    findings.add(("npm", item_name, version, identifier, node))
        if item_severity in {"high", "critical"} and not valid_advisories_by_severity[item_severity]:
            report_error(f"{path}: {package}: item severity {item_severity} lacks a matching valid advisory", failures)
    expected = {level for level in ("high", "critical") if normalized[level]}
    missing_severities = expected - parseable_severities
    if missing_severities:
        report_error(
            f"{path}: high/critical aggregate but no parseable {'/'.join(sorted(missing_severities))} advisory",
            failures,
        )
    return findings, normalized, has_valid_advisory


def pip_findings(report: Any, failures: list[str]) -> set[Key]:
    dependencies = report if isinstance(report, list) else report.get("dependencies") if isinstance(report, dict) else None
    if not isinstance(dependencies, list):
        report_error("pip-audit.json: expected a JSON list or object with dependencies", failures)
        return set()
    findings: set[Key] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            report_error("pip-audit.json: invalid dependency entry", failures)
            continue
        package, version = dependency.get("name"), dependency.get("version")
        if (
            isinstance(package, str)
            and package.strip() == "sage-core"
            and isinstance(dependency.get("skip_reason"), str)
            and dependency["skip_reason"].strip()
            and set(dependency) == {"name", "skip_reason"}
        ):
            continue
        vulnerabilities = dependency.get("vulns")
        if not isinstance(package, str) or not package.strip() or not isinstance(version, str) or not version.strip():
            report_error("pip-audit.json: dependency missing name/version", failures)
            continue
        if not isinstance(vulnerabilities, list):
            report_error("pip-audit.json: dependency vulns must be an explicit list", failures)
            continue
        for vulnerability in vulnerabilities:
            if (
                not isinstance(vulnerability, dict)
                or not isinstance(vulnerability.get("id"), str)
                or not valid_pip_advisory_id(vulnerability["id"].strip())
            ):
                report_error("pip-audit.json: invalid vulnerability entry or advisory ID", failures)
                continue
            aliases = vulnerability.get("aliases")
            if aliases is not None and (
                not isinstance(aliases, list)
                or not aliases
                or any(
                    not isinstance(alias, str)
                    or not alias.strip()
                    or not valid_pip_alias(alias.strip())
                    for alias in aliases
                )
            ):
                report_error("pip-audit.json: vulnerability aliases must be a non-empty valid string list", failures)
                continue
            findings.add(("pip", package.strip(), version.strip(), vulnerability["id"].strip(), "main Python 3.11 production path"))
    return findings


def outcome(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return "missing"
    normalized = value.strip().lower()
    return normalized if normalized in {"success", "failure"} else "invalid"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npm", required=True)
    parser.add_argument("--npm-prod", required=True)
    parser.add_argument("--pip", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--package-lock", default="package-lock.json")
    args = parser.parse_args()
    failures: list[str] = []
    policy_keys = validate_policy(read_json(args.policy, failures), failures)
    lock = read_json(args.package_lock, failures)
    versions, identities = package_versions(lock, failures)
    npm_keys_by_report: dict[str, set[Key]] = {}
    npm_report_has_findings: dict[str, bool] = {}
    for name, path in (("NPM_AUDIT_ALL_OUTCOME", args.npm), ("NPM_AUDIT_PROD_OUTCOME", args.npm_prod)):
        report = read_json(path, failures)
        if report is None:
            npm_keys_by_report[name] = set()
            npm_report_has_findings[name] = False
            continue
        findings, counts, has_valid_advisory = npm_findings(report, path, versions, identities, failures)
        npm_keys_by_report[name] = findings
        npm_report_has_findings[name] = has_valid_advisory
        print(f"{path}: low={counts['low']} moderate={counts['moderate']} high={counts['high']} critical={counts['critical']}")
    npm_keys = set().union(*npm_keys_by_report.values())
    for key in sorted(npm_keys):
        if key not in policy_keys:
            report_error(f"npm {key[1]} {key[3]} package_version={key[2]} affected_path={key[4]}: not covered by policy", failures)
    pip_report = read_json(args.pip, failures)
    pip_keys = pip_findings(pip_report, failures) if pip_report is not None else set()
    print(f"pip findings={len(pip_keys)}")
    for key in sorted(pip_keys):
        if key not in policy_keys:
            report_error(f"pip {key[1]} {key[3]} package_version={key[2]} affected_path={key[4]}: not covered by policy", failures)
    for name in ("NPM_CI_OUTCOME", "PYTHON_INSTALL_OUTCOME"):
        if outcome(name) != "success":
            report_error(f"{name}: command/environment failed ({outcome(name)})", failures)
    for name in ("NPM_AUDIT_ALL_OUTCOME", "NPM_AUDIT_PROD_OUTCOME"):
        value = outcome(name)
        if value not in {"success", "failure"}:
            report_error(f"{name}: unexpected outcome {value!r}", failures)
        elif value == "failure" and not npm_report_has_findings[name]:
            report_error(f"{name}: command failed without findings", failures)
    pip_outcome = outcome("PIP_AUDIT_OUTCOME")
    if pip_outcome not in {"success", "failure"}:
        report_error(f"PIP_AUDIT_OUTCOME: unexpected outcome {pip_outcome!r}", failures)
    elif pip_outcome == "failure" and not pip_keys:
        report_error("pip-audit command failed without findings", failures)
    if failures:
        print(f"::error::Dependency audit gate failed ({len(failures)} issue(s))")
        return 1
    print("Dependency audit gate passed: all findings are explicitly covered and review dates are current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
