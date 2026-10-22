"""SKILL.md importer / writer 专属异常。"""

from __future__ import annotations


class NoSkillsDirError(RuntimeError):
    """无法解析或创建 skills_dir(SAGE_SKILLS_DIR / ~/.sage/skills 都不可用)。"""


class WriteFailedError(OSError):
    """写 SKILL.md 时底层 OSError (PermissionError / DiskFull / 等)。"""


class ImportValidationError(ValueError):
    """name 不符合 slug、frontmatter 缺字段等单文件校验失败。"""


class SkillDirectoryImportError(RuntimeError):
    """技能目录导入的前置校验失败（缺 SKILL.md / 入口文件不合法）。

    ``error_type`` 是稳定的错误分类码，路由层原样透出到 ``detail.type``；
    ``message`` 是面向用户的中文说明，不得包含上传内容或本机绝对路径。
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
