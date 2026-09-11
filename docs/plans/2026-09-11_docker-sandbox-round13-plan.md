# bash docker 沙箱执行后端 Round 13 实施计划（对标 hermes terminal backends）

> 日期: 2026-09-11 · 分支: `feat/bash-docker-sandbox` · 基于 main @ 7fc1bdda
> 来源: hermes-agent 对标分析（7 种 terminal backends 中最有安全价值的一个）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2，
> 且 Win7 分支无 docker 依赖）。

## 背景

Sage 的 bash 工具只能在宿主机直接执行命令。hermes 支持 local/docker/ssh
等 7 种 terminal backends——docker 沙箱把命令隔离进容器（文件系统/进程/
网络与宿主隔离），是无人值守（网关远程审批自动批准）场景的安全升级。

## 方案（最小侵入：命令 argv 层包装）

### A. `backend/tools/bash_tool.py`

- 环境变量：`SAGE_BASH_EXEC_BACKEND=local|docker`（默认 local）；
  `SAGE_BASH_DOCKER_IMAGE`（默认 `python:3.11-slim`）
- `_spawn` 起点调用 `_docker_maybe_wrap(command, cwd, shell)`：
  - backend != docker → 返回 None（既有路径不变）
  - docker → argv 包装为
    `docker run --rm [-v <cwd>:/workspace -w /workspace] <image>
    <shell.executable> *shell.args_prefix <command>`，
    spawn 的 cwd 置 None（容器内路径）
- `_decorate` 增加 `exec_backend` 元数据（docker/local），结果可见

### B. 测试

- `backend/tests/unit/test_bash_docker_backend.py`：argv 构造（含 cwd
  挂载与无 cwd）、local 默认透传、未知 backend 回退 local、decorate 标记
- 既有 bash 回归

## Round 14 候选

- Discord 平台适配 / 网关多平台抽象基类
- hex-legacy 双栈收敛
