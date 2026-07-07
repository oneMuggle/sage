"""
Permission system for multi-agent orchestration.

Controls what actions agents can perform during lane execution.
Implements least-privilege principle with preset profiles.
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List


class PermissionPreset(str, Enum):
    """Predefined permission profiles for agents."""

    AUDIT = "audit"  # Read-only: code analysis, test execution
    EXPLAIN = "explain"  # Read-only: documentation, explanations
    IMPLEMENT = "implement"  # Write: code modifications, file creation


@dataclass
class AgentAction:
    """Represents an action an agent wants to perform."""

    action_type: str  # "read_file", "write_file", "execute", etc.
    target: str  # File path, command, or resource
    parameters: dict = field(default_factory=dict)


@dataclass
class LanePermission:
    """Permission constraints for a lane execution."""

    preset: PermissionPreset
    allowed_paths: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)

    def check(self, action: AgentAction) -> bool:
        """
        Validate if an action is permitted.

        Args:
            action: The action to validate

        Returns:
            True if permitted, False otherwise
        """
        # Check denied tools
        if action.action_type in self.denied_tools:
            return False

        # Audit/Explain presets cannot write, execute, or run lanes
        if self.preset in (
            PermissionPreset.AUDIT,
            PermissionPreset.EXPLAIN,
        ) and action.action_type in (
            "write_file",
            "delete_file",
            "execute",
            "shell",
            "execute_lane",
        ):
            return False

        # Check path restrictions for file operations
        if action.action_type in ("read_file", "write_file", "delete_file"):
            return self._check_path_access(action.target)

        return True

    def _check_path_access(self, target_path: str) -> bool:
        """Check if path is within allowed directories."""
        if not self.allowed_paths:
            return True  # No restrictions

        target = Path(target_path).resolve()
        for allowed in self.allowed_paths:
            allowed_dir = Path(allowed).resolve()
            try:
                target.relative_to(allowed_dir)
                return True
            except ValueError:
                continue
        return False


class PermissionChecker:
    """Manages permission validation for lane execution."""

    def __init__(self, permission: LanePermission):
        self.permission = permission

    def can_execute(self, action: AgentAction) -> bool:
        """Check if action is permitted."""
        return self.permission.check(action)

    def assert_permission(self, action: AgentAction) -> None:
        """
        Assert that action is permitted, raise if not.

        Raises:
            PermissionError: If action is not permitted
        """
        if not self.can_execute(action):
            raise PermissionError(
                f"Action '{action.action_type}' on '{action.target}' "
                f"not permitted by {self.permission.preset.value} preset"
            )
