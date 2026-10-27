"""`project_profiler` 单元测试（2026-10-27）。

重点覆盖：
- 敏感路径排除（.env / secrets / *.pem / id_rsa / credentials）
- 采样上限（8 文件 × 120 行）
- 路径穿越防护
- 各维度采集正确性
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.project_profiler import (  # noqa: E402
    MAX_SAMPLE_FILES,
    MAX_SAMPLE_LINES,
    is_sensitive_path,
    profile_project,
)


def _make_project(root: Path, files: dict) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


# ── 敏感路径判定 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "secrets",
        "secrets/db.pem",
        "config/id_rsa",
        "credentials.json",
        "app/.credentials.yaml",
        "certs/server.key",
        "certs/server.p12",
        "deploy/id_ed25519",
    ],
)
def test_sensitive_paths_detected(path: str) -> None:
    assert is_sensitive_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "backend/main.py", "docs/readme.md", "a/b/notes.txt"],
)
def test_normal_paths_not_sensitive(path: str) -> None:
    assert is_sensitive_path(path) is False


# ── 采样约束 ────────────────────────────────────────────────────────────────


def test_source_samples_exclude_sensitive_files(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        {
            "src/app.py": "print('ok')\n",
            "config/.env": "SECRET=1\n",
            "secrets/token.py": "TOKEN='x'\n",
            "certs/key.pem": "-----BEGIN PRIVATE KEY-----\n",
            "home/credentials.json": "{}\n",
        },
    )

    profile = profile_project(tmp_path)
    sampled = [sample.path for sample in profile.source_samples]

    assert sampled, "应至少采到一个源文件"
    for path in sampled:
        assert ".env" not in path
        assert "secrets" not in path
        assert ".pem" not in path
        assert "credentials" not in path


def test_source_samples_respect_file_and_line_limits(tmp_path: Path) -> None:
    body = "\n".join(f"line {index}" for index in range(500))
    files = {f"src/module_{index}.py": body for index in range(20)}
    _make_project(tmp_path, files)

    profile = profile_project(tmp_path)

    assert len(profile.source_samples) <= MAX_SAMPLE_FILES
    for sample in profile.source_samples:
        assert sample.lines <= MAX_SAMPLE_LINES
        assert len(sample.content.splitlines()) <= MAX_SAMPLE_LINES


def test_symlink_outside_root_is_not_sampled(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}_outside"
    outside.mkdir(exist_ok=True)
    (outside / "leak.py").write_text("SECRET = 1\n", encoding="utf-8")

    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    try:
        (root / "src" / "escape.py").symlink_to(outside / "leak.py")
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不支持符号链接")

    profile = profile_project(root)
    sampled = [sample.path for sample in profile.source_samples]

    assert all("escape.py" not in path for path in sampled)


# ── 各维度采集 ──────────────────────────────────────────────────────────────


def test_profile_detects_types_and_stack(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        {
            "package.json": json.dumps(
                {
                    "scripts": {"build": "vite build", "test": "vitest"},
                    "dependencies": {"react": "^18", "electron": "^28"},
                }
            ),
            "src/main.tsx": "export const App = () => null;\n",
        },
    )

    profile = profile_project(tmp_path)

    assert profile.level1_type == "coding"
    assert profile.sub_type == "desktop_app"
    assert "react" in profile.tech_stack
    assert "electron" in profile.frameworks
    assert "npm run build" in profile.build_commands
    assert "npm run test" in profile.build_commands


def test_profile_collects_rules_lint_and_ci(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        {
            "AGENTS.md": "rules\n",
            "CLAUDE.md": "rules\n",
            ".cursorrules": "rules\n",
            ".github/workflows/ci.yml": "name: ci\n",
            "eslint.config.js": "export default [];\n",
            "tsconfig.json": "{}\n",
        },
    )

    profile = profile_project(tmp_path)

    assert "AGENTS.md" in profile.existing_rule_files
    assert "CLAUDE.md" in profile.existing_rule_files
    assert ".cursorrules" in profile.existing_rule_files
    assert ".github/workflows/ci.yml" in profile.ci_workflows
    assert "eslint.config.js" in profile.lint_configs
    assert "tsconfig.json" in profile.lint_configs


def test_profile_on_missing_directory_is_empty(tmp_path: Path) -> None:
    profile = profile_project(tmp_path / "does-not-exist")

    assert profile.level1_type is None
    assert profile.source_samples == []
    assert profile.git_stats.is_repo is False


def test_profile_on_empty_directory(tmp_path: Path) -> None:
    profile = profile_project(tmp_path)

    assert profile.level1_type is None
    assert profile.tech_stack == []
    assert profile.source_samples == []


def test_to_dict_can_omit_source_content(tmp_path: Path) -> None:
    _make_project(tmp_path, {"src/app.py": "x = 1\n"})

    profile = profile_project(tmp_path)
    with_content = profile.to_dict(include_source_content=True)
    without_content = profile.to_dict(include_source_content=False)

    assert with_content["source_samples"][0]["content"]
    assert "content" not in without_content["source_samples"][0]
