# ruff: noqa: UP006, UP007, UP035
"""Plugin scaffold templates and manifest rendering (R86).

Generated plugins depend only on the Python standard library.  This module
contains data and pure rendering helpers; package validation and dev execution
live in :mod:`backend.plugins.scaffold`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.plugins.manifest import (
    CapabilityType,
    PluginCapability,
    PluginManifest,
    PluginMetadata,
    PluginType,
)

TEMPLATE_NAMES: Tuple[str, ...] = ("tool", "hook", "mcp", "skill")

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "tool": {
        "name": "tool",
        "capability_type": CapabilityType.TOOL.value,
        "maturity": "supported",
        "description": "Python tool hosted by the R83 out-of-process runtime.",
    },
    "hook": {
        "name": "hook",
        "capability_type": CapabilityType.HOOK.value,
        "maturity": "preview",
        "description": "Hook contract starter; the current host does not execute hooks.",
    },
    "mcp": {
        "name": "mcp",
        "capability_type": CapabilityType.MCP_SERVER.value,
        "maturity": "preview",
        "description": "Dependency-free stdio MCP server starter; register it manually.",
    },
    "skill": {
        "name": "skill",
        "capability_type": CapabilityType.SKILL.value,
        "maturity": "preview",
        "description": "SKILL.md content package; place the skill in a Sage skill root.",
    },
}

_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*$")


class PluginEcosystemError(Exception):
    """Stable ecosystem error for CLI and API-style callers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": False,
            "error": self.code,
            "detail": self.message,
            "status_code": self.status_code,
        }
        payload.update(self.details)
        return payload


@dataclass(frozen=True)
class ScaffoldOptions:
    """Inputs for one plugin scaffold operation."""

    name: str
    output_dir: Optional[Path] = None
    template: str = "tool"
    display_name: Optional[str] = None
    author: str = ""
    description: Optional[str] = None
    version: str = "0.1.0"
    force: bool = False


@dataclass(frozen=True)
class ScaffoldResult:
    """Files written by :func:`scaffold_plugin`."""

    root: Path
    manifest: PluginManifest
    template: str
    files: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "root": str(self.root),
            "template": dict(_TEMPLATES[self.template]),
            "plugin": self.manifest.to_dict(),
            "files": list(self.files),
        }


def list_templates() -> List[Dict[str, str]]:
    """Return the available scaffold templates in stable order."""

    return [dict(_TEMPLATES[name]) for name in TEMPLATE_NAMES]


def _title_from_name(name: str) -> str:
    words = [part for part in re.split(r"[-_]+", name) if part]
    return " ".join(word[:1].upper() + word[1:] for word in words) or "Sage Plugin"


def _identifier(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if value and value[0].isdigit():
        value = "plugin_" + value
    return value or "sage_plugin"


def _manifest_for_template(options: ScaffoldOptions) -> PluginManifest:
    template = options.template.strip().lower()
    if template not in _TEMPLATES:
        raise PluginEcosystemError(
            "UNKNOWN_PLUGIN_TEMPLATE",
            f"unknown plugin template: {options.template!r}",
            status_code=422,
            details={"templates": list_templates()},
        )

    raw_name = options.name.strip().lower()
    identifier = _identifier(raw_name)
    skill_slug = raw_name.replace("_", "-")
    display_name = (options.display_name or "").strip() or _title_from_name(raw_name)
    description = (options.description or "").strip() or f"A Sage {template} plugin."

    if template == "tool":
        capability = PluginCapability(
            type=CapabilityType.TOOL,
            name=identifier,
            description=f"Run the {display_name} tool.",
            version=options.version,
            entry_point="handlers:run",
            permissions=[],
            config_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "World"},
                },
                "additionalProperties": True,
            },
        )
        user_config: Optional[Dict[str, Any]] = {
            "type": "object",
            "properties": {
                "greeting": {"type": "string", "default": "Hello"},
            },
            "additionalProperties": False,
        }
    elif template == "hook":
        capability = PluginCapability(
            type=CapabilityType.HOOK,
            name=f"{identifier}_hook",
            description=f"Handle a {display_name} lifecycle event.",
            version=options.version,
            entry_point="handlers:on_event",
            permissions=[],
            config_schema={
                "type": "object",
                "properties": {
                    "event": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": True,
            },
        )
        user_config = None
    elif template == "mcp":
        capability = PluginCapability(
            type=CapabilityType.MCP_SERVER,
            name=f"{identifier}_mcp",
            description=f"Run the {display_name} stdio MCP server.",
            version=options.version,
            entry_point="server.py",
            permissions=[],
        )
        user_config = None
    else:
        capability = PluginCapability(
            type=CapabilityType.SKILL,
            name=skill_slug,
            description=f"Use the {display_name} skill.",
            version=options.version,
            entry_point=f"skills/{skill_slug}/SKILL.md",
            permissions=[],
        )
        user_config = None

    try:
        return PluginManifest(
            schema_version="1.0",
            name=raw_name,
            version=options.version,
            type=PluginType.PERSONAL,
            metadata=PluginMetadata(
                display_name=display_name,
                description=description,
                author=options.author.strip(),
                license="MIT",
                categories=[template],
                tags=["sage-plugin", template],
            ),
            capabilities=[capability],
            dependencies=[],
            min_sage_version="0.4.0",
            python_version=">=3.8",
            hooks=[],
            user_config=user_config,
        )
    except (TypeError, ValueError) as exc:
        raise PluginEcosystemError(
            "INVALID_SCAFFOLD_OPTIONS",
            str(exc),
            status_code=422,
        ) from exc


def _render_readme(manifest: PluginManifest, template: str) -> str:
    display_name = manifest.metadata.display_name
    maturity = _TEMPLATES[template]["maturity"]
    lines = [
        f"# {display_name}",
        "",
        manifest.metadata.description,
        "",
        f"- Plugin: `{manifest.name}`",
        f"- Version: `{manifest.version}`",
        f"- Template: `{template}` ({maturity})",
        "",
        "## Validate in a Sage checkout",
        "",
        "```bash",
        f"python -m backend.cli.plugin validate /path/to/{manifest.name} --strict",
        "```",
        "",
    ]
    if template == "tool":
        lines.extend(
            [
                "## Run the out-of-process smoke test",
                "",
                "```bash",
                f"python -m backend.cli.plugin dev /path/to/{manifest.name} \\",
                f"  --arguments-file /path/to/{manifest.name}/examples/request.json",
                "```",
                "",
                "Installing or enabling a lifecycle record never executes this code. "
                "The runtime starts only through an explicit dev/UI/API action.",
                "",
            ]
        )
    elif template == "mcp":
        lines.extend(
            [
                "## Register the stdio server manually",
                "",
                "Use your MCP client's command configuration with this directory as "
                "the working directory:",
                "",
                "```text",
                "python server.py",
                "```",
                "",
                "The Sage plugin lifecycle can record this package, but the R83 host "
                "does not launch MCP-server capabilities.",
                "",
            ]
        )
    elif template == "skill":
        skill_slug = manifest.name.replace("_", "-")
        lines.extend(
            [
                "## Use the skill",
                "",
                f"Copy or link `skills/{skill_slug}` into a Sage skill root, then run "
                "`python -m backend.cli.skills lint <skill-root>` from a Sage checkout.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Runtime status",
                "",
                "This is a contract-preview template. Sage validates and records the "
                "manifest, but the R83 out-of-process host currently executes only "
                "Python tool capabilities.",
                "",
            ]
        )
    lines.extend(
        [
            "## Test without Sage",
            "",
            "```bash",
            "python -m pytest",
            "```",
            "",
            "Keep declared permissions minimal. A permission declaration is an "
            "install-review and audit contract, not an operating-system sandbox.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_files(
    options: ScaffoldOptions,
    manifest: PluginManifest,
) -> Dict[str, str]:
    template = options.template.strip().lower()
    identifier = _identifier(manifest.name)
    skill_slug = manifest.name.replace("_", "-")
    files: Dict[str, str] = {
        "plugin.json": manifest.to_json(indent=2) + "\n",
        "README.md": _render_readme(manifest, template),
        ".gitignore": "__pycache__/\n.pytest_cache/\n*.py[cod]\n",
        ".github/workflows/plugin-ci.yml": (
            "name: Plugin CI\n\n"
            "on:\n"
            "  push:\n"
            "  pull_request:\n\n"
            "jobs:\n"
            "  test:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            "          python-version: '3.11'\n"
            "      - run: python -m pip install pytest\n"
            "      - run: python -m json.tool plugin.json > /dev/null\n"
            "      - run: python -m pytest\n"
        ),
    }

    if template == "tool":
        files["handlers.py"] = (
            '"""Tool handlers for the '
            + manifest.name
            + ' Sage plugin."""\n\n'
            "from typing import Any, Dict, Optional\n\n"
            "_CONFIG: Dict[str, Any] = {}\n\n\n"
            "def configure(config: Dict[str, Any]) -> None:\n"
            '    """Receive lifecycle config before the worker serves calls."""\n'
            "    _CONFIG.clear()\n"
            "    _CONFIG.update(config or {})\n\n\n"
            "def run(arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n"
            '    """Return a JSON-serializable greeting."""\n'
            "    payload = arguments if isinstance(arguments, dict) else {}\n"
            '    name = str(payload.get("name") or "World")\n'
            '    greeting = str(_CONFIG.get("greeting") or "Hello")\n'
            "    return {\n"
            '        "message": "{}, {}!".format(greeting, name),\n'
            f'        "plugin": "{manifest.name}",\n'
            '        "template": "tool",\n'
            "    }\n"
        )
        files["examples/request.json"] = json.dumps({"name": "Ada"}, indent=2) + "\n"
        files["tests/test_plugin.py"] = (
            "import importlib.util\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "ROOT = Path(__file__).resolve().parents[1]\n\n\n"
            "def load_handlers():\n"
            '    spec = importlib.util.spec_from_file_location("handlers", ROOT / "handlers.py")\n'
            "    module = importlib.util.module_from_spec(spec)\n"
            "    assert spec is not None and spec.loader is not None\n"
            "    spec.loader.exec_module(module)\n"
            "    return module\n\n\n"
            "def test_manifest_points_to_tool_entry():\n"
            '    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))\n'
            f'    assert manifest["name"] == "{manifest.name}"\n'
            '    assert manifest["capabilities"][0]["entry_point"] == "handlers:run"\n\n\n'
            "def test_run_uses_configured_greeting():\n"
            "    handlers = load_handlers()\n"
            '    handlers.configure({"greeting": "Hi"})\n'
            '    assert handlers.run({"name": "Ada"})["message"] == "Hi, Ada!"\n'
        )
    elif template == "hook":
        files["handlers.py"] = (
            '"""Hook handlers for the '
            + manifest.name
            + ' Sage plugin."""\n\n'
            "from typing import Any, Dict, Optional\n\n\n"
            "def on_event(arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n"
            '    """Handle one preview hook event without mutating host state."""\n'
            "    payload = arguments if isinstance(arguments, dict) else {}\n"
            "    return {\n"
            '        "handled": True,\n'
            '        "event": str(payload.get("event") or "unknown"),\n'
            '        "payload": payload.get("payload") or {},\n'
            f'        "plugin": "{manifest.name}",\n'
            "    }\n"
        )
        files["tests/test_plugin.py"] = (
            "import importlib.util\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "ROOT = Path(__file__).resolve().parents[1]\n\n\n"
            "def load_handlers():\n"
            '    spec = importlib.util.spec_from_file_location("handlers", ROOT / "handlers.py")\n'
            "    module = importlib.util.module_from_spec(spec)\n"
            "    assert spec is not None and spec.loader is not None\n"
            "    spec.loader.exec_module(module)\n"
            "    return module\n\n\n"
            "def test_manifest_declares_hook():\n"
            '    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))\n'
            '    assert manifest["capabilities"][0]["type"] == "hook"\n\n\n'
            "def test_on_event_echoes_payload():\n"
            "    handlers = load_handlers()\n"
            '    result = handlers.on_event({"event": "demo", "payload": {"x": 1}})\n'
            '    assert result["handled"] is True\n'
            '    assert result["payload"] == {"x": 1}\n'
        )
    elif template == "mcp":
        files["server.py"] = (
            '"""Dependency-free stdio MCP server for '
            + manifest.name
            + '."""\n\n'
            "import json\n"
            "import sys\n"
            "from typing import Any, Dict, Optional\n\n"
            f'PLUGIN_NAME = "{manifest.name}"\n'
            f'PLUGIN_VERSION = "{manifest.version}"\n'
            f'TOOL_NAME = "{identifier}"\n\n\n'
            "def _result(request_id: Any, result: Any) -> Dict[str, Any]:\n"
            '    return {"jsonrpc": "2.0", "id": request_id, "result": result}\n\n\n'
            "def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:\n"
            "    return {\n"
            '        "jsonrpc": "2.0",\n'
            '        "id": request_id,\n'
            '        "error": {"code": code, "message": message},\n'
            "    }\n\n\n"
            "def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:\n"
            '    """Handle one JSON-RPC request; notifications return None."""\n'
            '    method = str(request.get("method") or "")\n'
            '    request_id = request.get("id")\n'
            '    if method.startswith("notifications/"):\n'
            "        return None\n"
            '    if method == "initialize":\n'
            "        return _result(request_id, {\n"
            '            "protocolVersion": "2024-11-05",\n'
            '            "capabilities": {"tools": {}},\n'
            '            "serverInfo": {"name": PLUGIN_NAME, "version": PLUGIN_VERSION},\n'
            "        })\n"
            '    if method == "ping":\n'
            "        return _result(request_id, {})\n"
            '    if method == "tools/list":\n'
            '        return _result(request_id, {"tools": [{\n'
            '            "name": TOOL_NAME,\n'
            '            "description": "Return a greeting.",\n'
            '            "inputSchema": {\n'
            '                "type": "object",\n'
            '                "properties": {"name": {"type": "string"}},\n'
            "            },\n"
            "        }]})\n"
            '    if method == "tools/call":\n'
            '        params = request.get("params") or {}\n'
            '        if params.get("name") != TOOL_NAME:\n'
            '            return _error(request_id, -32602, "unknown tool")\n'
            '        arguments = params.get("arguments") or {}\n'
            '        name = str(arguments.get("name") or "World")\n'
            '        payload = {"message": "Hello, {}!".format(name)}\n'
            "        return _result(request_id, {\n"
            '            "content": [{"type": "text", "text": json.dumps(payload)}],\n'
            '            "structuredContent": payload,\n'
            "        })\n"
            '    return _error(request_id, -32601, "method not found")\n\n\n'
            "def main() -> int:\n"
            "    for line in sys.stdin:\n"
            "        if not line.strip():\n"
            "            continue\n"
            "        try:\n"
            "            request = json.loads(line)\n"
            "        except json.JSONDecodeError:\n"
            '            response = _error(None, -32700, "parse error")\n'
            "        else:\n"
            "            response = handle_request(request)\n"
            "        if response is not None:\n"
            '            sys.stdout.write(json.dumps(response) + "\\n")\n'
            "            sys.stdout.flush()\n"
            "    return 0\n\n\n"
            'if __name__ == "__main__":\n'
            "    raise SystemExit(main())\n"
        )
        files["tests/test_plugin.py"] = (
            "import importlib.util\n"
            "import json\n"
            "from pathlib import Path\n\n"
            "ROOT = Path(__file__).resolve().parents[1]\n\n\n"
            "def load_server():\n"
            '    spec = importlib.util.spec_from_file_location("server", ROOT / "server.py")\n'
            "    module = importlib.util.module_from_spec(spec)\n"
            "    assert spec is not None and spec.loader is not None\n"
            "    spec.loader.exec_module(module)\n"
            "    return module\n\n\n"
            "def test_manifest_declares_mcp_server():\n"
            '    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))\n'
            '    assert manifest["capabilities"][0]["type"] == "mcp_server"\n\n\n'
            "def test_initialize_and_call():\n"
            "    server = load_server()\n"
            '    initialized = server.handle_request({"id": 1, "method": "initialize"})\n'
            '    assert initialized["result"]["serverInfo"]["name"] == "'
            + manifest.name
            + '"\n'
            "    called = server.handle_request({\n"
            '        "id": 2,\n'
            '        "method": "tools/call",\n'
            '        "params": {"name": server.TOOL_NAME, "arguments": {"name": "Ada"}},\n'
            "    })\n"
            '    assert called["result"]["structuredContent"]["message"] == "Hello, Ada!"\n'
        )
    else:
        files[f"skills/{skill_slug}/SKILL.md"] = (
            "---\n"
            f"name: {skill_slug}\n"
            f"description: {manifest.metadata.description}\n"
            "---\n\n"
            f"# {manifest.metadata.display_name}\n\n"
            "Use this skill when the user asks for this plugin's documented workflow.\n\n"
            "1. Clarify the desired output.\n"
            "2. Work only with information the user provided or approved tools return.\n"
            "3. Summarize assumptions, actions, and verification.\n"
        )
        files["tests/test_plugin.py"] = (
            "import json\n"
            "from pathlib import Path\n\n"
            "ROOT = Path(__file__).resolve().parents[1]\n\n\n"
            "def test_skill_entry_exists_with_frontmatter():\n"
            '    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))\n'
            '    entry = manifest["capabilities"][0]["entry_point"]\n'
            '    text = (ROOT / entry).read_text(encoding="utf-8")\n'
            '    assert text.startswith("---\\n")\n'
            f'    assert "name: {skill_slug}" in text\n'
            '    assert "description:" in text\n'
        )
    return files
