# R32 批次 D —— W4 遗留平台语义用例定性收尾（permission/compute/download）

> 背景：W4（#746）曾将 3 处平台语义用例 skipif(nt) 标注"另行批次定性"。
> 本批完成定性：2 处改为平台中立用例（安全契约双平台真实验证），1 处为
> **真产品语义修复**（compute_resolver PATHEXT），并解除全部 skip。

## 定性与改动

### 1. permission（真测试改进，解除 skip）
- 原用例写死 `/etc/cron.d/evil`（Windows 上非绝对路径 → 语义漂移）。
- 改为平台中立越界绝对路径：nt 用 `<盘符>:\Windows\evil`，POSIX 仍
  `/etc/cron.d/evil`——"workspace 外绝对路径写入 → 硬拒绝"安全契约
  双平台真实验证。

### 2. download_tool（真测试改进，解除 skip）
- 同类：绝对文件名按平台构造（nt 用 `<anchor>\etc\passwd`）。
- 断言接受两条等价安全拒绝路径（`filename_must_be_relative` 或
  `path_outside_workspace`）。

### 3. compute_resolver（真产品语义修复）
- `_is_executable` 在 Windows 上 `os.access(X_OK)` **恒真** → 任意文本文件
  都会被误判为可执行的 compute 二进制（用户配置 `executable_path` 指向
  说明文档时也会被启动）。
- 修复：nt 分支改按 **PATHEXT 后缀判定**（与 `shutil.which` 同语义；
  缺省 `.com/.exe/.bat/.cmd`）；POSIX 行为不变。
- `test_non_executable_file_is_skipped` 解除 skip（plain 无后缀文件在
  Windows 正确跳过）；夹具可执行文件在 nt 上补 `.exe` 后缀（断言全部
  动态引用路径，无需改动）。

## 验证
- compute_resolver：14/14（0 skip）；permission + download_tool：125 过。
- 本机 Windows 全绿；ubuntu CI 验证 POSIX 分支不变。
