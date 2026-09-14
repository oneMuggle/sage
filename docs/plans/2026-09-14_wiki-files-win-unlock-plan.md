# W5 计划——wiki/files 全量 Windows 解锁（R32 模式扩展）

> 日期: 2026-09-14 · 基线: main `fe0bde80`
> 分支: `feat/wiki-files-win-unlock` · 前置: R32 #760（win_reparse_io 原语 + 2 个函数解锁）、P6 #775

## 1. 问题（Windows 产品缺陷）

wiki/files.py 的 14 个 secure_* 中，R32 只给了 `secure_atomic_write_file` /
`secure_read_text` Windows 分支，其余 12 个仍 POSIX-only（`_require_posix_safety`
直接抛 OSError）。后果：**Windows 上 wiki 项目 create/open/list 全部 500**
（P6 集成测试因此 Windows skip），整个 wiki 功能对 Windows 用户不可用——
而 Windows 是 Sage 的主平台。

## 2. 方案

沿用 R32 模式（`win_reparse_io` 逐组件 reparse 检查 + 句柄复核 + 原子替换），
为其余 12 个函数补 Windows 分支。统一骨架：

```python
parts = _relative_parts(root, target)   # 保留 .. 逃逸/越界拒绝契约（重要！）
absolute = root.joinpath(*parts)        # 不经 abspath 规范化，防 .. 被词法折叠
verify_no_reparse(str(absolute))        # 逐组件 reparse 检查（缺失组件放行）
```

| 函数 | Windows 分支要点 |
| --- | --- |
| secure_ensure_directory | verify 后 `mkdir(parents=True, exist_ok=True)`；存在即文件 → NotADirectoryError |
| secure_write_file | `write_file_reparse_safe(overwrite=True)`——CREATE_ALWAYS + 句柄复核天然拒绝 reparse/目录/多链接（契约对齐） |
| secure_write_file_if_missing | `overwrite=False` → FileExistsError 时 lstat 复核（reparse/非 regular/多链接 → 原契约文案）→ False |
| secure_write_temp_file / secure_write_temp_bytes | verify 目录 → 随机名 `overwrite=False` 原子建，FileExistsError 重试 10 次；返回 root 相对路径 |
| secure_create_temp_file | 新原语 `create_new_write_fd_reparse_safe`（CreateFileW CREATE_NEW + msvcrt.open_osfhandle）→ 返回 CRT fd（held 契约） |
| secure_publish_held_temp | `os.fstat(fd)` 身份 ↔ `os.stat(temp)` 比对（st_dev/st_ino Windows 有效）→ 拒 reparse/非 regular 目标 → `os.replace` |
| secure_delete_path | lstat 拒 reparse（"拒绝删除符号链接"）；regular → unlink；dir → 递归删除（条目级 reparse 拒绝）；其余拒绝 |
| secure_rename_path | 双端 verify；旧必须 regular；新存在则拒 reparse/非 regular；`os.replace` |
| secure_read_file | `read_file_reparse_safe`（句柄复核 nlinks==1 契约对齐） |
| secure_read_file_bounded | 先 stat 尺寸预检 → `read_file_reparse_safe` → 长度复核（注释注明与 POSIX held-fd 读的差异） |
| secure_open_file | 新原语 `open_read_fd_reparse_safe`（CreateFileW 读 + 复核 + open_osfhandle）→ CRT fd |
| secure_list_directory | verify 后 `os.scandir`，条目级 reparse 属性过滤（symlink/junction 全跳），只出 regular/dir |
| iter_wiki_markdown | verify root 与 root/wiki；os.walk + 目录级 reparse 剪枝，只出 .md |

`win_reparse_io.py` 仅新增 2 个 fd 桥接函数（msvcrt.open_osfhandle，
O_NOINHERIT），不改动 R32 既有原语。

## 3. 契约保持清单（每函数对照 POSIX 分支）

- `..` 逃逸 / 越界 → `_relative_parts` 原样抛（"不在项目目录内"/"无效"）；
- reparse 组件（symlink/junction）→ 一律拒绝，绝不跟随；
- 多链接（NTFS hardlink）→ 写/读/建均拒绝（"多链接"文案对齐）；
- 非 regular 目标 → 拒绝（原文案）；
- 原子性：写=CREATE_ALWAYS 截断 / 建.CREATE_NEW；替换=MoveFileExW / os.replace；
- temp 未完成 → 清理（best-effort unlink）。

## 4. 测试解锁

- `test_wiki_path_security.py`：移除模块级 `skipif(os.name=="nt")`；
  symlink 夹具改**能力探测 skip**（W4 同款），硬链接/`..` 逃逸/合法
  相对路径用例在 Windows 真实执行（硬链接无需特权，本机可验证）；
- P6 的 `test_wiki_projects_bridge.py` 移除 Windows skip（open/create/list
  解锁后端点级用例可真实执行）；
- `test_project_context.py:156` 的 iter_wiki_markdown 依赖 skip 移除（本地验证）；
- 本机（Windows 3.12）全量相关簇验证 + ruff；CI 的 Linux/Windows 双跑兜底。

## 5. 明确不做

- 不改 POSIX 分支任何行为（零风险面）；
- 不动 win_reparse_io 既有函数签名；
- 不解锁 mklink/junction 类管理操作（不在 wiki 功能面内）。

## 6. win7 对齐

win_reparse_io / files.py 为 R32 后新增分支，win7 分支（Python 3.8）按需
cherry-pick：ctypes/os.replace/msvcrt 均 3.8 兼容；测试文件的能力探测
skip 模式与 W4 一致。

## 7. 实施补充（测试网揪出的两个 R32 原语缺陷，已修）

1. **CREATE_ALWAYS 先截断后复核**：`write_file_reparse_safe(overwrite=True)`
   原实现对硬链接目标在 `_validate_info` 之前就截断——"多链接拒绝"契约
   被绕过（test_secure_write_rejects_hardlink_without_modifying_outside
   捕获 outside.md 被清空）。修复：overwrite=True 改为"CREATE_NEW 原子建；
   已存在 → OPEN_EXISTING 打开链接本体，复核通过后 SetFilePointer+SetEndOfFile
   截断"（R32 预留未用的 set_pointer/set_eof 配置正是为此）。
2. **校验失败句柄泄漏**：`_open_validated`/`_open_single` 在
   `_validate_info` 抛出时未关句柄——SHARE_NONE 下泄漏会把同 inode 的
   其他硬链接一起锁死（后续读取 PermissionError）。两处均补 CloseHandle。

另：`secure_read_text` 的 R32 Windows 分支未拒绝 `..` 逃逸，本批对齐
`_win_abspath` 契约；`test_read_pdf_size_limit` 的 `Path.stat` 桩补
`follow_symlinks` 形参（Python 3.12 新版 pathlib 内部传参变化导致的
INTERNALERROR，与 wiki 无关的顺手修复）。

## 8. 本机验证记录（Windows 3.12）

- wiki/security/skill 簇：83 passed + 后续解锁批次累计全绿；
- 全量 `tests/unit -n auto`：**5539 passed / 8 failed**——8 个失败在干净
  main 上逐一复跑同样失败（symlink 特权 / git 语义 / word 模板 /
  asyncio cancel flake），零新增；
- ruff `backend/` 全过；全部代码 py3.8 兼容。
