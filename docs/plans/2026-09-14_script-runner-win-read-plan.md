# R32 批次 B —— script_runner Windows 绑定读取等价

> 承接 #760：`script_runner._read_bound_regular_file` 在 Windows 因缺
> O_NOFOLLOW 直接 fail-closed（脚本执行确认链路的第一步）。本批用 W5 的
> reparse-safe 原语提供 Windows 等价实现。

## 设计

- `win_reparse_io.read_file_bound_reparse_safe(path) -> (bytes, identity)`：
  - `verify_no_reparse` + `CreateFileW(OPEN_EXISTING + OPEN_REPARSE_POINT)`
  - 打开后句柄复核（reparse/目录/多链接拒绝）
  - identity = `(dwVolumeSerialNumber, nFileIndexHigh, nFileIndexLow)`
    （Windows 的 (st_dev, st_ino) 等价物）
  - 读取后二次打开校验 identity 仍一致（路径→文件绑定未被替换）
- `script_runner._read_bound_regular_file` 平台分派：POSIX 保留原实现；
  Windows 走新原语（identity 元数据等价物，消费方只做相等比较，无需感知）。

## 范围与不变式
- 脚本**执行**（沙箱、进程组）仍 POSIX-only——`test_skill_md_script_runner`
  的模块级 skipif(nt) 保持，另行批次。
- 本批只解锁"确认前快照/确认后重读比对"的读取原语。

## 测试
- 新 test_script_runner_win_read.py（nt-only）：happy（内容+sha 一致）、
  两次读取 identity 稳定、文件被替换后 identity 变化、symlink 拒绝（探测式）。
