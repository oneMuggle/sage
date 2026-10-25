# R152：runtime_exec 输入校验层单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime_exec 结构性校验（路径/cwd/
  代码大小/timeout/敏感环境变量）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/runtime_validation.py`（116 行）是 runtime_exec 的输入校验层：
runtime_path 必须 regular file + 可执行、cwd 必须位于 workspace_root
内、code 字节上限 256KiB、timeout ∈ [1,600]、env_overrides 禁止覆盖
八类敏感凭证变量。此前零测试。

## 覆盖矩阵（约 18 例）

1. validate_runtime_path：空/非字符串、不存在、目录（非 regular
   file）、不可执行 → 各自 ValueError；合法（tmp 文件 + chmod 755）→
   resolve 后绝对路径；
2. validate_cwd：None → None；根内目录 → resolve 路径；工作区外 →
   ValueError；路径是文件非目录 → ValueError；
3. validate_code_size：非字符串 → 错误；超 256KiB → 错误；返回 utf-8
   字节数；
4. validate_timeout：None → 60；非整数 / <1 / >600 → 错误；合法透传；
5. validate_env_overrides：None/空 → {}；合法键值 → 原样拷贝；敏感键
   （SAGE_LOCAL_AUTH_TOKEN/OPENAI_API_KEY/GITHUB_TOKEN 等）→ 错误；
   空键 / 非字符串键 / 非字符串值 → 错误；
6. RuntimeValidationError 是 ValueError 子类。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
