# R32 批次 —— Windows 原生 reparse-safe 文件原语（ctypes CreateFileW）

> 背景：W1-W4（#712/#715/#722/#746）治理后，多个产品面仍在 Windows 因
> 无 O_NOFOLLOW 设计性 fail-closed：技能写盘（safe_writer）、recent_projects
> （wiki/files 全家桶）、script_runner 读取。本批实现 Win32 原生
> reparse-safe 读写原语，按风险分步接入。

## 已有蓝图
`backend/tools/shell_resolver.py` 已有完整的 kernel32 ctypes 模式：
`CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT)` + `GetFileAttributesW` 逐父组件
reparse 检查 + `GetFinalPathNameByHandleW` 规范化比对 + 可注入 kernel32
（测试 monkeypatch 先例：test_shell_resolver.py:156/246）。

## 新原语 backend/tools/win_reparse_io.py

- 模块级 `_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)`
  （模块属性可注入；argtypes/restype 显式配置）。
- `verify_no_reparse(path: str) -> bool`：逐组件 GetFileAttributesW 检查
  FILE_ATTRIBUTE_REPARSE_POINT（目录/链接/junction 全覆盖）。
- `read_file_reparse_safe(path) -> bytes`：
  1. verify_no_reparse；
  2. `CreateFileW(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING,
     FILE_FLAG_OPEN_REPARSE_POINT)`；
  3. `GetFileInformationByHandle`：reparse 属性 → OSError 拒绝；
     DIRECTORY → NotADirectoryError；`nNumberOfLinks != 1` → OSError
     （非私有文件，对齐 POSIX 分支 st_nlink==1）；
  4. ReadFile 循环读全量。
- `write_file_reparse_safe(path, data: bytes, *, overwrite: bool) -> None`：
  1. verify_no_reparse（父组件）；
  2. `CreateFileW(GENERIC_WRITE, FILE_SHARE_NONE,` overwrite=False →
     `CREATE_NEW`（原子建，ERROR_FILE_EXISTS/ALREADY_EXISTS →
     FileExistsError）`; overwrite=True → OPEN_EXISTING（缺失 →
     FileNotFoundError）``；flags 加 FILE_FLAG_OPEN_REPARSE_POINT；
  3. 信息校验同上（reparse/目录/多链接拒绝）；
  4. overwrite=True → `SetFilePointer(FILE_BEGIN)` + `SetEndOfFile` 截断；
  5. WriteFile 全量写出。

## 接入（按风险分步）

### W5a 技能写盘解锁（safe_writer.py）
- `_open_windows_skill_file` 替换 raise：名称校验（单组件，含路径分隔符即拒
  = 越界防护）→ 父目录普通 mkdir（与 POSIX 分支 mkdir 非 secure 一致）→
  `write_file_reparse_safe(utf-8 bytes, overwrite=overwrite)`。
- 异常契约保持：FileExistsError / OSError("Refusing skill write ...")。
- test_safe_writer：模块 skipif(nt) 改为保留（POSIX 分支用例）+ 新增
  Windows 实测用例（nt-only：happy path / CREATE_NEW 冲突 / hardlink 拒绝
  ——hardlink 本地可创建无需特权；symlink 拒绝用探测式 skip）。

### W5b recent_projects 解锁（wiki/files.py）
- `secure_read_text` / `secure_atomic_write_file` 增加 Windows 分支：
  读 → read_file_reparse_safe；原子写 → reparse-safe 建临时文件 +
  `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` 同卷原子替换。
- 仅这两个函数开 Windows 分支；其余 secure_* 维持 POSIX-only。
- test_recent_projects：移除模块 skipif(nt)，symlink 用例保留探测式 skip。

### W5c loader 读侧硬化恢复（skill_md/loader.py）
- `_read_no_follow` Windows 分支从 read_bytes 升级为
  read_file_reparse_safe（#722 的放宽被原生实现取代）。
- #722 跳过的 4 个 symlink 拒绝用例改为能力探测（CI windows runner 有
  特权可跑；本地无特权仍 skip）。

### 延后（记录）
- script_runner（需要 fd-identity 三重绑定的 Windows 等价）、resources
  （已有 metadata 路线）、subprocess 进程组。

## 测试
- 新 test_win_reparse_io.py：读写 happy / CREATE_NEW 冲突 / 覆盖截断 /
  目录拒绝 / 多链接（os.link 本地可建）/ 缺失读错误（nt-only）。
- 触及簇回归 + 触及文件的 symlink 用例（能力探测式）。
- 本地（Windows 无特权）+ CI windows job（非阻塞，有特权全量）双验证。

**平台支持性改进，win7 分支不 cherry**（其 ci.yml 独立；未来如需可单独移植）。
