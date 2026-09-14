# R32 批次 F —— resources 消费端句柄级复核升级

> 背景：resources.py 消费端复检（`_indexed_regular_resources`）此前用
> lstat 元数据检查（reparse 属性 + S_ISREG + 非 symlink），元数据检查与
> 消费打开之间存在 TOCTOU 窗口。本批把复核升级为**句柄级校验**
> （#760 win_reparse_io 原语）。

## 改动
### win_reparse_io
- 新增 `verify_regular_file_reparse_safe(path)`（只校验不读取）：
  1. `verify_no_reparse` 逐组件检查（不存在的组件放行，缺失错误由打开语义表达）；
  2. 目录预检（无 BACKUP_SEMANTICS 打开目录是 ACCESS_DENIED，提前转
     NotADirectoryError）；
  3. `CreateFileW(OPEN_EXISTING + FILE_FLAG_OPEN_REPARSE_POINT)` + 句柄
     `GetFileInformationByHandle` 复核（reparse/目录/多链接拒绝）。

### resources.py
- `_indexed_regular_resources` 句柄级复核：nt 走原语；POSIX 用
  `os.open(O_RDONLY | O_NOFOLLOW)` 打开校验（等价闭合 TOCTOU）。
  校验失败（reparse/目录/多链接/消失）一律跳过，授权集合不含该资源。

## 测试
- test_win_reparse_io 增 5 例（regular 通过 / 缺失 FileNotFoundError /
  目录 NotADirectoryError / hardlink 拒绝 / symlink 叶拒绝——探测式）。
- 既有 resources 63 例全绿（含 4 例 CI 真实执行的 symlink 拒绝安全用例）；
  skill_md 全家回归绿。

**平台支持改进，win7 分支不 cherry**。方案：本文件。
