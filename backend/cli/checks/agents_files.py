"""检查 .sage/agents/*.md 子代理档案文件的结构合法性（CA3, round9）。

诊断:文件化档案（对标 Claude Code .claude/agents）frontmatter 缺字段、
未闭合、正文为空等问题会在派发时才失败。本 check 启动期提前发现。

stdlib-only（doctor 纪律,不 import backend.agents——复刻最小 frontmatter
结构检查:闭合 + 每行含冒号 + 正文非空）。字段取值合法性（工具名等）由
启动期 validate_profile_tools 覆盖,此处不重复。
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register


def _agents_dir() -> Path:
    env = os.environ.get("SAGE_AGENTS_DIR", "").strip()
    if env:
        return Path(env)
    return Path.cwd() / os.path.join(".sage", "agents")


@register
class AgentsFilesCheck:
    name = "agents_files"
    description = ".sage/agents/*.md 子代理档案文件结构"

    def run(self) -> CheckResult:
        directory = _agents_dir()
        if not directory.is_dir():
            return CheckResult(
                self.name,
                Severity.INFO,
                f"无文件化子代理档案（{directory} 不存在，属正常）",
            )
        files = sorted(directory.glob("*.md"))
        if not files:
            return CheckResult(
                self.name, Severity.INFO, f"{directory} 下没有 *.md 档案"
            )
        problems = []
        parsed = 0
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                problems.append(f"{path.name}: 读取失败 {exc.__class__.__name__}")
                continue
            lines = text.splitlines()
            idx = 0
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
            if idx >= len(lines) or lines[idx].strip() != "---":
                problems.append(f"{path.name}: 缺少 frontmatter（应以 --- 开头）")
                continue
            closed = False
            for inner in range(idx + 1, len(lines)):
                if lines[inner].strip() == "---":
                    closed = True
                    body_start = inner + 1
                    break
            if not closed:
                problems.append(f"{path.name}: frontmatter 未闭合（缺少第二个 ---）")
                continue
            body = "\n".join(lines[body_start:]).strip()
            if not body:
                problems.append(f"{path.name}: system prompt 正文为空")
                continue
            for line in lines[idx + 1 : body_start - 1]:
                stripped = line.strip()
                if stripped and ":" not in stripped and not stripped.startswith("#"):
                    problems.append(f"{path.name}: frontmatter 行缺少冒号: {stripped!r}")
                    break
            else:
                parsed += 1
        if problems:
            return CheckResult(
                self.name,
                Severity.WARN,
                f"{len(problems)} 个档案文件结构异常（{parsed} 个正常）: "
                + "; ".join(problems[:3]),
                f"检查 {directory} 下对应文件的 frontmatter 格式",
            )
        return CheckResult(
            self.name,
            Severity.INFO,
            f"{parsed} 个档案文件结构正常",
        )
