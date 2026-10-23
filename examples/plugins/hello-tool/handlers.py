"""Tool handlers for the hello-tool Sage plugin."""

from typing import Any, Dict, Optional

_CONFIG: Dict[str, Any] = {}


def configure(config: Dict[str, Any]) -> None:
    """Receive lifecycle config before the worker serves calls."""
    _CONFIG.clear()
    _CONFIG.update(config or {})


def run(arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a JSON-serializable greeting."""
    payload = arguments if isinstance(arguments, dict) else {}
    name = str(payload.get("name") or "World")
    greeting = str(_CONFIG.get("greeting") or "Hello")
    return {
        "message": "{}, {}!".format(greeting, name),
        "plugin": "hello-tool",
        "template": "tool",
    }
