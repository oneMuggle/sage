"""audit_watch（round40/44）— 未覆盖发现求差的单元测试。

pip_findings / validate_policy 的匹配语义由 test_check_dependency_audit.py
覆盖；本文件只测 audit_watch 的差集、格式化与 CLI 退出码。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from audit_watch import uncovered_findings  # noqa: E402

SCRIPT = Path(__file__).parents[1] / "audit_watch.py"

MAIN_LABEL = "main Python 3.11 production path"
PY38_LABEL = "Win7 LTS Python 3.8 production path"

POLICY = {
    "default_action": "fail",
    "exceptions": [
        {
            "owner": "Sage maintainers",
            "review_by": "2027-01-01",
            "source": "pip",
            "package": "anyio",
            "package_version": "3.7.1",
            "advisory": "GHSA-82r6-8w77-94w6",
            "advisory_url": "https://osv.dev/vulnerability/GHSA-82r6-8w77-94w6",
            "affected_path": MAIN_LABEL,
            "actual_reachability": "not reachable (documented)",
            "controls": "quarterly review",
        },
    ],
}


def pip_report(name, version, advisory):
    # pip-audit 真实形态：vuln 至少含合法 id；aliases 可省略（空列表会被
    # 校验器判为无效）。
    return [
        {
            "name": name,
            "version": version,
            "vulns": [{"id": advisory}],
        }
    ]


def test_uncovered_empty_when_policy_covers():
    uncovered, all_findings, failures = uncovered_findings(
        [(MAIN_LABEL, pip_report("anyio", "3.7.1", "GHSA-82r6-8w77-94w6"))],
        POLICY,
    )
    assert failures == []
    assert uncovered == []
    assert len(all_findings) == 1


def test_uncovered_lists_finding_missing_from_policy():
    uncovered, _all, failures = uncovered_findings(
        [(MAIN_LABEL, pip_report("anyio", "3.7.1", "GHSA-5p39-cfhj-2xmp"))],
        POLICY,
    )
    assert failures == []
    assert len(uncovered) == 1
    src, package, version, advisory, affected = uncovered[0]
    assert (package, version, advisory) == (
        "anyio",
        "3.7.1",
        "GHSA-5p39-cfhj-2xmp",
    )
    assert affected == MAIN_LABEL


def test_uncovered_multi_report_relabels_py38_path():
    """round44: 同公告在不同报告里按标签区分 affected_path。"""
    reports = [
        (MAIN_LABEL, pip_report("anyio", "3.7.1", "GHSA-82r6-8w77-94w6")),
        (PY38_LABEL, pip_report("anyio", "3.7.1", "GHSA-82r6-8w77-94w6")),
    ]
    uncovered, _all, failures = uncovered_findings(reports, POLICY)
    assert failures == []
    # main 路径的发现被策略覆盖 → 未覆盖的只有 py38 标签那份
    assert len(uncovered) == 1
    assert uncovered[0][4] == PY38_LABEL


def test_cli_exit_2_and_writes_outputs(tmp_path):
    report = tmp_path / "pip-audit.json"
    policy = tmp_path / "policy.json"
    report.write_text(
        json.dumps(pip_report("anyio", "3.7.1", "GHSA-82r6-8w77-94w6")),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"default_action": "fail", "exceptions": []}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pip-report",
            f"{MAIN_LABEL}={report}",
            "--policy",
            str(policy),
            "--out",
            str(tmp_path / "uncovered.txt"),
            "--json-out",
            str(tmp_path / "uncovered.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert (tmp_path / "uncovered.txt").exists()
    data = json.loads((tmp_path / "uncovered.json").read_text(encoding="utf-8"))
    assert data[0]["advisory"] == "GHSA-82r6-8w77-94w6"


def test_cli_exit_0_when_clean(tmp_path):
    report = tmp_path / "pip-audit.json"
    policy = tmp_path / "policy.json"
    report.write_text(json.dumps([]), encoding="utf-8")
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pip-report",
            f"{MAIN_LABEL}={report}",
            "--policy",
            str(policy),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0


@pytest.mark.parametrize("missing", ["pip", "policy"])
def test_cli_exit_1_on_missing_input(tmp_path, missing):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    report = tmp_path / "pip-audit.json"
    report.write_text("[]", encoding="utf-8")
    args = [
        sys.executable,
        str(SCRIPT),
        "--pip-report",
        (
            f"{MAIN_LABEL}={report}"
            if missing != "pip"
            else f"{MAIN_LABEL}={tmp_path / 'nope.json'}"
        ),
        "--policy",
        str(policy) if missing != "policy" else str(tmp_path / "nope.json"),
    ]
    proc = subprocess.run(args, capture_output=True, text=True)
    assert proc.returncode == 1
