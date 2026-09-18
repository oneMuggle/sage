# 83. Python 后端代码保护方案 (Cython + 字节码混淆与剥离)

## 1. 概述与背景

在早期版本中，Windows 安装包通过 `scripts/bundle-python-main.ps1` 和 `scripts/bundle-python.ps1` 直接将后端代码（`resources/backend/` 及 `resources/sage-core/`）以 `.py` 源码形式分发。这导致客户端用户可直接查看、篡改业务逻辑与安全中间件代码。

为解决代码资产暴露问题，本项目引入了**开发/发布分离的混合代码保护机制**：
- **日常开发与普通 CI (PR/Push)**：采用纯源码模式，保证秒级热重载与 0 编译开销。
- **正式发布 (Release Tag)**：通过环境变量 `SAGE_PROTECT_CODE=true` 启用混合代码保护：
  1. `packages/sage-core/sage_core` 核心模块通过 **Cython** 编译为二进制扩展（Windows 下为 `.pyd`，Linux 下为 `.so`）。
  2. `backend/` 业务逻辑模块通过 **Python 字节码编译 (`compileall -b`)**，并在安装包生成阶段**彻底剥离 `.py` 源码**（除最小入口文件外）。

---

## 2. 架构设计与执行流

```
[开发 / PR CI 阶段]
  SAGE_PROTECT_CODE 未设置 / false
  └─ 直接复制 .py 源码到 resources/ -> 耗时 ~0 秒，支持单测和断点

[正式发布 Tag 阶段 (release.yml / release-win7.yml)]
  SAGE_PROTECT_CODE=true
  ├─ 1. Cython 编译: scripts/compile-sage-core.py
  │     packages/sage-core/sage_core/*.py -> *.pyd (C 扩展二进制)
  ├─ 2. 注入 site-packages 并剥离 sage_core .py 源码
  ├─ 3. Bytecode 编译: python -m compileall -b resources/backend
  └─ 4. 剥离 resources/backend/ 下所有非入口 .py 源码
```

---

## 3. 双分支 (main vs release/win7) 对齐策略

| 维度 | `main` 分支 | `release/win7` 分支 |
|---|---|---|
| **Python 运行时** | Python 3.11.9 embeddable | Python 3.8.10 embeddable |
| **打包脚本** | `scripts/bundle-python-main.ps1` | `scripts/bundle-python.ps1` |
| **Cython 约束** | `cython>=3.0.0` | `cython>=3.0.0,<3.1.0` (兼容 Py3.8) |
| **Pydantic 兼容** | Pydantic v2 (使用 `binding=True`) | Pydantic v1 (兼容 AST 生成) |
| **CI 工作流** | `.github/workflows/release.yml` | `.github/workflows/release-win7.yml` |

---

## 4. 关键文件与脚本

- `scripts/compile-sage-core.py`：Cython 自动化编译驱动脚本，配置了 `binding=True` 和 `language_level=3`，保证 FastAPI / Pydantic 反射检查正常工作。
- `scripts/backend.spec`：备选的 PyInstaller standalone 可执行文件打包配置。
- `scripts/bundle-python-main.ps1`：main 分支打包入口，支持 `-ProtectCode` 参数与 `SAGE_PROTECT_CODE` 环境变量。
- `scripts/bundle-python.ps1`：win7 分支打包入口，同步支持 `-ProtectCode` 参数与 `SAGE_PROTECT_CODE` 环境变量。

---

## 5. 本地验证与排错

> 脚本名按分支取用：`main` 用 `scripts/bundle-python-main.ps1`，`release/win7` 用 `scripts/bundle-python.ps1`。以下示例以 main 为例。

### 验证快速模式（开发默认）
```powershell
pwsh scripts/bundle-python-main.ps1
```

### 验证发布保护模式
```powershell
$env:SAGE_PROTECT_CODE = "true"
pwsh scripts/bundle-python-main.ps1
```
验证步骤：
1. 检查 `resources/python/Lib/site-packages/sage_core/` 中是否存在 `.pyd` 文件，且无对应 `.py` 源码（除 `__init__.py`）。
2. 检查 `resources/backend/` 中业务代码是否为 `.pyc` 且已清除 `.py`。
3. 执行 canary 验证：
   ```cmd
   resources\python\python.exe -c "import backend.main; import sage_core; print('OK')"
   ```
