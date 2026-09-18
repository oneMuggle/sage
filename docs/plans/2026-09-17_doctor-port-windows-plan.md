# doctor 端口占用检测 Windows 语义修复（Round 20）

日期：2026-09-17 ｜ 分支：`feat/doctor-port-windows` ｜ 基线：#1047（6e626f8cf）

## 背景

`cli/checks/port_{frontend,backend}.py` 用 `SO_REUSEADDR + bind` 探测端口占用。
Linux 上语义正确；Windows 上 `SO_REUSEADDR` 允许绑定到**已被监听**的端口——
占用检测永远返回「空闲」（漏报孤儿 backend / 正在运行的 dev server）。
仓库测试里两个占用用例带 `skipif(os.name == "nt")`，注释明说是产品缺口。

## 修复

- Windows：改设 `SO_EXCLUSIVEADDRUSE`（保证任何占用下 bind 都失败），不再设
  `SO_REUSEADDR`
- POSIX：保持 `SO_REUSEADDR`（原语义，TIME_WAIT 也能复用）
- `port_backend` 的修复提示按平台分派：Windows 给 `netstat -ano | findstr :8765`
  + `taskkill /PID <pid> /F`，POSIX 保持 `lsof`
- 提取共享 `_bind_probe(port)` 到 `cli/checks/_ports.py`，两 check 复用

## 测试

- 摘除两个 `skipif(nt)`，占用/空闲用例在 Windows 真实执行
- `port_backend` 新增：Windows 提示文案包含 `netstat`（平台相关断言）

## 验证

本机 Windows：test_port_frontend / test_port_backend 全绿（0 skip）；
POSIX 语义不变（CI ubuntu 回归）。
