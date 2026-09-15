# P11 计划——wiki/files Windows 解锁对齐 release/win7（R32 原语 + W5 分支移植）

> 日期: 2026-09-15 · 基线: release/win7 `1300d269`（P10 #836 合入后）
> 分支: `feat/win7-wiki-unlock` · 上游: main R32 #760 / W5 #802

## 1. 缺陷（win7 用户真实不可用）

win7 分支的 `backend/wiki/files.py` 与 main pre-W5 状态一致——除
`secure_atomic_write_file` / `secure_read_text`（R32 已加 Windows 分支）
外，其余 secure_* 仍 POSIX-only（`_require_posix_safety` 直接抛
OSError）。后果与 main 修复前相同：**wiki 项目 create/open/list 在
Windows 上 500**，整个 wiki 功能对 win7 用户不可用。

## 2. 方案（整文件移植，非重写）

经比对，win7 的 wiki/files.py 与 main pre-W5（b8da0c90）版本函数清单
完全一致（仅缺 W5 增量）——因此**整文件移植 main 当前版本**（W5 已在
main 上全量验证），而非逐函数重写：

| 文件 | 来源 | 内容 |
| --- | --- | --- |
| backend/tools/win_reparse_io.py | main HEAD | R32 原语 + W5 fd 桥接（py3.8 兼容：`from __future__ import annotations` + 无新语法） |
| backend/wiki/files.py | main HEAD | W5 全量：12 个 secure_* 的 reparse-safe Windows 分支 + `_win_abspath`/`_win_remove_tree` 骨架 + secure_read_text 逃逸修复 |
| backend/tests/unit/test_wiki_path_security.py | 9d501fcd（W5 版） | 移除模块级 Windows skip；symlink 夹具改能力探测 |
| backend/tests/unit/test_security_final_paths.py | 9d501fcd（W5 版） | 同上 + 0600 权限断言平台化 |

**不移植**（与本批无关或属其它批次）：R32 的 safe_writer/skill_md/
recent_projects 改动（win7 的 recent_projects 走 wiki/files——本批
files.py 解锁后**顺带恢复可用**）、W5 的 test_pdf stat 桩修复（该
INTERNALERROR 仅 py3.12 触发，win7 CI 是 py3.8）、P6/P8 的存储迁移。

## 3. 验证

- 本机 Windows 3.12：wiki 安全簇 + recent_projects + project_authorization
  全绿；ruff（win7 自带 ruff.toml）；
- CI win7 通道：**Backend (Python 3.8, Win7 LTS)** 真实 3.8 验证
  （P10 已证明该任务在本仓库可绿）；
- 前端零改动。

## 4. win7 对齐状态记录

P10（#836）：项目模块 P1 核心 ✅
P11（本批）：wiki/files Windows 解锁 ✅ → win7 上 wiki create/open/list
缺陷关闭；recent_projects 顺带恢复。
待评估：P2+ 子列表/命令面板对齐；P6/P8 授权/存储桥接（依赖本批）。
