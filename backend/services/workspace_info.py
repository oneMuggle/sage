"""
Workspace information service.

Provides workspace metadata for UI display:
- Project name and path
- Git branch and status
- Recent file modifications

Author: Claude
Date: 2026-09-26
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RecentFile(BaseModel):
    """Recently modified file in workspace."""

    name: str = Field(..., description="文件名")
    path: str = Field(..., description="文件路径")
    modified: str = Field(..., description="修改时间 ISO 格式")
    size_bytes: int = Field(default=0, description="文件大小")


class WorkspaceInfo(BaseModel):
    """Workspace information for UI display."""

    project_name: str = Field(..., description="项目名称")
    workspace_path: str = Field(..., description="工作区路径")
    git_branch: Optional[str] = Field(default=None, description="Git 分支")
    git_status: Optional[str] = Field(default=None, description="Git 状态")
    git_ahead: int = Field(default=0, description="领先远程的提交数")
    git_behind: int = Field(default=0, description="落后远程的提交数")
    recent_files: List[RecentFile] = Field(
        default_factory=list, description="最近修改的文件"
    )
    total_files: int = Field(default=0, description="总文件数")
    last_activity: Optional[str] = Field(
        default=None, description="最后活动时间 ISO 格式"
    )


class WorkspaceInfoError(Exception):
    """Base exception for workspace info errors."""

    pass


class WorkspaceInfoService:
    """
    Service for gathering workspace information.

    Collects metadata about a workspace directory:
    - Project name (from directory name)
    - Git information (branch, status, ahead/behind)
    - Recent file modifications

    Usage:
        service = WorkspaceInfoService()
        info = service.get_workspace_info("/path/to/workspace")
    """

    def get_workspace_info(
        self, workspace_path: Union[Path, str], max_recent_files: int = 10
    ) -> WorkspaceInfo:
        """
        Get workspace information.

        Args:
            workspace_path: Workspace directory path
            max_recent_files: Maximum number of recent files to return

        Returns:
            WorkspaceInfo
        """
        workspace = Path(workspace_path)

        if not workspace.exists():
            raise WorkspaceInfoError(f"工作区目录不存在: {workspace}")

        if not workspace.is_dir():
            raise WorkspaceInfoError(f"路径不是目录: {workspace}")

        # Gather information
        project_name = workspace.name
        git_info = self._get_git_info(workspace)
        recent_files = self._get_recent_files(workspace, max_recent_files)
        total_files = self._count_files(workspace)
        last_activity = self._get_last_activity(workspace)

        return WorkspaceInfo(
            project_name=project_name,
            workspace_path=str(workspace),
            git_branch=git_info.get("branch"),
            git_status=git_info.get("status"),
            git_ahead=git_info.get("ahead", 0),
            git_behind=git_info.get("behind", 0),
            recent_files=recent_files,
            total_files=total_files,
            last_activity=last_activity,
        )

    def _get_git_info(self, workspace: Path) -> dict:
        """Get git repository information."""
        info = {}

        try:
            # Check if it's a git repository
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5, check=False,
            )

            if result.returncode != 0:
                return info

            # Get current branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5, check=False,
            )

            if result.returncode == 0:
                info["branch"] = result.stdout.strip()

            # Get status
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5, check=False,
            )

            if result.returncode == 0:
                status_lines = result.stdout.strip()
                if not status_lines:
                    info["status"] = "clean"
                else:
                    modified_count = len(status_lines.split("\n"))
                    info["status"] = f"{modified_count} modified"

            # Get ahead/behind
            result = subprocess.run(
                ["git", "status", "--branch", "--porcelain=v2"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=5, check=False,
            )

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("# branch.ab"):
                        parts = line.split()
                        for part in parts:
                            if part.startswith("+"):
                                info["ahead"] = int(part[1:])
                            elif part.startswith("-"):
                                info["behind"] = int(part[1:])

        except subprocess.TimeoutExpired:
            logger.warning("Git command timed out")
        except Exception as e:
            logger.warning(f"Failed to get git info: {e}")

        return info

    def _get_recent_files(
        self, workspace: Path, max_files: int
    ) -> List[RecentFile]:
        """Get recently modified files."""
        recent = []

        try:
            # Use find to get recently modified files
            result = subprocess.run(
                [
                    "find",
                    str(workspace),
                    "-type",
                    "f",
                    "-not",
                    "-path",
                    "*/.git/*",
                    "-not",
                    "-path",
                    "*/node_modules/*",
                    "-not",
                    "-path",
                    "*/__pycache__/*",
                    "-printf",
                    "%T@ %p\n",
                ],
                capture_output=True,
                text=True,
                timeout=10, check=False,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                file_times = []

                for line in lines:
                    if not line:
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) != 2:
                        continue

                    try:
                        timestamp = float(parts[0])
                        filepath = parts[1]
                        file_times.append((timestamp, filepath))
                    except ValueError:
                        continue

                # Sort by timestamp (most recent first)
                file_times.sort(reverse=True)

                # Take top N
                for timestamp, filepath in file_times[:max_files]:
                    path = Path(filepath)
                    try:
                        stat = path.stat()
                        recent.append(
                            RecentFile(
                                name=path.name,
                                path=filepath,
                                modified=datetime.fromtimestamp(timestamp)
                                .isoformat()
                                .replace("+00:00", "Z"),
                                size_bytes=stat.st_size,
                            )
                        )
                    except Exception:
                        continue

        except subprocess.TimeoutExpired:
            logger.warning("File search timed out")
        except Exception as e:
            logger.warning(f"Failed to get recent files: {e}")

        return recent

    def _count_files(self, workspace: Path) -> int:
        """Count total files in workspace."""
        try:
            result = subprocess.run(
                [
                    "find",
                    str(workspace),
                    "-type",
                    "f",
                    "-not",
                    "-path",
                    "*/.git/*",
                    "-not",
                    "-path",
                    "*/node_modules/*",
                    "-not",
                    "-path",
                    "*/__pycache__/*",
                ],
                capture_output=True,
                text=True,
                timeout=10, check=False,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                return len([line for line in lines if line])

        except Exception as e:
            logger.warning(f"Failed to count files: {e}")

        return 0

    def _get_last_activity(self, workspace: Path) -> Optional[str]:
        """Get last activity timestamp."""
        try:
            # Find most recently modified file
            result = subprocess.run(
                [
                    "find",
                    str(workspace),
                    "-type",
                    "f",
                    "-not",
                    "-path",
                    "*/.git/*",
                    "-not",
                    "-path",
                    "*/node_modules/*",
                    "-not",
                    "-path",
                    "*/__pycache__/*",
                    "-printf",
                    "%T@\n",
                ],
                capture_output=True,
                text=True,
                timeout=10, check=False,
            )

            if result.returncode == 0:
                timestamps = [
                    float(line)
                    for line in result.stdout.strip().split("\n")
                    if line
                ]
                if timestamps:
                    latest = max(timestamps)
                    return (
                        datetime.fromtimestamp(latest)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )

        except Exception as e:
            logger.warning(f"Failed to get last activity: {e}")

        return None


# Global instance
_workspace_info_service: Optional[WorkspaceInfoService] = None


def get_workspace_info_service() -> WorkspaceInfoService:
    """Get global workspace info service instance."""
    global _workspace_info_service
    if _workspace_info_service is None:
        _workspace_info_service = WorkspaceInfoService()
    return _workspace_info_service
