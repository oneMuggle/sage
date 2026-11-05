"""项目模板系统单元测试（P1 of 2026-11-05 设计）。

覆盖三个来源加载、优先级解析、脚手架执行、变量替换、路径安全、
dry_run 模式、overwrite 行为。
"""

from __future__ import annotations

import json

import pytest

from backend.services.project_template import (
    ProjectTemplate,
    ScaffoldResult,
    TemplateDirectory,
    TemplateFile,
    get_built_in_templates,
    load_global_templates,
    load_project_template,
    resolve_template,
    save_project_template,
    scaffold_project,
)

# ─────────────────────────────────────────────────────────────────────
# 数据模型：构造与校验
# ─────────────────────────────────────────────────────────────────────


class TestTemplateDirectory:
    """TemplateDirectory 构造与校验。"""

    def test_valid_construction(self):
        d = TemplateDirectory(path="src", desc="源代码", role="folder")
        assert d.path == "src"
        assert d.desc == "源代码"
        assert d.role == "folder"

    def test_project_role(self):
        d = TemplateDirectory(path="cases", desc="子项目", role="project")
        assert d.role == "project"

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError, match="role must be"):
            TemplateDirectory(path="src", role="invalid")

    def test_path_escape_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            TemplateDirectory(path="../escape", role="folder")

    def test_empty_path_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            TemplateDirectory(path="", role="folder")


class TestTemplateFile:
    """TemplateFile 构造与校验。"""

    def test_valid_construction(self):
        f = TemplateFile(path="SAGE.md", content="# Test", overwrite=False)
        assert f.path == "SAGE.md"
        assert f.content == "# Test"
        assert f.overwrite is False

    def test_content_and_template_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            TemplateFile(path="SAGE.md", content="A", template="B")

    def test_template_alone_is_ok(self):
        f = TemplateFile(path="SAGE.md", template="sage_md")
        assert f.template == "sage_md"
        assert f.content == ""

    def test_path_escape_rejected(self):
        with pytest.raises(ValueError, match="unsafe"):
            TemplateFile(path="../../etc/passwd", content="x")


class TestProjectTemplate:
    """ProjectTemplate 序列化与反序列化。"""

    def test_round_trip(self):
        tpl = ProjectTemplate(
            name="测试模板",
            description="一句话说明",
            version=2,
            directories=[
                TemplateDirectory(path="src", desc="源代码", role="folder"),
                TemplateDirectory(path="cases", desc="子项目", role="project"),
            ],
            files=[
                TemplateFile(path="SAGE.md", content="# {{project_name}}", overwrite=False),
            ],
            built_in=False,
            source="global",
        )
        data = tpl.to_dict()
        assert data["name"] == "测试模板"
        assert data["version"] == 2
        assert len(data["directories"]) == 2
        assert data["directories"][1]["role"] == "project"

        # 反序列化（不含 built_in/source 元信息，由 from_dict 参数控制）
        restored = ProjectTemplate.from_dict(data, source="global")
        assert restored.name == "测试模板"
        assert restored.source == "global"
        assert restored.directories[1].role == "project"

    def test_from_json_valid(self):
        text = json.dumps(
            {
                "name": "Test",
                "version": 1,
                "directories": [{"path": "src", "role": "folder"}],
                "files": [{"path": "README.md", "content": "hello"}],
            }
        )
        tpl = ProjectTemplate.from_json(text)
        assert tpl.name == "Test"
        assert len(tpl.directories) == 1
        assert tpl.files[0].content == "hello"

    def test_from_json_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid template JSON"):
            ProjectTemplate.from_json("not json")

    def test_from_json_non_object_raises(self):
        with pytest.raises(ValueError, match="must be an object"):
            ProjectTemplate.from_json("[]")

    def test_from_dict_missing_optional_fields(self):
        """宽容解析：缺失可选字段用默认值。"""
        data = {"name": "Minimal", "directories": [{"path": "x"}]}
        tpl = ProjectTemplate.from_dict(data)
        assert tpl.description == ""
        assert tpl.version == 1
        assert tpl.directories[0].desc == ""
        assert tpl.directories[0].role == "folder"

    def test_from_dict_ignores_unknown_fields(self):
        data = {"name": "Test", "unknown_field": "ignored", "directories": []}
        tpl = ProjectTemplate.from_dict(data)
        assert tpl.name == "Test"


# ─────────────────────────────────────────────────────────────────────
# 模板变量替换
# ─────────────────────────────────────────────────────────────────────


class TestRenderContent:
    """render_content 白名单变量替换。"""

    def test_project_name_substitution(self):
        tpl = ProjectTemplate(name="T")
        result = tpl.render_content("# {{project_name}}", "my-cfd-project")
        assert result == "# my-cfd-project"

    def test_date_substitution(self):
        tpl = ProjectTemplate(name="T")
        result = tpl.render_content("Date: {{date}}", "x")
        # 日期格式 YYYY-MM-DD
        assert "Date: " in result
        parts = result.split("Date: ", 1)[1]
        assert len(parts) == 10  # YYYY-MM-DD
        assert parts[4] == "-"
        assert parts[7] == "-"

    def test_datetime_substitution(self):
        tpl = ProjectTemplate(name="T")
        result = tpl.render_content("TS: {{datetime}}", "x")
        ts = result.split("TS: ", 1)[1]
        # YYYY-MM-DD HH:MM:SS
        assert len(ts) == 19
        assert ts[10] == " "
        assert ts[13] == ":"
        assert ts[16] == ":"

    def test_user_substitution(self):
        tpl = ProjectTemplate(name="T")
        result = tpl.render_content("User: {{user}}", "x")
        # 至少能替换，不为空
        assert "User: " in result
        assert "{{user}}" not in result

    def test_no_expression_injection(self):
        """白名单替换不执行表达式，{{eval}} 等不被解释。"""
        tpl = ProjectTemplate(name="T")
        result = tpl.render_content("{{eval('1+1')}}", "x")
        assert result == "{{eval('1+1')}}"  # 未替换


# ─────────────────────────────────────────────────────────────────────
# 三来源加载
# ─────────────────────────────────────────────────────────────────────


class TestLoadGlobalTemplates:
    """load_global_templates 从 ~/.sage/templates/ 加载。"""

    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR",
            tmp_path / "nonexistent",
        )
        assert load_global_templates() == []

    def test_loads_valid_templates(self, tmp_path, monkeypatch):
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "a.json").write_text(
            json.dumps({"name": "A", "directories": [], "files": []}), encoding="utf-8"
        )
        (tpl_dir / "b.json").write_text(
            json.dumps({"name": "B", "directories": [{"path": "x"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR", tpl_dir
        )
        result = load_global_templates()
        assert len(result) == 2
        assert {t.name for t in result} == {"A", "B"}
        assert all(t.source == "global" for t in result)

    def test_skips_invalid_json(self, tmp_path, monkeypatch):
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "good.json").write_text(
            json.dumps({"name": "Good"}), encoding="utf-8"
        )
        (tpl_dir / "bad.json").write_text("not json", encoding="utf-8")
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR", tpl_dir
        )
        result = load_global_templates()
        assert len(result) == 1
        assert result[0].name == "Good"

    def test_skips_non_json_files(self, tmp_path, monkeypatch):
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "readme.txt").write_text("not a template", encoding="utf-8")
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR", tpl_dir
        )
        assert load_global_templates() == []


class TestLoadProjectTemplate:
    """load_project_template 从 <root>/.sage/template.json 加载。"""

    def test_returns_none_when_missing(self, tmp_path):
        assert load_project_template(tmp_path) is None

    def test_loads_valid(self, tmp_path):
        tpl_dir = tmp_path / ".sage"
        tpl_dir.mkdir()
        (tpl_dir / "template.json").write_text(
            json.dumps({"name": "ProjectTpl", "version": 3}), encoding="utf-8"
        )
        tpl = load_project_template(tmp_path)
        assert tpl is not None
        assert tpl.name == "ProjectTpl"
        assert tpl.version == 3
        assert tpl.source == "project"

    def test_returns_none_on_invalid_json(self, tmp_path):
        tpl_dir = tmp_path / ".sage"
        tpl_dir.mkdir()
        (tpl_dir / "template.json").write_text("broken", encoding="utf-8")
        assert load_project_template(tmp_path) is None


class TestSaveProjectTemplate:
    """save_project_template 写入 .sage/template.json。"""

    def test_writes_json(self, tmp_path):
        tpl = ProjectTemplate(
            name="Saved",
            directories=[TemplateDirectory(path="src")],
        )
        target = save_project_template(tmp_path, tpl)
        assert target == tmp_path / ".sage" / "template.json"
        assert target.exists()

        # 内容可被反序列化
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["name"] == "Saved"
        assert data["directories"][0]["path"] == "src"

    def test_creates_parent_dir(self, tmp_path):
        tpl = ProjectTemplate(name="X")
        target = save_project_template(tmp_path, tpl)
        assert (tmp_path / ".sage").is_dir()
        assert target.exists()


# ─────────────────────────────────────────────────────────────────────
# 优先级解析
# ─────────────────────────────────────────────────────────────────────


class TestResolveTemplate:
    """resolve_template 优先级：项目内 > 全局 > 内置 > 兜底。"""

    def test_project_template_wins(self, tmp_path, monkeypatch):
        # 项目内模板
        (tmp_path / ".sage").mkdir()
        (tmp_path / ".sage" / "template.json").write_text(
            json.dumps({"name": "ProjectWins"}), encoding="utf-8"
        )
        # 全局模板（优先级较低）
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "a.json").write_text(
            json.dumps({"name": "GlobalTpl"}), encoding="utf-8"
        )
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR", global_dir
        )

        tpl = resolve_template("coding", project_root=tmp_path)
        assert tpl.name == "ProjectWins"

    def test_global_template_over_builtin(self, tmp_path, monkeypatch):
        """无项目内模板时，全局按 name 匹配优先于内置。"""
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "custom.json").write_text(
            json.dumps({"name": "MyCustom"}), encoding="utf-8"
        )
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR", global_dir
        )
        tpl = resolve_template(None, template_name="MyCustom")
        assert tpl.name == "MyCustom"

    def test_builtin_by_project_type(self, tmp_path, monkeypatch):
        """无项目内也无全局匹配时，按 project_type 返回内置。"""
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR",
            tmp_path / "empty_global",
        )
        tpl = resolve_template("coding")
        assert tpl.source == "built_in"
        assert tpl.name == "代码工程项目"

    def test_fallback_to_business(self, tmp_path, monkeypatch):
        """未知 project_type 兜底到 business 内置模板。"""
        monkeypatch.setattr(
            "backend.services.project_template.GLOBAL_TEMPLATE_DIR",
            tmp_path / "empty_global",
        )
        tpl = resolve_template("unknown_type")
        assert tpl.name == "一般档案与文书项目"


# ─────────────────────────────────────────────────────────────────────
# 内置模板泛化
# ─────────────────────────────────────────────────────────────────────


class TestBuiltInTemplates:
    """get_built_in_templates 从 ARCHETYPE_BLUEPRINTS 泛化。"""

    def test_returns_all_four_types(self):
        tpls = get_built_in_templates()
        assert set(tpls.keys()) == {"coding", "business", "research", "personal"}

    def test_all_are_built_in(self):
        for tpl in get_built_in_templates().values():
            assert tpl.built_in is True
            assert tpl.source == "built_in"

    def test_coding_has_hooks_file(self):
        """coding 类型应包含 .sage/hooks.json 初始文件。"""
        tpl = get_built_in_templates()["coding"]
        hooks_files = [f for f in tpl.files if f.path == ".sage/hooks.json"]
        assert len(hooks_files) == 1

    def test_each_has_sage_md(self):
        """每个内置模板都生成 SAGE.md 文件。"""
        for tpl in get_built_in_templates().values():
            sage_files = [f for f in tpl.files if f.path == "SAGE.md"]
            assert len(sage_files) == 1, f"Template {tpl.name} missing SAGE.md"


# ─────────────────────────────────────────────────────────────────────
# 脚手架执行
# ─────────────────────────────────────────────────────────────────────


class TestScaffoldProject:
    """scaffold_project 目录/文件创建、幂等性、dry_run。"""

    def _make_template(self):
        return ProjectTemplate(
            name="TestTpl",
            description="测试",
            directories=[
                TemplateDirectory(path="src", desc="源代码", role="folder"),
                TemplateDirectory(path="cases", desc="子项目", role="project"),
            ],
            files=[
                TemplateFile(
                    path="SAGE.md",
                    content="# {{project_name}}\nCreated: {{date}}",
                    overwrite=False,
                ),
                TemplateFile(
                    path="src/main.py",
                    content="# {{project_name}} entry point",
                    overwrite=False,
                ),
            ],
        )

    def test_creates_directories_and_files(self, tmp_path):
        tpl = self._make_template()
        result = scaffold_project(tpl, tmp_path, "my-project")

        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "cases").is_dir()
        assert (tmp_path / "SAGE.md").exists()
        assert (tmp_path / "src" / "main.py").exists()

        # 变量替换生效
        sage_content = (tmp_path / "SAGE.md").read_text(encoding="utf-8")
        assert "# my-project" in sage_content
        assert "Created: " in sage_content

        # 结果对象
        assert result.template_name == "TestTpl"
        assert set(result.created_directories) == {"src", "cases"}
        assert "SAGE.md" in result.created_files
        assert "src/main.py" in result.created_files
        assert result.dry_run is False

    def test_writes_project_template_json(self, tmp_path):
        tpl = self._make_template()
        scaffold_project(tpl, tmp_path, "proj")

        tpl_path = tmp_path / ".sage" / "template.json"
        assert tpl_path.exists()
        data = json.loads(tpl_path.read_text(encoding="utf-8"))
        assert data["name"] == "TestTpl"

    def test_idempotent_no_overwrite(self, tmp_path):
        """overwrite=False 时不覆盖已存在的文件/目录。"""
        tpl = self._make_template()
        # 预先创建一些目标
        (tmp_path / "src").mkdir()
        (tmp_path / "SAGE.md").write_text("# original", encoding="utf-8")

        result = scaffold_project(tpl, tmp_path, "proj")

        assert "src" in result.skipped_directories  # 已存在
        assert "SAGE.md" in result.skipped_files  # 已存在
        assert (tmp_path / "SAGE.md").read_text(encoding="utf-8") == "# original"  # 未被覆盖

    def test_overwrite_true_replaces(self, tmp_path):
        """overwrite=True 时覆盖已存在的文件。"""
        tpl = ProjectTemplate(
            name="ForceTpl",
            files=[
                TemplateFile(path="SAGE.md", content="# forced", overwrite=True),
            ],
        )
        (tmp_path / "SAGE.md").write_text("# original", encoding="utf-8")

        scaffold_project(tpl, tmp_path, "proj")
        assert (tmp_path / "SAGE.md").read_text(encoding="utf-8") == "# forced"

    def test_dry_run_does_not_write(self, tmp_path):
        tpl = self._make_template()
        result = scaffold_project(tpl, tmp_path, "proj", dry_run=True)

        # 文件/目录都不应被创建
        assert not (tmp_path / "src").exists()
        assert not (tmp_path / "SAGE.md").exists()
        assert not (tmp_path / ".sage").exists()

        # 但结果对象记录了"将会创建"
        assert len(result.created_directories) == 2
        assert len(result.created_files) >= 2
        assert result.dry_run is True

    def test_raises_on_missing_root(self, tmp_path):
        tpl = self._make_template()
        with pytest.raises(ValueError, match="does not exist"):
            scaffold_project(tpl, tmp_path / "nonexistent", "proj")

    def test_path_escape_rejected_at_construction(self, tmp_path):
        """路径中含 .. 的条目在构造时被拒绝（一级防线）。"""
        with pytest.raises(ValueError, match="unsafe"):
            TemplateDirectory(path="../escape", role="folder")
        with pytest.raises(ValueError, match="unsafe"):
            TemplateFile(path="../../etc/passwd", content="x")

        # 即使构造失败被绕过（如 from_dict 宽容解析），scaffold 仍有二级防线跳过
        # 这里通过直接调用 scaffold_project 并跳过构造验证来测试二级防线
        # 但这需要绕过 dataclass 验证，实践中不常见，因此我们只测构造拒绝
        tpl = ProjectTemplate(name="SafeTpl")
        result = scaffold_project(tpl, tmp_path, "proj")
        assert result.created_directories == []
        assert result.created_files == [".sage/template.json"]

    def test_skip_write_project_template(self, tmp_path):
        tpl = self._make_template()
        result = scaffold_project(tpl, tmp_path, "proj", write_project_template=False)
        assert not (tmp_path / ".sage" / "template.json").exists()
        assert ".sage/template.json" not in result.created_files

    def test_existing_project_template_not_overwritten(self, tmp_path):
        """已有 .sage/template.json 时不覆盖（幂等）。"""
        (tmp_path / ".sage").mkdir()
        existing = tmp_path / ".sage" / "template.json"
        existing.write_text('{"name": "existing"}', encoding="utf-8")

        tpl = self._make_template()
        result = scaffold_project(tpl, tmp_path, "proj")

        # 内容应保持原有
        data = json.loads(existing.read_text(encoding="utf-8"))
        assert data["name"] == "existing"
        assert ".sage/template.json" in result.skipped_files


class TestScaffoldResult:
    """ScaffoldResult.to_dict 序列化。"""

    def test_to_dict(self):
        r = ScaffoldResult(
            template_name="T",
            created_directories=["src"],
            created_files=["SAGE.md"],
            skipped_directories=["docs"],
            skipped_files=[],
            dry_run=False,
        )
        d = r.to_dict()
        assert d["template_name"] == "T"
        assert d["created_directories"] == ["src"]
        assert d["dry_run"] is False
