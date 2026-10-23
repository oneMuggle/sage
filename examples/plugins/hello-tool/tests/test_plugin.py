import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_handlers():
    spec = importlib.util.spec_from_file_location("handlers", ROOT / "handlers.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_points_to_tool_entry():
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "hello-tool"
    assert manifest["capabilities"][0]["entry_point"] == "handlers:run"


def test_run_uses_configured_greeting():
    handlers = load_handlers()
    handlers.configure({"greeting": "Hi"})
    assert handlers.run({"name": "Ada"})["message"] == "Hi, Ada!"
