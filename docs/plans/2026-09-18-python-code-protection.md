# Python 后端代码保护混合方案

**实施日期**: 2026-09-18  
**状态**: 进行中  
**分支**: feat/python-code-protection (main + release/win7 对齐)

---

## 1. 背景与目标

### 问题
当前安装包中 Python 后端代码以 `.py` 源码形式分发，存在以下风险：
- **知识产权暴露**：业务逻辑、算法实现完全可见
- **安全漏洞暴露**：攻击者可以审计代码找漏洞
- **篡改风险**：用户可以修改 .py 文件改变程序行为

### 目标
实施**混合方案**实现代码保护，同时保持开发效率：
- **日常开发/CI**：纯源码模式，0 开销，支持热重载
- **正式发布**：混合编译保护（Cython + PyInstaller/Nuitka）

### 方案选型
| 模块 | 保护方式 | 理由 |
|------|---------|------|
| `sage_core` 核心包 | Cython 编译为 `.pyd/.so` | 核心算法保护 + 性能提升 |
| `backend/` 业务逻辑 | PyInstaller 打包或 Nuitka 编译 | 整体打包，部署简单 |
| 入口文件 | `.py` 或 `.pyc` | 启动入口，保持灵活 |

---

## 2. 实施策略：Dev/Release 分离

### 核心机制
通过环境变量 `SAGE_PROTECT_CODE` 控制打包行为：

```powershell
# scripts/bundle-python-main.ps1
if ($env:SAGE_PROTECT_CODE -eq "true") {
    # 编译保护模式（Release 使用）
    # - Cython 编译 sage_core → .pyd
    # - PyInstaller 打包 backend → backend.exe
} else {
    # 快速模式（Dev/CI 使用）
    # - 直接复制源码 .py 文件
}
```

### 工作流职责划分

| 场景 | 触发时机 | 工作流 | 后端处理方式 | 耗时 |
|------|---------|--------|-------------|------|
| 本地开发 | `npm run dev` | 本地环境 | 纯源码，热重载 | 即时 |
| CI/PR | push 分支/PR | `ci.yml` | 纯源码跑 pytest | ~10 分钟 |
| 正式发布 | push tag `v*` | `release.yml` | **混合编译保护** | ~35-40 分钟 |

---

## 3. 涉及的文件与模块

### 需要修改的文件

1. **打包脚本**
   - `scripts/bundle-python-main.ps1` (main 分支)
   - `scripts/bundle-python.ps1` (win7 分支)
   - 添加 `SAGE_PROTECT_CODE` 环境开关

2. **编译脚本**（新增）
   - `scripts/compile-sage-core.py` — Cython 编译 sage_core
   - `scripts/backend-pyinstaller.spec` — PyInstaller 打包 backend

3. **CI/Release 配置**
   - `.github/workflows/release.yml` — 添加 `SAGE_PROTECT_CODE: "true"`
   - `.github/workflows/release-win7.yml` — 同步

4. **依赖管理**
   - `backend/requirements-bundled.txt` — 添加 Cython/PyInstaller

5. **Electron 启动逻辑**（可能需要调整）
   - `electron/main.ts` / `electron/backendLauncher.ts` — 适配编译后启动

### 不修改的文件
- `ci.yml` — 保持纯源码模式，不增加编译步骤

---

## 4. 技术方案

### 4.1 Cython 编译 sage_core

**目标**：将 `packages/sage-core/sage_core/` 编译为平台相关的 `.pyd` (Windows) 或 `.so` (Linux)

**编译脚本** `scripts/compile-sage-core.py`：
```python
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        "packages/sage-core/sage_core/**/*.py",
        compiler_directives={'language_level': "3"}
    )
)
```

**编译产物**：
- Windows: `sage_core/*.pyd`
- Linux: `sage_core/*.so`

### 4.2 PyInstaller 打包 backend

**目标**：将 `backend/` 目录打包为可执行文件

**PyInstaller spec** `scripts/backend-pyinstaller.spec`：
```python
a = Analysis(
    ['backend/main.py'],
    pathex=['backend'],
    datas=[...],
    hiddenimports=['fastapi', 'uvicorn', 'pydantic', 'sage_core'],
)
exe = EXE(pyz, a.scripts, name='backend', ...)
```

### 4.3 环境变量开关

**bundle 脚本修改**：
```powershell
if ($env:SAGE_PROTECT_CODE -eq "true") {
    Write-Host "🛡️ Code protection ENABLED" -ForegroundColor Yellow
    # Cython + PyInstaller
} else {
    Write-Host "⚡ Fast mode: source code only" -ForegroundColor Green
    # 当前逻辑：直接复制 .py
}
```

---

## 5. 实施步骤

### Phase 1: 基础架构（1 天）

- [ ] **Task 1.1**: 创建 Cython 编译脚本 `scripts/compile-sage-core.py`
- [ ] **Task 1.2**: 测试 Cython 编译 sage_core，验证 `.pyd` 生成
- [ ] **Task 1.3**: 修改 `bundle-python-main.ps1` 添加环境开关
- [ ] **Task 1.4**: 本地测试 `SAGE_PROTECT_CODE=true` 打包流程

### Phase 2: PyInstaller 打包（1-2 天）

- [ ] **Task 2.1**: 创建 PyInstaller spec 文件 `scripts/backend-pyinstaller.spec`
- [ ] **Task 2.2**: 测试 PyInstaller 打包 backend，验证 `backend.exe` 可运行
- [ ] **Task 2.3**: 修改 `bundle-python-main.ps1` 集成 PyInstaller
- [ ] **Task 2.4**: 测试完整打包流程（Cython + PyInstaller）

### Phase 3: Electron 适配（0.5 天）

- [ ] **Task 3.1**: 修改 `electron/backendLauncher.ts` 适配编译后启动
- [ ] **Task 3.2**: 测试编译后的 backend 启动逻辑

### Phase 4: CI/Release 集成（0.5 天）

- [ ] **Task 4.1**: 修改 `.github/workflows/release.yml` 添加 `SAGE_PROTECT_CODE: "true"`
- [ ] **Task 4.2**: 修改 `.github/workflows/release-win7.yml` 同步

### Phase 5: Win7 分支对齐（0.5 天）

- [ ] **Task 5.1**: 修改 `scripts/bundle-python.ps1` (win7) 添加环境开关
- [ ] **Task 5.2**: 适配 Py3.8 + Pydantic v1 的编译配置

### Phase 6: 文档与验证（0.5 天）

- [ ] **Task 6.1**: 更新 `docs/technical/` 添加代码保护说明
- [ ] **Task 6.2**: 验证安装包体积变化
- [ ] **Task 6.3**: 性能测试 + 安全性验证

---

## 6. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Cython 编译失败（跨平台） | 高 | 分别在 Windows/Linux 测试 |
| PyInstaller hiddenimports 缺失 | 高 | 详细测试，逐步添加 |
| Win7 Py3.8 兼容性 | 中 | 使用 Py3.8 兼容版本 |

---

**下一步**：开始 Phase 1 实施
