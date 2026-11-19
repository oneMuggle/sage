import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "check_dependency_audit.py"


def write_json(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def npm_report(advisory="GHSA-test-test-test", severity="high", count=1, *, include_version=False):
    item = {
        "name": "electron", "severity": severity,
        "nodes": ["node_modules/electron"],
        "via": [{"url": f"https://github.com/advisories/{advisory}", "severity": severity}],
    }
    if include_version:
        item["version"] = "21.4.4"
    return {
        "metadata": {"vulnerabilities": {"low": 0, "moderate": 0, "high": count, "critical": 0}},
        "vulnerabilities": {"electron": item},
    }


def empty_npm():
    return {"metadata": {"vulnerabilities": {"low": 0, "moderate": 0, "high": 0, "critical": 0}}, "vulnerabilities": {}}


def package_lock_data():
    return {"lockfileVersion": 3, "packages": {
        "": {"name": "sage", "version": "1.0.0"},
        "node_modules/electron": {"version": "21.4.4"},
    }}


def package_lock():
    return package_lock_data()


def base_policy():
    return {"default_action": "fail", "exceptions": [{
        "source": "npm", "package": "electron", "package_version": "21.4.4", "advisory": "GHSA-test-test-test",
        "advisory_url": "https://github.com/advisories/GHSA-test-test-test",
        "affected_path": "node_modules/electron", "actual_reachability": "accepted risk",
        "controls": "test control", "owner": "Sage maintainers", "review_by": "2099-01-01",
    }]}


def run_gate(tmp_path, *, policy=None, npm=None, npm_prod=None, pip=None, package_lock=None, unset_env=(), **env):
    write_json(tmp_path / "policy.json", policy or base_policy())
    write_json(tmp_path / "package-lock.json", package_lock or package_lock_data())
    write_json(tmp_path / "npm.json", npm if npm is not None else npm_report())
    write_json(tmp_path / "npm-prod.json", npm_prod if npm_prod is not None else npm_report())
    write_json(tmp_path / "pip.json", pip if pip is not None else {"dependencies": []})
    command_env = os.environ.copy()
    command_env.update({
        "NPM_CI_OUTCOME": "success", "PYTHON_INSTALL_OUTCOME": "success",
        "NPM_AUDIT_ALL_OUTCOME": "failure", "NPM_AUDIT_PROD_OUTCOME": "failure",
        "PIP_AUDIT_OUTCOME": "success", **env,
    })
    for name in unset_env:
        command_env.pop(name, None)
    return subprocess.run([
        sys.executable, str(SCRIPT), "--npm", str(tmp_path / "npm.json"),
        "--npm-prod", str(tmp_path / "npm-prod.json"), "--pip", str(tmp_path / "pip.json"),
        "--policy", str(tmp_path / "policy.json"), "--package-lock", str(tmp_path / "package-lock.json"),
    ], env=command_env, capture_output=True, text=True, check=False)


def test_allows_npm_exit_one_when_report_has_findings(tmp_path):
    result = run_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "high=1" in result.stdout


def test_rejects_unmapped_npm_advisory(tmp_path):
    result = run_gate(tmp_path, policy={"default_action": "fail", "exceptions": []})
    assert result.returncode == 1
    assert "not covered by policy" in result.stdout
    assert "::error::" in result.stdout


def test_rejects_npm_version_mismatch_with_package_lock(tmp_path):
    report = npm_report(include_version=True)
    report["vulnerabilities"]["electron"]["version"] = "99.0.0"
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "nodes must exist in package-lock and match version" in result.stdout


@pytest.mark.parametrize(
    "missing",
    [
        "NPM_CI_OUTCOME",
        "PYTHON_INSTALL_OUTCOME",
        "NPM_AUDIT_ALL_OUTCOME",
        "NPM_AUDIT_PROD_OUTCOME",
        "PIP_AUDIT_OUTCOME",
    ],
)
def test_missing_outcome_fails_closed(tmp_path, missing):
    result = run_gate(tmp_path, unset_env=(missing,))
    assert result.returncode == 1
    assert f"{missing}:" in result.stdout
    assert "missing" in result.stdout


@pytest.mark.parametrize(
    "vulnerability_id",
    ["GHSA-pip", "PYSEC-2024", "PYSEC-2024-x", "CVE-24-1234", "CVE-2024"],
)
def test_rejects_malformed_pip_advisory_id(tmp_path, vulnerability_id):
    pip = {"dependencies": [{"name": "demo", "version": "1.0", "vulns": [{"id": vulnerability_id}]}]}
    result = run_gate(tmp_path, pip=pip)
    assert result.returncode == 1
    assert "invalid vulnerability entry or advisory ID" in result.stdout


@pytest.mark.parametrize("aliases", [[""], ["GHSA-pip"], [1], "CVE-2024-1234"])
def test_rejects_malformed_pip_aliases(tmp_path, aliases):
    pip = {"dependencies": [{"name": "demo", "version": "1.0", "vulns": [{"id": "CVE-2024-1234", "aliases": aliases}]}]}
    result = run_gate(tmp_path, pip=pip)
    assert result.returncode == 1
    assert "aliases must be a list of valid advisory IDs" in result.stdout


def test_accepts_pip_audit_object_format_and_exact_exception(tmp_path):
    pip = {
        "dependencies": [
            {
                "name": "demo",
                "version": "1.0",
                "vulns": [{"id": "GHSA-pip0-pip0-pip0", "aliases": []}],
            }
        ]
    }
    policy = base_policy()
    policy["exceptions"].append(
        {
            "source": "pip",
            "package": "demo",
            "package_version": "1.0",
            "advisory": "GHSA-pip0-pip0-pip0",
            "advisory_url": "https://osv.dev/vulnerability/GHSA-pip0-pip0-pip0",
            "affected_path": "main Python 3.11 production path",
            "actual_reachability": "conditional",
            "controls": "test control",
            "owner": "Sage maintainers",
            "review_by": "2099-01-01",
        }
    )
    result = run_gate(tmp_path, policy=policy, pip=pip)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pip findings=1" in result.stdout


def test_pip_failure_allowed_only_with_findings(tmp_path):
    pip = {"dependencies": [{"name": "demo", "version": "1.0", "vulns": [{"id": "GHSA-pip0-pip0-pip0"}]}]}
    policy = base_policy()
    policy["exceptions"].append({
        "source": "pip", "package": "demo", "package_version": "1.0", "advisory": "GHSA-pip0-pip0-pip0",
        "advisory_url": "https://osv.dev/vulnerability/GHSA-pip0-pip0-pip0",
        "affected_path": "main Python 3.11 production path", "actual_reachability": "conditional",
        "controls": "test", "owner": "Sage maintainers", "review_by": "2099-01-01",
    })
    result = run_gate(tmp_path, policy=policy, pip=pip, PIP_AUDIT_OUTCOME="failure")
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_gate(tmp_path, policy=policy, pip={"dependencies": []}, PIP_AUDIT_OUTCOME="failure")
    assert result.returncode == 1
    assert "pip-audit command failed without findings" in result.stdout


def test_all_failure_rejected_when_all_empty_but_prod_has_findings(tmp_path):
    result = run_gate(tmp_path, npm=empty_npm(), npm_prod=npm_report(), NPM_AUDIT_ALL_OUTCOME="failure", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "NPM_AUDIT_ALL_OUTCOME: command failed without findings" in result.stdout


def test_prod_failure_rejected_when_prod_empty_but_all_has_findings(tmp_path):
    result = run_gate(tmp_path, npm=npm_report(), npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="failure")
    assert result.returncode == 1
    assert "NPM_AUDIT_PROD_OUTCOME: command failed without findings" in result.stdout


def test_rejects_npm_aggregate_high_without_parseable_high_advisory(tmp_path):
    report = npm_report(advisory="GHSA-moderate", severity="moderate", count=1)
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "high/critical aggregate but no parseable" in result.stdout


def test_rejects_malformed_npm_vulnerability_items(tmp_path):
    malformed = npm_report()
    malformed["vulnerabilities"]["electron"] = None
    result = run_gate(tmp_path, npm=malformed, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "vulnerability item must be an object" in result.stdout


def test_rejects_non_mapping_npm_vulnerabilities_without_traceback(tmp_path):
    malformed = npm_report()
    malformed["vulnerabilities"] = []
    result = run_gate(
        tmp_path,
        npm=malformed,
        npm_prod=empty_npm(),
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode != 0
    assert "Dependency audit gate failed" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("field, value, expected", [
    ("name", "", "name must be a non-empty string"),
    ("version", "", "version must be a non-empty string"),
    ("nodes", ["node_modules/missing"], "nodes must exist in package-lock"),
    ("via", [""], "via dependency reference must be non-empty"),
    ("via", [1], "every via entry must be an object or non-empty dependency reference"),
    ("via", [{"severity": "high", "url": "https://example.invalid/advisory"}], "lacks a valid advisory ID"),
])
def test_rejects_malformed_npm_item_fields(tmp_path, field, value, expected):
    malformed = npm_report()
    malformed["vulnerabilities"]["electron"][field] = value
    result = run_gate(tmp_path, npm=malformed, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert expected in result.stdout


@pytest.mark.parametrize("metadata", [
    {"low": 0, "moderate": 0, "high": 1},
    {"low": 0, "moderate": 0, "high": -1, "critical": 0},
    {"low": 0, "moderate": 0, "high": True, "critical": 0},
])
def test_rejects_malformed_npm_metadata_counts(tmp_path, metadata):
    malformed = npm_report()
    malformed["metadata"]["vulnerabilities"] = metadata
    result = run_gate(tmp_path, npm=malformed, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "metadata.vulnerabilities must contain" in result.stdout


@pytest.mark.parametrize("vulns", [None, {"id": "GHSA-pip"}, [{"id": ""}], [{"id": "GHSA-pip", "aliases": [1]}]])
def test_rejects_malformed_pip_vulnerabilities(tmp_path, vulns):
    pip = {"dependencies": [{"name": "demo", "version": "1.0", "vulns": vulns}]}
    result = run_gate(tmp_path, pip=pip)
    assert result.returncode == 1
    assert "pip-audit.json" in result.stdout


def test_accepts_npm_dependency_reference_strings(tmp_path):
    report = npm_report()
    report["vulnerabilities"]["electron"]["via"].insert(0, "@electron/get")
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 0, result.stdout + result.stderr


def test_accepts_high_npm_meta_vulnerability_via_reported_dependency(tmp_path):
    advisory = "GHSA-test-test-test"
    report = {
        "metadata": {
            "vulnerabilities": {"low": 0, "moderate": 0, "high": 2, "critical": 0}
        },
        "vulnerabilities": {
            "wrapper": {
                "name": "wrapper",
                "severity": "high",
                "nodes": ["node_modules/wrapper"],
                "via": ["braces"],
            },
            "braces": {
                "name": "braces",
                "severity": "high",
                "nodes": ["node_modules/braces"],
                "via": [
                    {
                        "url": f"https://github.com/advisories/{advisory}",
                        "severity": "high",
                    }
                ],
            },
        },
    }
    package_lock = package_lock_data()
    package_lock["packages"]["node_modules/wrapper"] = {"version": "1.0.0"}
    package_lock["packages"]["node_modules/braces"] = {"version": "3.0.3"}
    policy = base_policy()
    policy["exceptions"].append(
        {
            "source": "npm",
            "package": "braces",
            "package_version": "3.0.3",
            "advisory": advisory,
            "advisory_url": f"https://github.com/advisories/{advisory}",
            "affected_path": "node_modules/braces",
            "actual_reachability": "test",
            "controls": "test",
            "owner": "Sage maintainers",
            "review_by": "2099-01-01",
        }
    )
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=package_lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_high_npm_meta_vulnerability_with_unresolved_reference(tmp_path):
    report = npm_report()
    report["vulnerabilities"]["electron"]["via"] = ["not-in-this-report"]
    result = run_gate(
        tmp_path,
        npm=report,
        npm_prod=empty_npm(),
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 1
    assert "lacks a matching valid advisory or dependency chain" in result.stdout


def test_accepts_editable_pip_skip_entry(tmp_path):
    result = run_gate(tmp_path, pip={"dependencies": [{"name": "sage-core", "skip_reason": "editable local package"}]})
    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_editable_pip_skip_entry_with_extra_fields(tmp_path):
    pip = {"dependencies": [{"name": "sage-core", "skip_reason": "editable local package", "version": "1.0"}]}
    result = run_gate(tmp_path, pip=pip)
    assert result.returncode == 1
    assert "dependency vulns must be an explicit list" in result.stdout


def test_rejects_editable_pip_skip_entry_without_reason(tmp_path):
    result = run_gate(tmp_path, pip={"dependencies": [{"name": "sage-core"}]})
    assert result.returncode == 1
    assert "dependency missing name/version" in result.stdout



def test_npm_outcomes_use_their_own_reports(tmp_path):
    result = run_gate(
        tmp_path,
        npm=empty_npm(),
        npm_prod=npm_report(),
        NPM_AUDIT_ALL_OUTCOME="failure",
        NPM_AUDIT_PROD_OUTCOME="failure",
    )
    assert result.returncode == 1
    assert "NPM_AUDIT_ALL_OUTCOME: command failed without findings" in result.stdout


def test_rejects_expired_policy_and_duplicate_exception(tmp_path):
    policy = base_policy()
    policy["exceptions"][0]["review_by"] = "2000-01-01"
    policy["exceptions"].append(dict(policy["exceptions"][0]))
    result = run_gate(tmp_path, policy=policy)
    assert result.returncode == 1
    assert "expired" in result.stdout
    assert "duplicate" in result.stdout




def test_derives_missing_npm_version_from_lockfile(tmp_path):
    result = run_gate(tmp_path, npm=npm_report(include_version=False), npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("key,item_name,node", [
    ("not-electron", "electron", "node_modules/electron"),
    ("electron", "not-electron", "node_modules/electron"),
    ("electron", "electron", "node_modules/not-electron"),
])
def test_rejects_forged_npm_identity(tmp_path, key, item_name, node):
    report = npm_report()
    item = report["vulnerabilities"].pop("electron")
    item["name"] = item_name
    item["nodes"] = [node]
    report["vulnerabilities"][key] = item
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "vulnerability key and name must match" in result.stdout or "nodes must exist" in result.stdout
    assert "not covered by policy" not in result.stdout


@pytest.mark.parametrize("severity,via_severity", [
    ("high", "moderate"),
    ("critical", "high"),
])
def test_rejects_npm_item_severity_without_matching_advisory(tmp_path, severity, via_severity):
    report = npm_report(severity=via_severity)
    report["vulnerabilities"]["electron"]["severity"] = severity
    report["metadata"]["vulnerabilities"]["high"] = int(severity == "high")
    report["metadata"]["vulnerabilities"]["critical"] = int(severity == "critical")
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm(), NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success")
    assert result.returncode == 1
    assert "lacks a matching valid advisory" in result.stdout
    run_gate(tmp_path)
    (tmp_path / "npm.json").write_text("not-json")
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--npm", str(tmp_path / "npm.json"),
        "--npm-prod", str(tmp_path / "npm-prod.json"), "--pip", str(tmp_path / "pip.json"),
        "--policy", str(tmp_path / "policy.json"), "--package-lock", str(tmp_path / "package-lock.json"),
    ], env={**os.environ, "NPM_AUDIT_ALL_OUTCOME": "failure", "NPM_AUDIT_PROD_OUTCOME": "failure"}, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "report parse failure" in result.stdout


def test_skips_moderate_item_absent_from_lockfile(tmp_path):
    # R74: npm audit 会为 prune 掉的 optional/dev 嵌套树报 moderate
    # （实测 node-gyp 嵌套 undici 不在 lockfile）——moderate/low 缺节点
    # 按「未安装」跳过，门放行并打印跳过说明。
    report = npm_report(advisory="GHSA-1111-1111-1111", severity="moderate")
    report["vulnerabilities"]["electron"]["nodes"] = ["node_modules/node-gyp/node_modules/undici"]
    report["metadata"]["vulnerabilities"]["moderate"] = 1
    report["metadata"]["vulnerabilities"]["high"] = 0
    result = run_gate(
        tmp_path, npm=report, npm_prod=empty_npm(),
        NPM_AUDIT_ALL_OUTCOME="success", NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 0
    assert "absent from package-lock" in result.stdout
    assert "not covered by policy" not in result.stdout


def test_high_item_absent_from_lockfile_still_fails(tmp_path):
    # high/critical 缺节点无法核实 → 维持失败（宁可误报不可漏报）
    report = npm_report()
    report["vulnerabilities"]["electron"]["nodes"] = ["node_modules/ghost"]
    result = run_gate(tmp_path, npm=report, npm_prod=empty_npm())
    assert result.returncode == 1
    assert "nodes must exist in package-lock" in result.stdout


def test_rejects_package_lock_declared_name_mismatch(tmp_path):
    lock = package_lock_data()
    lock["packages"]["node_modules/electron"]["name"] = "not-electron"
    result = run_gate(
        tmp_path,
        package_lock=lock,
        npm=npm_report(),
        npm_prod=empty_npm(),
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 1
    assert "nodes must exist in package-lock" in result.stdout
    assert "not covered by policy" not in result.stdout


def _npm_exception(package, version, advisory, path):
    return {
        "source": "npm",
        "package": package,
        "package_version": version,
        "advisory": advisory,
        "advisory_url": f"https://github.com/advisories/{advisory}",
        "affected_path": path,
        "actual_reachability": "test",
        "controls": "test",
        "owner": "Sage maintainers",
        "review_by": "2099-01-01",
    }


def test_package_identity_from_node_handles_nested_paths():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_dependency_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.package_identity_from_node("node_modules/react") == "react"
    assert module.package_identity_from_node("node_modules/a/node_modules/b") == "b"
    assert module.package_identity_from_node("node_modules/a/node_modules/@scope/pkg") == "@scope/pkg"
    assert module.package_identity_from_node("node_modules/@scope/pkg") == "@scope/pkg"
    assert module.package_identity_from_node("packages/local") is None


def test_multi_version_npm_item_without_top_level_version(tmp_path):
    # npm 会把多版本漏洞（picomatch 2.x + 4.x 都受 <=4.0.7 影响）合并成一条
    # 无 version 字段的 item，nodes 跨顶层与嵌套路径。
    advisory = "GHSA-aaaa-bbbb-cccc"
    report = {
        "metadata": {
            "vulnerabilities": {"low": 0, "moderate": 0, "high": 1, "critical": 0}
        },
        "vulnerabilities": {
            "picomatch": {
                "name": "picomatch",
                "severity": "high",
                "nodes": [
                    "node_modules/picomatch",
                    "node_modules/anymatch/node_modules/picomatch",
                ],
                "via": [
                    {
                        "url": f"https://github.com/advisories/{advisory}",
                        "severity": "high",
                    }
                ],
            }
        },
    }
    lock = package_lock_data()
    lock["packages"]["node_modules/picomatch"] = {"version": "4.0.7"}
    lock["packages"]["node_modules/anymatch/node_modules/picomatch"] = {"version": "2.3.2"}
    policy = base_policy()
    policy["exceptions"].extend(
        [
            _npm_exception("picomatch", "4.0.7", advisory, "node_modules/picomatch"),
            _npm_exception(
                "picomatch", "2.3.2", advisory, "node_modules/anymatch/node_modules/picomatch"
            ),
        ]
    )
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_multi_version_item_keeps_per_version_policy_keys(tmp_path):
    # 只覆盖顶层 4.0.7 时，嵌套 2.3.2 必须仍然报 not covered（证明 findings
    # 按每个 node 的实际版本入 key，而不是任选一个版本）。
    advisory = "GHSA-aaaa-bbbb-cccc"
    report = {
        "metadata": {
            "vulnerabilities": {"low": 0, "moderate": 0, "high": 1, "critical": 0}
        },
        "vulnerabilities": {
            "picomatch": {
                "name": "picomatch",
                "severity": "high",
                "nodes": [
                    "node_modules/picomatch",
                    "node_modules/anymatch/node_modules/picomatch",
                ],
                "via": [
                    {
                        "url": f"https://github.com/advisories/{advisory}",
                        "severity": "high",
                    }
                ],
            }
        },
    }
    lock = package_lock_data()
    lock["packages"]["node_modules/picomatch"] = {"version": "4.0.7"}
    lock["packages"]["node_modules/anymatch/node_modules/picomatch"] = {"version": "2.3.2"}
    policy = base_policy()
    policy["exceptions"].append(
        _npm_exception("picomatch", "4.0.7", advisory, "node_modules/picomatch")
    )
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 1
    assert "package_version=2.3.2" in result.stdout
    assert "node_modules/anymatch/node_modules/picomatch" in result.stdout


def test_meta_chain_resolves_through_nested_node(tmp_path):
    # picomatch 的直接 advisory 位于嵌套路径时，依赖它的 meta 漏洞
    # （anymatch/vitest 等）必须能沿 chain 解析，而不是级联报错。
    advisory = "GHSA-dddd-eeee-ffff"
    report = {
        "metadata": {
            "vulnerabilities": {"low": 0, "moderate": 0, "high": 2, "critical": 0}
        },
        "vulnerabilities": {
            "anymatch": {
                "name": "anymatch",
                "severity": "high",
                "nodes": ["node_modules/anymatch"],
                "via": ["picomatch"],
            },
            "picomatch": {
                "name": "picomatch",
                "severity": "high",
                "nodes": ["node_modules/anymatch/node_modules/picomatch"],
                "via": [
                    {
                        "url": f"https://github.com/advisories/{advisory}",
                        "severity": "high",
                    }
                ],
            },
        },
    }
    lock = package_lock_data()
    lock["packages"]["node_modules/anymatch"] = {"version": "3.1.3"}
    lock["packages"]["node_modules/anymatch/node_modules/picomatch"] = {"version": "2.3.2"}
    policy = base_policy()
    policy["exceptions"].append(
        _npm_exception(
            "picomatch",
            "2.3.2",
            advisory,
            "node_modules/anymatch/node_modules/picomatch",
        )
    )
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lacks a matching valid advisory" not in result.stdout


def test_report_error_escapes_github_workflow_commands(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_dependency_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    failures = []
    module.report_error("percent%\r\n::warning::injected", failures)

    assert failures == ["percent%\r\n::warning::injected"]
    assert capsys.readouterr().out == "::error::percent%25%0D%0A::warning::injected\n"


    """Guard the standalone script's module-level annotations on Python 3.8."""
    py38 = Path("/home/fz/anaconda3/envs/sage-backend-py38/bin/python")
    if not py38.is_file():
        pytest.skip("Python 3.8 environment is unavailable")
    result = subprocess.run(
        [str(py38), str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validate dependency-audit reports" in result.stdout


def _nested_duplicate_fixture():
    """picomatch 顶层 4.0.7 + anymatch 嵌套副本 2.3.2 的最小复现。"""
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "sage", "version": "1.0.0"},
            "node_modules/picomatch": {"version": "4.0.7"},
            "node_modules/anymatch": {"version": "3.1.3"},
            "node_modules/anymatch/node_modules/picomatch": {"version": "2.3.2"},
        },
    }
    report = {
        "metadata": {
            "vulnerabilities": {"low": 0, "moderate": 0, "high": 2, "critical": 0}
        },
        "vulnerabilities": {
            "anymatch": {
                "name": "anymatch",
                "severity": "high",
                "nodes": ["node_modules/anymatch"],
                "via": ["picomatch"],
            },
            "picomatch": {
                "name": "picomatch",
                "severity": "high",
                "nodes": [
                    "node_modules/picomatch",
                    "node_modules/anymatch/node_modules/picomatch",
                ],
                "via": [
                    {
                        "url": "https://github.com/advisories/GHSA-nest-nest-nest",
                        "severity": "high",
                    }
                ],
            },
        },
    }
    return lock, report


def _nested_policy_entry(version: str, path: str):
    return {
        "source": "npm",
        "package": "picomatch",
        "package_version": version,
        "advisory": "GHSA-nest-nest-nest",
        "advisory_url": "https://github.com/advisories/GHSA-nest-nest-nest",
        "affected_path": path,
        "actual_reachability": "dev only",
        "controls": "test control",
        "owner": "Sage maintainers",
        "review_by": "2099-01-01",
    }


def test_allows_nested_duplicate_per_node_policy(tmp_path):
    lock, report = _nested_duplicate_fixture()
    policy = {
        "default_action": "fail",
        "exceptions": [
            _nested_policy_entry("4.0.7", "node_modules/picomatch"),
            _nested_policy_entry(
                "2.3.2", "node_modules/anymatch/node_modules/picomatch"
            ),
        ],
    }
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_nested_duplicate_missing_policy_entry(tmp_path):
    lock, report = _nested_duplicate_fixture()
    policy = {
        "default_action": "fail",
        "exceptions": [_nested_policy_entry("4.0.7", "node_modules/picomatch")],
    }
    result = run_gate(
        tmp_path,
        policy=policy,
        npm=report,
        npm_prod=empty_npm(),
        package_lock=lock,
        NPM_AUDIT_ALL_OUTCOME="success",
        NPM_AUDIT_PROD_OUTCOME="success",
    )
    assert result.returncode == 1
    assert "not covered by policy" in result.stdout
    assert "node_modules/anymatch/node_modules/picomatch" in result.stdout
