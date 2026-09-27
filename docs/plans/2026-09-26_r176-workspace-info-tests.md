# R176：workspace_info 工作区信息服务单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；WorkspaceInfoService（工作区元数据
  供 UI 展示）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`services/workspace_info.py`（351 行，工作区信息服务——项目名 / Git
信息 / 最近文件 / 文件计数 / 最后活动）此前零测试。

## 覆盖矩阵（约 14 例）

1. get_workspace_info：不存在路径 → WorkspaceInfoError；非目录 → 同；
2. 正常工作区：project_name / workspace_path / git_branch/git_status /
   recent_files / total_files / last_activity；
3. 非 git 目录：git_branch=None、git_status=None；
4. RecentFile 模型字段；5. get_workspace_info_service 单例。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
