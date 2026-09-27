# R162：Git Status 路由单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；侧边栏 Git Status 面板（ZCode 对标）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/git_status_routes.py`（173 行，GET /api/v1/git/status——porcelain
v1 解析、conflicted 优先排序、非 git 目录静默降级、detached HEAD 处理）
此前零测试。porcelain 解析纯函数 + 真实 tmp git 仓库端到端。

## 覆盖矩阵（约 18 例）

_parse_porcelain_line（纯）：
1. " M" → modified；"M " → staged；"??" → untracked；"UU"/"AA"/"DD" →
   conflicted；"D " → deleted；短行 → None；双空格行 → None；
2. 引号包裹的空格路径 → 剥引号。

get_git_status（真实 tmp git 仓库，subprocess 驱动）：
3. 非 git 目录 → is_git_repo=False 空文件；4. 目录不存在 → 404；
5. 提交后修改+新增未跟踪 → 文件状态正确（modified/untracked）；
6. 排序：conflicted 最前、renamed 最后；7. branch 名非 None；
8. 路径含空格的文件名正确解析。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
