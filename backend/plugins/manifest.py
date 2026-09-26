"""
Plugin manifest schema definition.

This module defines the standardized plugin manifest format (plugin.json)
for Sage's plugin system, inspired by ZCode's plugin architecture.

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# Pydantic v1/v2 compatibility
try:
    # Pydantic v2
    from pydantic import field_validator, model_validator
    PYDANTIC_V2 = True
except ImportError:
    # Pydantic v1 fallback
    from pydantic import validator as field_validator  # type: ignore
    from pydantic import root_validator as model_validator  # type: ignore
    PYDANTIC_V2 = False


class PluginType(str, Enum):
    """Plugin type classification."""

    BUILTIN = "builtin"  # 内置插件，随应用包分发
    CDN = "cdn"  # CDN 插件，从官方市场下载
    PERSONAL = "personal"  # 个人来源插件


class CapabilityType(str, Enum):
    """Plugin capability types."""

    TOOL = "tool"  # 提供工具（Agent 可调用）
    SKILL = "skill"  # 提供技能（SKILL.md 定义）
    HOOK = "hook"  # 提供钩子（生命周期钩子）
    MCP_SERVER = "mcp_server"  # 提供 MCP 服务器
    COMMAND = "command"  # 提供命令（Slash command）


class PluginCapability(BaseModel):
    """Plugin capability declaration."""

    type: CapabilityType = Field(..., description="能力类型")
    name: str = Field(..., description="能力名称", min_length=1, max_length=100)
    description: str = Field(default="", description="能力描述")
    version: str = Field(default="1.0.0", description="能力版本", pattern=r"^\d+\.\d+\.\d+$")

    # 可选配置
    entry_point: Optional[str] = Field(
        default=None, description="入口点（工具函数名/技能文件路径/MCP 服务器路径）"
    )
    permissions: List[str] = Field(
        default_factory=list, description="所需权限列表（如 file:read, network:write）"
    )
    config_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="配置项 JSON Schema"
    )

    if PYDANTIC_V2:
        @field_validator("name")
        @classmethod
        def validate_name(cls, v: str) -> str:
            """Validate capability name format."""
            if not v.replace("-", "").replace("_", "").isalnum():
                raise ValueError("能力名称只能包含字母、数字、连字符和下划线")
            return v
    else:
        @field_validator("name")
        def validate_name(cls, v: str) -> str:
            """Validate capability name format (Pydantic v1)."""
            if not v.replace("-", "").replace("_", "").isalnum():
                raise ValueError("能力名称只能包含字母、数字、连字符和下划线")
            return v


class PluginDependency(BaseModel):
    """Plugin dependency declaration."""

    name: str = Field(..., description="依赖插件名称", min_length=1)
    version: str = Field(..., description="版本要求", pattern=r"^[\d.^~*>=]+$")
    optional: bool = Field(default=False, description="是否可选依赖")

    if PYDANTIC_V2:
        @model_validator(mode="after")
        def validate_version_format(self) -> PluginDependency:
            """Validate version constraint format."""
            valid = self.version.replace("^", "").replace("~", "").replace("*", "").replace(">=", "")
            if not all(c.isdigit() or c == "." for c in valid):
                raise ValueError(f"不支持的版本格式: {self.version}")
            return self
    else:
        @model_validator
        def validate_version_format(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            """Validate version constraint format (Pydantic v1)."""
            version = values.get("version", "")
            valid = version.replace("^", "").replace("~", "").replace("*", "").replace(">=", "")
            if not all(c.isdigit() or c == "." for c in valid):
                raise ValueError(f"不支持的版本格式: {version}")
            return values


class PluginMetadata(BaseModel):
    """Plugin metadata (display information)."""

    display_name: str = Field(..., description="显示名称", min_length=1, max_length=100)
    description: str = Field(default="", description="插件描述", max_length=500)
    icon: Optional[str] = Field(default=None, description="图标路径或 URL")
    author: str = Field(default="", description="作者名称", max_length=100)
    homepage: Optional[str] = Field(default=None, description="主页 URL")
    repository: Optional[str] = Field(default=None, description="代码仓库 URL")
    license: str = Field(default="MIT", description="许可证")
    categories: List[str] = Field(
        default_factory=list, description="分类标签", max_length=10
    )
    tags: List[str] = Field(default_factory=list, description="标签", max_length=20)

    # 商店信息
    hero_image: Optional[str] = Field(default=None, description="商店页 Hero 图")
    example_prompts: List[str] = Field(
        default_factory=list, description="示例提示词", max_length=5
    )


class PluginManifest(BaseModel):
    """
    Plugin manifest (plugin.json) definition.

    This is the core data model for Sage's plugin system.
    Each plugin must have a valid manifest file.

    Example plugin.json:
    {
      "schema_version": "1.0",
      "name": "my-plugin",
      "version": "1.0.0",
      "type": "personal",
      "metadata": {
        "display_name": "My Plugin",
        "description": "A sample plugin",
        "author": "John Doe"
      },
      "capabilities": [
        {
          "type": "tool",
          "name": "my-tool",
          "description": "A custom tool",
          "entry_point": "tools.my_tool"
        }
      ],
      "dependencies": [],
      "min_sage_version": "0.4.0"
    }
    """

    schema_version: str = Field(
        default="1.0", description="Schema 版本", pattern=r"^\d+\.\d+$"
    )
    name: str = Field(
        ..., description="插件唯一标识符", min_length=1, max_length=100
    )
    version: str = Field(..., description="插件版本", pattern=r"^\d+\.\d+\.\d+$")
    type: PluginType = Field(default=PluginType.PERSONAL, description="插件类型")

    metadata: PluginMetadata = Field(..., description="插件元数据")

    capabilities: List[PluginCapability] = Field(
        default_factory=list, description="插件能力列表"
    )
    dependencies: List[PluginDependency] = Field(
        default_factory=list, description="插件依赖列表"
    )

    # 系统要求
    min_sage_version: str = Field(
        default="0.4.0", description="最低 Sage 版本要求", pattern=r"^\d+\.\d+\.\d+$"
    )
    python_version: str = Field(
        default=">=3.10", description="Python 版本要求"
    )

    # 生命周期钩子
    hooks: List[str] = Field(
        default_factory=list, description="生命周期钩子函数名"
    )

    # 配置
    user_config: Optional[Dict[str, Any]] = Field(
        default=None, description="用户配置 JSON Schema"
    )

    if PYDANTIC_V2:
        @field_validator("name")
        @classmethod
        def validate_plugin_name(cls, v: str) -> str:
            """Validate plugin name format."""
            if not v.replace("-", "").replace("_", "").isalnum():
                raise ValueError("插件名称只能包含字母、数字、连字符和下划线")
            if v.startswith("-") or v.endswith("-"):
                raise ValueError("插件名称不能以连字符开头或结尾")
            return v.lower()
    else:
        @field_validator("name")
        def validate_plugin_name(cls, v: str) -> str:
            """Validate plugin name format (Pydantic v1)."""
            if not v.replace("-", "").replace("_", "").isalnum():
                raise ValueError("插件名称只能包含字母、数字、连字符和下划线")
            if v.startswith("-") or v.endswith("-"):
                raise ValueError("插件名称不能以连字符开头或结尾")
            return v.lower()

    if PYDANTIC_V2:
        @model_validator(mode="after")
        def validate_capabilities_unique(self) -> PluginManifest:
            """Validate that capability names are unique."""
            names = [c.name for c in self.capabilities]
            if len(names) != len(set(names)):
                raise ValueError("能力名称必须唯一")
            return self

        @model_validator(mode="after")
        def validate_dependencies_no_self(self) -> PluginManifest:
            """Validate that plugin doesn't depend on itself."""
            for dep in self.dependencies:
                if dep.name == self.name:
                    raise ValueError("插件不能依赖自身")
            return self
    else:
        @model_validator
        def validate_capabilities_unique(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            """Validate that capability names are unique (Pydantic v1)."""
            capabilities = values.get("capabilities", [])
            names = [c.name if hasattr(c, "name") else c.get("name") for c in capabilities]
            if len(names) != len(set(names)):
                raise ValueError("能力名称必须唯一")
            return values

        @model_validator
        def validate_dependencies_no_self(cls, values: Dict[str, Any]) -> Dict[str, Any]:
            """Validate that plugin doesn't depend on itself (Pydantic v1)."""
            name = values.get("name", "")
            dependencies = values.get("dependencies", [])
            for dep in dependencies:
                dep_name = dep.name if hasattr(dep, "name") else dep.get("name")
                if dep_name == name:
                    raise ValueError("插件不能依赖自身")
            return values

    def to_json(self, indent: int = 2) -> str:
        """Serialize manifest to JSON string."""
        # Pydantic v1/v2 compatibility
        if hasattr(self, "model_dump_json"):
            return self.model_dump_json(indent=indent)
        return self.json(indent=indent)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manifest to dictionary."""
        # Pydantic v1/v2 compatibility
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()

    @classmethod
    def from_json(cls, json_str: str) -> PluginManifest:
        """Deserialize manifest from JSON string."""
        data = json.loads(json_str)
        # Pydantic v1/v2 compatibility
        if hasattr(cls, "model_validate"):
            return cls.model_validate(data)
        return cls.parse_obj(data)

    @classmethod
    def from_file(cls, path: Union[Path, str]) -> PluginManifest:
        """Load manifest from plugin.json file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"插件清单文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"路径不是文件: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Pydantic v1/v2 compatibility
        if hasattr(cls, "model_validate"):
            return cls.model_validate(data)
        return cls.parse_obj(data)

    def save(self, path: Union[Path, str]) -> None:
        """Save manifest to plugin.json file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


def validate_plugin_manifest(manifest_path: Union[Path, str]) -> tuple[bool, List[str]]:
    """
    Validate a plugin manifest file.

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    try:
        PluginManifest.from_file(manifest_path)
        return True, []
    except FileNotFoundError as e:
        errors.append(f"文件不存在: {e}")
    except json.JSONDecodeError as e:
        errors.append(f"JSON 解析错误: {e}")
    except ValueError as e:
        errors.append(f"校验失败: {e}")
    except Exception as e:
        errors.append(f"未知错误: {e}")

    return False, errors


# Example manifest for testing/documentation
EXAMPLE_MANIFEST = {
    "schema_version": "1.0",
    "name": "example-plugin",
    "version": "1.0.0",
    "type": "personal",
    "metadata": {
        "display_name": "Example Plugin",
        "description": "An example plugin demonstrating the manifest schema",
        "author": "Sage Team",
        "homepage": "https://github.com/example/sage-plugin",
        "license": "MIT",
        "categories": ["productivity", "tools"],
        "tags": ["example", "demo"],
    },
    "capabilities": [
        {
            "type": "tool",
            "name": "example-tool",
            "description": "An example tool provided by this plugin",
            "entry_point": "tools.example_tool",
            "permissions": ["file:read"],
        },
        {
            "type": "skill",
            "name": "example-skill",
            "description": "An example skill defined in SKILL.md",
            "entry_point": "skills/example/SKILL.md",
        },
    ],
    "dependencies": [],
    "min_sage_version": "0.4.0",
    "python_version": ">=3.10",
    "hooks": ["on_install", "on_uninstall"],
    "user_config": {
        "type": "object",
        "properties": {
            "api_key": {"type": "string", "description": "API Key"},
            "enabled": {"type": "boolean", "default": True},
        },
    },
}
