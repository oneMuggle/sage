# 内网离线组件包（.sagepkg）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 release/win7 增加“签名离线组件包”能力：管理员可通过 SageDoctor CLI 或设置页导入 `.sagepkg`，完成模型等可选组件的离线安装；win7 全量安装包继续原样产出，组件包作为独立发布资产。

**Architecture:** 组件核心放在 `backend/services/components/`（纯 Python，不依赖 FastAPI/uvicorn），CLI 与 Electron IPC 共用同一套校验/安装逻辑。`.sagepkg` 是带 RSA-SHA256 签名的 zip，安装目标默认是 `userData`（模型目录）或 `userData/components/<id>/<version>`。SageDoctor 负责应用起不来时的兜底/批量导入，设置页「组件管理」负责日常导入。

**Tech Stack:** Python 3.8 / pydantic 1.x 分支、`cryptography`（已随 win7 运行时打包）、argparse、zipfile；Electron 21 主进程 TypeScript、Node `child_process`；React + Tailwind + Vitest。

**Spec:** 本对话中确认的设计（2026-11-16/17）：win7 内网保留全量安装包；在线通道未来才做瘦包；组件包与安装包同批签名；SageDoctor 与 UI 双入口共用核心。

## Global Constraints

- 分支：`release/win7` 派生，Python **3.8**、pydantic **1.x**；禁止 PEP 604/585 语法（`str | None`、`list[...]`）。
- 后端依赖只能使用 win7 已打包依赖；签名使用 `cryptography`，不新增运行时依赖。
- 组件包默认要求签名；未配置公钥/签名无效必须拒绝导入，不能静默降级。
- 不在生产终端执行 pip/npm/conda；`.sagepkg` 内是已构建好的文件。
- win7 全量 NSIS 安装包保持不变；本计划只新增组件包与导入入口。
- 所有新增 Python 文件必须 `from __future__ import annotations`（py3.8 兼容）。
- 单文件 ≤800 行（架构门禁）；新前端文件优先拆小。
- UI 文案中英双语；i18n 独立分域，不继续推高 `chatAndSider.ts`。

---

## 文件结构

```
backend/services/components/
├── __init__.py              # 导出 ComponentService / 模型 / 错误
├── errors.py                # ComponentError
├── models.py                # ComponentManifest / ComponentFile / InstalledComponent
├── crypto.py                # 公钥解析 + RSA-SHA256 验签
├── archive.py               # zip 安全解包 + 逐文件 hash
└── service.py               # scan/verify/install/remove + installed.json

backend/cli/components.py    # 独立 CLI（JSON 行事件，供 Electron 解析）
backend/cli/rescue.py        # 增加 components 子命令 + REPL 菜单

electron/componentsIpc.ts    # components:* IPC + 进度事件
electron/backendLauncher.ts  # 新增通用 resolveModuleLaunchCommand()
electron/preload.ts          # components bridge
src/shared/types/electron-api.d.ts  # ComponentsElectronApiBridge

src/pages/settings/ComponentsTab.tsx
src/pages/settings/settingsTabs.tsx
src/pages/settings/settingsSearchEntries.ts
src/pages/settings/__tests__/ComponentsTab.test.tsx
src/shared/lib/i18n/locales/{zh,en}/components.ts
src/shared/lib/i18n/{zh,en}.ts

scripts/build-component-packs.py
scripts/gen-component-keypair.py
resources/component-public-key.pem   # 公开公钥（私钥不入库）
.github/workflows/release-win7.yml   # 构建/上传 .sagepkg

docs/technical/161-offline-component-packs.md
docs/technical/README.md
docs/technical/101-win7-offline-maintenance.md
docs/user-manual/54-offline-component-packs.md
docs/user-manual/README.md
```

---

## Task 0: 工作区与测试环境

**Files:**
- 已创建 worktree：`.worktrees/feat-offline-component-packs`
- 共享 `node_modules`（依赖版本与 release/win7 一致，避免慢速网络重装）

- [x] **Step 1: 创建 worktree**

```bash
scripts/worktree.sh new feat/offline-component-packs --base release/win7
```

- [ ] **Step 2: 链接主仓库 node_modules**

```bash
cd /home/fz/project/sage/.worktrees/feat-offline-component-packs
ln -s /home/fz/project/sage/node_modules node_modules
```

- [ ] **Step 3: 确认 py38 测试解释器**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -c "import cryptography; print(cryptography.__version__)"
# 期望：47.0.0
```

---

## Task 1: 组件核心（models / errors / crypto）

**Files:**
- Create: `backend/services/components/__init__.py`
- Create: `backend/services/components/errors.py`
- Create: `backend/services/components/models.py`
- Create: `backend/services/components/crypto.py`
- Test: `backend/tests/unit/services/test_components_service.py`

**Interfaces:**
- Produces:
  - `ComponentError(message: str, code: str = "component_error")`
  - `ComponentFile(path: str, size: int, sha256: str)`
  - `ComponentManifest(...)`，字段：`schema_version/id/name/version/branch/python/arch/target/payload_dir/files/description/created_at`
  - `load_public_key(pem: bytes) -> PublicKey`
  - `verify_signature(public_key, payload: bytes, signature: bytes) -> bool`

- [ ] **Step 1: 写失败测试（manifest 解析 + 验签）**

```python
# backend/tests/unit/services/test_components_service.py
from __future__ import annotations

import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.services.components.crypto import load_public_key, verify_signature
from backend.services.components.models import ComponentManifest


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, pub


def test_manifest_parses_and_rejects_traversal():
    manifest = ComponentManifest.from_dict(
        {
            "schemaVersion": 1,
            "id": "embedding-bge-small-zh",
            "name": "Embedding",
            "version": "1.0.0",
            "branch": "win7",
            "python": "3.8",
            "arch": "x64",
            "target": "user_data",
            "payloadDir": "payload",
            "files": [
                {"path": "models/bge-small-zh-v1.5/model.onnx", "size": 10, "sha256": "a" * 64}
            ],
        }
    )
    assert manifest.id == "embedding-bge-small-zh"
    assert manifest.files[0].path.startswith("models/")

    bad = dict(manifest.to_dict())
    bad["files"] = [{"path": "../sage.db", "size": 1, "sha256": "a" * 64}]
    try:
        ComponentManifest.from_dict(bad)
    except ValueError as exc:
        assert "路径" in str(exc) or "path" in str(exc).lower()
    else:
        raise AssertionError("expected traversal rejection")


def test_signature_roundtrip_and_tamper():
    key, pub = _keypair()
    payload = b'{"id":"x"}'
    signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    public_key = load_public_key(pub)
    assert verify_signature(public_key, payload, signature) is True
    assert verify_signature(public_key, payload + b" ", signature) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-offline-component-packs
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
# 期望：ModuleNotFoundError / ImportError
```

- [ ] **Step 3: 写最小实现**

`errors.py`：

```python
from __future__ import annotations


class ComponentError(Exception):
    def __init__(self, message: str, code: str = "component_error") -> None:
        super().__init__(message)
        self.code = code
```

`models.py`（要点：路径校验在解析期完成）：

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Tuple

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} 必须是非空字符串")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError(f"{label} 不允许绝对路径或 ..：{value}")
    if ":" in normalized.split("/")[0]:
        raise ValueError(f"{label} 不允许盘符：{value}")
    return normalized


@dataclass(frozen=True)
class ComponentFile:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComponentFile":
        path = _safe_relative_path(data.get("path"), "文件路径")
        size = data.get("size")
        sha = str(data.get("sha256", "")).lower()
        if not isinstance(size, int) or size < 0:
            raise ValueError("文件 size 必须是非负整数")
        if not _SHA_RE.match(sha):
            raise ValueError("文件 sha256 格式错误")
        return cls(path=path, size=size, sha256=sha)

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class ComponentManifest:
    schema_version: int
    id: str
    name: str
    version: str
    branch: str
    python: str
    arch: str
    target: str
    payload_dir: str
    files: Tuple[ComponentFile, ...]
    description: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComponentManifest":
        if data.get("schemaVersion") != 1:
            raise ValueError("不支持的组件包 schemaVersion")
        comp_id = str(data.get("id", ""))
        if not _ID_RE.match(comp_id):
            raise ValueError("组件 id 格式错误")
        target = str(data.get("target", ""))
        if target not in ("user_data", "component_dir"):
            raise ValueError("不支持的组件 target")
        payload_dir = _safe_relative_path(data.get("payloadDir", "payload"), "payloadDir")
        files = tuple(ComponentFile.from_dict(item) for item in data.get("files", []))
        if not files:
            raise ValueError("组件包 files 不能为空")
        paths = [f.path for f in files]
        if len(paths) != len(set(paths)):
            raise ValueError("组件包 files 存在重复路径")
        return cls(
            schema_version=1,
            id=comp_id,
            name=str(data.get("name", comp_id)),
            version=str(data.get("version", "")),
            branch=str(data.get("branch", "")),
            python=str(data.get("python", "")),
            arch=str(data.get("arch", "")),
            target=target,
            payload_dir=payload_dir,
            files=files,
            description=str(data.get("description", "")),
            created_at=str(data.get("createdAt", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "branch": self.branch,
            "python": self.python,
            "arch": self.arch,
            "target": self.target,
            "payloadDir": self.payload_dir,
            "files": [f.to_dict() for f in self.files],
            "description": self.description,
            "createdAt": self.created_at,
        }

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)
```

`crypto.py`：

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def load_public_key(pem: bytes):
    return serialization.load_pem_public_key(pem)


def verify_signature(public_key, payload: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def resolve_public_key_path(
    *,
    environ: Optional[Mapping[str, str]] = None,
    user_data_dir: Optional[Path] = None,
    resources_dir: Optional[Path] = None,
) -> Optional[Path]:
    env = environ if environ is not None else os.environ
    explicit = env.get("SAGE_COMPONENT_PUBLIC_KEY_PATH")
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    for candidate in (
        (user_data_dir / "components" / "public-key.pem") if user_data_dir else None,
        (resources_dir / "component-public-key.pem") if resources_dir else None,
    ):
        if candidate and candidate.is_file():
            return candidate
    return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
# 期望：2 passed
```

- [ ] **Step 5: 提交**

```bash
git add backend/services/components backend/tests/unit/services/test_components_service.py
git commit -m "feat(components): add manifest model and signature verification"
```

---

## Task 2: zip 安全解包与文件校验

**Files:**
- Create: `backend/services/components/archive.py`
- Test: `backend/tests/unit/services/test_components_service.py`（追加）

**Interfaces:**
- Produces: `stage_payload(zip_path, manifest, staging_dir, progress=None) -> None`
- 行为：拒绝 zip slip、符号链接、重复条目、未登记文件、大小/hash 不匹配。

- [ ] **Step 1: 追加失败测试**

```python
import hashlib
import zipfile
from pathlib import Path

from backend.services.components.archive import stage_payload
from backend.services.components.models import ComponentManifest


def _manifest(files):
    return ComponentManifest.from_dict(
        {
            "schemaVersion": 1,
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "branch": "win7",
            "python": "3.8",
            "arch": "x64",
            "target": "user_data",
            "payloadDir": "payload",
            "files": files,
        }
    )


def test_stage_payload_rejects_zip_slip(tmp_path: Path):
    payload = b"evil"
    sha = hashlib.sha256(payload).hexdigest()
    manifest = _manifest([{"path": "models/evil.bin", "size": len(payload), "sha256": sha}])
    # 解包层防线：zip 内条目必须与 manifest 路径严格匹配，非法条目直接拒绝。
    zip_path = tmp_path / "bad.sagepkg"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("payload/ok.bin", payload)
    try:
        stage_payload(zip_path, manifest, tmp_path / "stage")
    except Exception as exc:
        assert "未登记" in str(exc) or "路径" in str(exc) or "payload" in str(exc).lower()
    else:
        raise AssertionError("expected rejection")


def test_stage_payload_verifies_hash(tmp_path: Path):
    payload = b"hello"
    good = hashlib.sha256(payload).hexdigest()
    manifest = _manifest([{"path": "models/demo.bin", "size": 5, "sha256": good}])
    zip_path = tmp_path / "ok.sagepkg"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("payload/models/demo.bin", payload)
    stage_payload(zip_path, manifest, tmp_path / "stage")
    assert (tmp_path / "stage" / "models" / "demo.bin").read_bytes() == payload
```

- [ ] **Step 2: 运行确认失败**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
# 期望：ImportError: backend.services.components.archive
```

- [ ] **Step 3: 实现 `archive.py`**

要点：
- `MAX_TOTAL_BYTES = 8 * 1024 ** 3`，`MAX_FILES = 100_000`。
- 遍历 zip：只允许 `component.json`、`signature.bin`、`<payloadDir>/...`。
- 归一化 `\` → `/`，拒绝绝对路径、`..`、盘符、空段。
- 拒绝 `external_attr` 中 symlink 位。
- 用 `zipfile.ZipFile.open()` 流式写临时文件，边写边算 sha256，校验 size/hash。
- 用 seen 集比对 manifest paths，缺失/多余都报错。
- 进度回调：`(phase, message, done, total)`。

```python
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Callable, Optional, Set

from .errors import ComponentError
from .models import ComponentManifest

MAX_TOTAL_BYTES = 8 * 1024**3
MAX_FILES = 100_000
Progress = Optional[Callable[[str, str, int, int], None]]


def _safe_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ComponentError(f"组件包包含非法路径：{name}")
    if ":" in parts[0]:
        raise ComponentError(f"组件包包含盘符路径：{name}")
    return normalized


def stage_payload(
    zip_path: Path,
    manifest: ComponentManifest,
    staging_dir: Path,
    progress: Progress = None,
) -> None:
    expected = {f.path: f for f in manifest.files}
    if len(expected) > MAX_FILES or manifest.total_bytes > MAX_TOTAL_BYTES:
        raise ComponentError("组件包超出文件数量或解压体积限制")
    staging_dir.mkdir(parents=True, exist_ok=True)
    seen: Set[str] = set()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        total = len(infos)
        for index, info in enumerate(infos, 1):
            name = _safe_member(info.filename)
            if name in ("component.json", "signature.bin") or name.endswith("/"):
                continue
            prefix = manifest.payload_dir + "/"
            if not name.startswith(prefix):
                raise ComponentError(f"组件包包含 payload 之外的文件：{name}")
            rel = name[len(prefix):]
            if rel not in expected:
                raise ComponentError(f"组件包包含未登记文件：{rel}")
            if rel in seen:
                raise ComponentError(f"组件包存在重复条目：{rel}")
            seen.add(rel)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ComponentError(f"组件包不允许符号链接：{rel}")
            target = staging_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with zf.open(info) as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > expected[rel].size:
                        raise ComponentError(f"文件大小超出声明：{rel}")
                    digest.update(chunk)
                    dst.write(chunk)
            if written != expected[rel].size or digest.hexdigest() != expected[rel].sha256:
                raise ComponentError(f"文件校验失败：{rel}")
            if progress:
                progress("extract", rel, index, total)
    missing = set(expected) - seen
    if missing:
        raise ComponentError(f"组件包缺少文件：{sorted(missing)[0]}")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
# 期望：全部 passed
```

- [ ] **Step 5: 提交**

```bash
git add backend/services/components/archive.py backend/tests/unit/services/test_components_service.py
git commit -m "feat(components): add safe signed payload extraction"
```

---

## Task 3: ComponentService（verify / install / list / remove / scan）

**Files:**
- Create: `backend/services/components/service.py`
- Modify: `backend/services/components/__init__.py`
- Test: 追加到 `backend/tests/unit/services/test_components_service.py`

**Interfaces:**
- Produces:
  - `ComponentService.from_environment(...)`
  - `list_installed() -> List[InstalledComponent]`
  - `scan(dirs=None) -> List[PackageScanResult]`
  - `verify_package(path, full=True) -> ComponentManifest`
  - `install(path) -> InstalledComponent`
  - `remove(component_id) -> bool`
- 安装元数据：`<userData>/components/installed.json`
- `user_data` target 只允许 `models/` 前缀；`component_dir` target 落在 `<userData>/components/<id>/<version>/`。

- [ ] **Step 1: 追加失败测试（导入/重复安装/删除/非法目标）**

```python
def _build_pack(tmp_path: Path, key, manifest: dict, payload: dict):
    import json, zipfile
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    signature = key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    pack = tmp_path / "demo.sagepkg"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("component.json", body)
        zf.writestr("signature.bin", signature)
        for name, data in payload.items():
            zf.writestr("payload/" + name, data)
    return pack


def test_install_and_remove_user_data_component(tmp_path: Path, monkeypatch):
    key, pub = _keypair()
    pub_path = tmp_path / "public.pem"
    pub_path.write_bytes(pub)
    monkeypatch.setenv("SAGE_COMPONENT_PUBLIC_KEY_PATH", str(pub_path))
    user_data = tmp_path / "userdata"
    user_data.mkdir()
    payload = b"model-bytes"
    import hashlib
    sha = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schemaVersion": 1, "id": "embedding-demo", "name": "Demo",
        "version": "1.0.0", "branch": "win7", "python": "3.8", "arch": "x64",
        "target": "user_data", "payloadDir": "payload",
        "files": [{"path": "models/demo/model.bin", "size": len(payload), "sha256": sha}],
    }
    pack = _build_pack(tmp_path, key, manifest, {"models/demo/model.bin": payload})
    from backend.services.components.service import ComponentService
    service = ComponentService(user_data_dir=user_data, resources_dir=tmp_path)
    installed = service.install(pack)
    assert installed.id == "embedding-demo"
    assert (user_data / "models/demo/model.bin").read_bytes() == payload
    assert service.list_installed()[0].version == "1.0.0"
    assert service.remove("embedding-demo") is True
    assert not (user_data / "models/demo/model.bin").exists()
    assert service.list_installed() == []
```

- [ ] **Step 2: 运行确认失败**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
# 期望：ImportError: service
```

- [ ] **Step 3: 实现 `service.py`**

关键实现约束：
- 读取 `component.json` 与 `signature.bin`：签名覆盖 `component.json` 原始字节。
- 公钥解析优先级：`SAGE_COMPONENT_PUBLIC_KEY_PATH` → `SAGE_COMPONENT_PUBLIC_KEY`（内联 PEM）→ `<userData>/components/public-key.pem` → `<resources>/component-public-key.pem`。
- `install` 流程：验签 → 解析 manifest → staging 解包/逐文件校验 → 获取 `.lock` → 读旧 metadata → 原子复制文件 → 写 `installed.json` → 删除旧版本中不再存在的文件。
- `remove`：只删除 `installed.json` 记录且位于允许前缀内的文件；删除空目录；写回 metadata。
- `scan` 默认扫描：
  - `<resources>/components`
  - `<userData>/components/inbox`
  - `SAGE_COMPONENT_SCAN_DIRS`（`os.pathsep` 分隔）
  - Windows 下 `%ProgramData%/Sage/components`
- `verify_package(full=True)` 解包到临时目录后清理；`full=False` 只验 manifest 签名。
- 锁文件超时 10 分钟；重复导入同一组件同版本且文件一致时直接返回已安装记录。

`InstalledComponent` / `PackageScanResult` 放在 `models.py`，字段：

```python
@dataclass(frozen=True)
class InstalledComponent:
    id: str
    name: str
    version: str
    target: str
    installed_at: str
    files: Tuple[ComponentFile, ...]
    source_package: str
    signature_verified: bool

    @property
    def total_bytes(self) -> int: ...


@dataclass(frozen=True)
class PackageScanResult:
    path: str
    id: str
    name: str
    version: str
    size: int
    error: str = ""
```

- [ ] **Step 4: 运行测试确认通过**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -q
```

- [ ] **Step 5: 补 py38 兼容与 ruff**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python scripts/check_py38_compat.py
/home/fz/anaconda3/envs/sage-backend-py38/bin/ruff check backend/services/components
```

- [ ] **Step 6: 提交**

```bash
git add backend/services/components backend/tests/unit/services/test_components_service.py
git commit -m "feat(components): add install/remove/scan service"
```

---

## Task 4: CLI `backend/cli/components.py` + SageDoctor 集成

**Files:**
- Create: `backend/cli/components.py`
- Modify: `backend/cli/rescue.py`
- Test: `backend/tests/unit/cli/test_components_cli.py`

**Interfaces:**
- CLI：
  - `python -m backend.cli.components list [--json]`
  - `scan [--dir PATH]... [--json]`
  - `verify PACKAGE [--json]`
  - `import PACKAGE [--json] [--yes]`
  - `remove ID [--json] [--yes]`
- JSON 模式逐行输出：
  - `{"event":"progress","phase":"extract","message":"...","done":1,"total":10}`
  - `{"event":"result","ok":true,"installed":[...]}` 或 `{"event":"result","ok":false,"error":"..."}`
- `rescue.py` 增加 `components` 子命令，转发到上述 CLI；REPL 增加 `[8] 管理离线组件包`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import json

from backend.cli import components as cli


def test_cli_parser_has_all_actions():
    parser = cli.build_parser()
    for argv in (["list"], ["scan"], ["verify", "x.sagepkg"], ["import", "x.sagepkg"], ["remove", "demo"]):
        assert parser.parse_args(argv).action == argv[0]


def test_cli_json_error_is_machine_readable(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    rc = cli.main(["verify", str(tmp_path / "missing.sagepkg"), "--json"])
    assert rc == 2
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[-1]["event"] == "result"
    assert lines[-1]["ok"] is False
    assert "不存在" in lines[-1]["error"]
```

- [ ] **Step 2: 运行确认失败**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/cli/test_components_cli.py -q
# 期望：ModuleNotFoundError
```

- [ ] **Step 3: 实现 CLI**

要点：
- `ComponentService.from_environment()` 使用 `resolve_user_data_dir()`（`backend/services/rescue/paths.py`）和资源目录推导：
  - `SAGE_RESOURCES_DIR` 优先；
  - 打包态（`SAGE_IS_PACKAGED=1`）用 `Path(sys.executable).parent.parent`；
  - 开发态用 `Path(__file__).resolve().parents[2] / "resources"`。
- `--json` 模式所有输出都是 JSON 行；不要在 stdout 打印人类文案。
- 人类模式打印中文进度/结果。
- `remove` 未带 `--yes` 时交互确认；非交互 stdin EOF 视为未确认（退出码 2）。
- 错误统一 `ComponentError` 捕获，JSON 模式输出 `result ok=false`。

- [ ] **Step 4: 修改 `rescue.py`**

```python
p_comp = sub.add_parser("components", parents=[common], help="离线组件包管理")
p_comp.add_argument("action", choices=["list", "scan", "verify", "import", "remove"])
p_comp.add_argument("package", nargs="?", default=None)
p_comp.add_argument("--id", dest="component_id", default=None)
p_comp.add_argument("--dir", action="append", default=None)
p_comp.add_argument("--json", action="store_true", dest="as_json")
```

`cmd_components(args)` 组装 argv 后调用 `components_cli.main`。REPL 增加菜单项 `[8]` 与 `_repl_components()`（list/scan/import/remove 循环）。

- [ ] **Step 5: 运行测试**

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/cli/test_components_cli.py backend/tests/unit/cli/test_rescue_cli.py -q
```

- [ ] **Step 6: 提交**

```bash
git add backend/cli/components.py backend/cli/rescue.py backend/tests/unit/cli/test_components_cli.py
git commit -m "feat(components): add CLI and SageDoctor entry"
```

---

## Task 5: 通用模块启动命令（Electron 复用）

**Files:**
- Modify: `electron/backendLauncher.ts`
- Test: `electron/__tests__/backendLauncher.test.ts`（追加）

**Interfaces:**
- Produces: `resolveModuleLaunchCommand(opts, moduleName, moduleArgs) -> CliLaunchPlan | undefined`
- 保持 `resolveDoctorLaunchCommand` 行为不变，可改为调用新函数。

- [ ] **Step 1: 写失败测试**

```ts
it('resolveModuleLaunchCommand swaps backend.main for an arbitrary module', () => {
  const plan = resolveModuleLaunchCommand(
    { ...opts, env: { CONDA_PREFIX: '/opt/conda/envs/sage-backend' }, isPackaged: false },
    'backend.cli.components',
    ['list', '--json'],
  );
  expect(plan?.args).toEqual(['-m', 'backend.cli.components', 'list', '--json']);
});
```

- [ ] **Step 2: 实现**

```ts
export type CliLaunchPlan = DoctorLaunchPlan;

export function resolveModuleLaunchCommand(
  opts: ResolveOpts,
  moduleName: string,
  moduleArgs: string[],
): CliLaunchPlan | undefined {
  const plan = resolveBackendLaunchCommand(opts);
  if (plan.kind === 'broken-installer') return undefined;
  const args = [...plan.args];
  const mainIdx = args.lastIndexOf('backend.main');
  if (mainIdx >= 0) args.splice(mainIdx, 1, moduleName, ...moduleArgs);
  else args.push('-m', moduleName, ...moduleArgs);
  return {
    command: plan.command,
    args,
    cwd: plan.cwd,
    env: { ...plan.env, ...plan.extraEnv },
    reason: plan.reason,
  };
}
```

- [ ] **Step 3: 运行测试**

```bash
npx vitest run electron/__tests__/backendLauncher.test.ts
```

- [ ] **Step 4: 提交**

```bash
git add electron/backendLauncher.ts electron/__tests__/backendLauncher.test.ts
git commit -m "refactor(electron): add generic module launch command"
```

---

## Task 6: Electron IPC `components:*`

**Files:**
- Create: `electron/componentsIpc.ts`
- Modify: `electron/main.ts`（注册）
- Modify: `electron/preload.ts`
- Modify: `src/shared/types/electron-api.d.ts`
- Test: `electron/__tests__/componentsIpc.test.ts`

**Interfaces:**
- IPC：
  - `components:list`
  - `components:scan`
  - `components:pick-and-import`
  - `components:import-path`
  - `components:remove`
- 进度事件：`sage:event:components:progress`
- preload bridge：`window.electronAPI.components`

- [ ] **Step 1: 写失败测试（JSON 行解析 + 路径校验）**

```ts
import { parseComponentEvents, validatePackagePath } from '../componentsIpc';

it('parses progress and result events', () => {
  const events = parseComponentEvents([
    '{"event":"progress","phase":"extract","done":1,"total":2}',
    '{"event":"result","ok":true,"installed":[]}',
  ].join('\n'));
  expect(events).toHaveLength(2);
  expect(events[0].event).toBe('progress');
});

it('rejects non-sagepkg paths', () => {
  expect(validatePackagePath('/tmp/x.zip')).toBe(false);
  expect(validatePackagePath('/tmp/x.sagepkg')).toBe(true);
});
```

- [ ] **Step 2: 实现 `componentsIpc.ts`**

要点：
- `runComponentCli(argv, resolveOpts, onEvent)`：
  - `resolveModuleLaunchCommand(opts, 'backend.cli.components', argv)`；
  - `spawn(command, args, { cwd, env: { ...process.env, ...plan.env }, windowsHide: true })`；
  - 逐行解析 stdout JSON；`progress` 事件转 `sage:event:components:progress`；
  - 15 分钟超时 kill；
  - 返回最后一个 `result` 事件。
- `pick-and-import` 使用 `dialog.showOpenDialog({ filters: [{ name: 'Sage component', extensions: ['sagepkg'] }] })`。
- `import-path` 只接受绝对路径、`.sagepkg` 后缀、存在；id 用 `^[a-z0-9][a-z0-9._-]{0,63}$`。
- `main.ts` 注册：

```ts
registerComponentsIpc(ipcMain, {
  getWindow: () => mainWindow,
  resolveOpts: () => ({
    env: process.env,
    resourcesPath: process.resourcesPath,
    platform: process.platform,
    isPackaged: app.isPackaged,
    sageDbPath: resolveSageDbPath(),
    sageUserDataDir: resolveSageUserDataDir(),
    port: BACKEND_PORT,
  }),
});
```

- [ ] **Step 3: preload + 类型**

```ts
components: {
  list: () => ipcRenderer.invoke('components:list'),
  scan: () => ipcRenderer.invoke('components:scan'),
  pickAndImport: () => ipcRenderer.invoke('components:pick-and-import'),
  importPath: (path: string) => ipcRenderer.invoke('components:import-path', path),
  remove: (id: string) => ipcRenderer.invoke('components:remove', id),
},
```

`electron-api.d.ts` 定义 `InstalledComponentSummary`、`ComponentPackageSummary`、`ComponentsElectronApiBridge`，并在 `ElectronAPI` 加 `components?: ComponentsElectronApiBridge;`。

- [ ] **Step 4: 运行测试 + 类型检查**

```bash
npx vitest run electron/__tests__/componentsIpc.test.ts
npx tsc -p tsconfig.electron.json --noEmit
```

- [ ] **Step 5: 提交**

```bash
git add electron/componentsIpc.ts electron/main.ts electron/preload.ts src/shared/types/electron-api.d.ts electron/__tests__/componentsIpc.test.ts
git commit -m "feat(electron): add offline component import IPC"
```

---

## Task 7: 设置页「组件管理」UI

**Files:**
- Create: `src/pages/settings/ComponentsTab.tsx`
- Create: `src/shared/lib/i18n/locales/zh/components.ts`
- Create: `src/shared/lib/i18n/locales/en/components.ts`
- Modify: `src/shared/lib/i18n/zh.ts`
- Modify: `src/shared/lib/i18n/en.ts`
- Modify: `src/pages/settings/settingsTabs.tsx`
- Modify: `src/pages/settings/settingsSearchEntries.ts`
- Modify: `src/pages/settings/__tests__/settingsTabs.guards.test.ts`
- Test: `src/pages/settings/__tests__/ComponentsTab.test.tsx`

**Interfaces:**
- Tab key：`components`，group `maintenance`，labelKey `settings.tab.components`
- 搜索索引至少 1 条：`key: 'components'`, `tab: 'components'`
- 守卫测试 tab 数量 19 → 20

- [ ] **Step 1: 写失败测试**

```tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ComponentsTab } from '../ComponentsTab';

it('renders installed components and imports a package', async () => {
  const list = vi.fn().mockResolvedValue({
    ok: true,
    installed: [{ id: 'embedding-demo', name: 'Demo', version: '1.0.0', target: 'user_data', installedAt: '', fileCount: 1, totalBytes: 10 }],
    discovered: [],
  });
  const pickAndImport = vi.fn().mockResolvedValue({ ok: true });
  (window as any).electronAPI = {
    components: { list, scan: vi.fn().mockResolvedValue({ ok: true, discovered: [] }), pickAndImport, importPath: vi.fn(), remove: vi.fn() },
    listen: vi.fn().mockResolvedValue(() => {}),
  };
  render(<ComponentsTab />);
  expect(await screen.findByText('Demo')).toBeInTheDocument();
  fireEvent.click(screen.getByTestId('components-import'));
  await waitFor(() => expect(pickAndImport).toHaveBeenCalled());
});
```

- [ ] **Step 2: 实现 UI**

- 顶部说明 + 「导入 .sagepkg」「刷新」按钮。
- 已安装列表：名称、id、版本、大小、target、安装时间、删除按钮。
- 可扫描包列表：路径、id/version、导入按钮。
- 导入中禁用按钮，展示 `components:progress` 阶段与进度条（若 total>0）。
- 成功提示「导入完成，请重启 Sage 后生效」；失败展示错误。
- 桌面端不可用（web 模式）显示提示。
- 删除使用 `window.confirm` 二次确认。

- [ ] **Step 3: i18n + tab 注册**

新增 `zhComponents` / `enComponents` 并聚合；`settingsTabs.tsx` 在 `updates` 后加：

```tsx
{
  key: 'components',
  labelKey: 'settings.tab.components',
  group: 'maintenance',
  render: () => <ComponentsTab />,
},
```

搜索索引追加一条；守卫测试数量改 20。

- [ ] **Step 4: 运行前端测试**

```bash
npx vitest run \
  src/pages/settings/__tests__/ComponentsTab.test.tsx \
  src/pages/settings/__tests__/settingsTabs.guards.test.ts
```

- [ ] **Step 5: 提交**

```bash
git add src/pages/settings/ComponentsTab.tsx src/pages/settings/settingsTabs.tsx \
  src/pages/settings/settingsSearchEntries.ts src/pages/settings/__tests__/ComponentsTab.test.tsx \
  src/pages/settings/__tests__/settingsTabs.guards.test.ts \
  src/shared/lib/i18n
git commit -m "feat(settings): add offline component manager tab"
```

---

## Task 8: 组件包构建脚本 + 发布流水线

**Files:**
- Create: `scripts/build-component-packs.py`
- Create: `scripts/gen-component-keypair.py`
- Create: `resources/component-public-key.pem`（公开公钥；私钥由 `.secrets/` 持有，不入库）
- Modify: `.gitignore`
- Modify: `electron-builder.yml`（extraResources 增加公钥文件）
- Modify: `.github/workflows/release-win7.yml`

**Interfaces:**
- `python scripts/build-component-packs.py --all --key <private.pem> --output release/components`
  - 产出：`embedding-bge-small-zh-<version>-win7.sagepkg`、`ocr-models-ppocr-<version>-win7.sagepkg`、`components-index.json`
- `python scripts/gen-component-keypair.py --out-dir .secrets` → `.secrets/component-private-key.pem` + `resources/component-public-key.pem`
- `python scripts/build-component-packs.py --print-public-key --key <private.pem>` → PEM 到 stdout

- [ ] **Step 1: 写构建脚本测试（可 import 的函数）**

```python
from pathlib import Path
from scripts.build_component_packs import build_pack


def test_build_pack_roundtrip(tmp_path: Path, key_path: Path):
    src = tmp_path / "models" / "demo"
    src.mkdir(parents=True)
    (src / "a.bin").write_bytes(b"abc")
    out = build_pack(
        component_id="demo",
        name="Demo",
        version="1.0.0",
        source_dir=src,
        payload_prefix="models/demo",
        output_dir=tmp_path / "out",
        private_key_path=key_path,
        branch="win7",
        python_version="3.8",
    )
    assert out.is_file()
```

- [ ] **Step 2: 实现构建脚本**

- 用 `zipfile.ZipFile(..., ZIP_DEFLATED)`，固定 `date_time=(1980, 1, 1, 0, 0, 0)`。
- `component.json` 使用 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`。
- 签名：`key.sign(body, padding.PKCS1v15(), hashes.SHA256())`。
- payload 路径：`models/<dir>/...`，与现有 userData 查找路径兼容。
- `--all` 构建两个内置 spec；缺少 `resources/models/...` 时给出明确错误。
- `--print-public-key` 输出 PEM。
- `components-index.json` 记录每个包的 sha256/size/version/signature。

- [ ] **Step 3: 生成密钥与公钥**

```bash
cd /home/fz/project/sage/.worktrees/feat-offline-component-packs
/home/fz/anaconda3/envs/sage-backend-py38/bin/python scripts/gen-component-keypair.py --out-dir .secrets
# .secrets/component-private-key.pem 不入库；resources/component-public-key.pem 入库
```

`.gitignore` 增加：

```
.secrets/
*.component-private.pem
component-private-key.pem
```

- [ ] **Step 4: 本地端到端验证**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python scripts/build-component-packs.py \
  --all --key .secrets/component-private-key.pem --output /tmp/sage-components
SAGE_COMPONENT_PUBLIC_KEY_PATH=resources/component-public-key.pem \
SAGE_USER_DATA_DIR=/tmp/sage-ud \
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m backend.cli.components \
  import /tmp/sage-components/embedding-bge-small-zh-*-win7.sagepkg --json --yes
# 期望：result ok=true；/tmp/sage-ud/models/bge-small-zh-v1.5/model.onnx 存在
```

- [ ] **Step 5: 接入 release-win7.yml**

Source job，在 `Fetch local AI models` 之后：

```yaml
      - name: Build offline component packs
        shell: pwsh
        env:
          SAGE_COMPONENT_SIGNING_KEY: ${{ secrets.SAGE_COMPONENT_SIGNING_KEY }}
        run: |
          if ([string]::IsNullOrWhiteSpace($env:SAGE_COMPONENT_SIGNING_KEY)) {
            Write-Host "::warning::SAGE_COMPONENT_SIGNING_KEY not configured; skipping component packs"
            exit 0
          }
          $keyPath = Join-Path $env:RUNNER_TEMP 'component-signing-key.pem'
          Set-Content -Path $keyPath -Value $env:SAGE_COMPONENT_SIGNING_KEY -NoNewline
          python -m pip install "cryptography==47.0.0"
          python scripts/build-component-packs.py --all --key $keyPath --output release/components
          python scripts/build-component-packs.py --print-public-key --key $keyPath |
            Set-Content -Path resources/component-public-key.pem -Encoding ascii

      - name: Upload component packs as artifact
        uses: actions/upload-artifact@v4
        with:
          name: sage-components
          path: release/components/*
          if-no-files-found: warn
```

`upload-release` job 增加下载 `sage-components`，并把 `artifacts/components/**/*` 加入 `files:`。

- [ ] **Step 6: 提交**

```bash
git add scripts/build-component-packs.py scripts/gen-component-keypair.py \
  resources/component-public-key.pem .gitignore electron-builder.yml \
  .github/workflows/release-win7.yml
git commit -m "feat(build): generate signed offline component packs"
```

---

## Task 9: 文档与归档

**Files:**
- Create: `docs/technical/161-offline-component-packs.md`
- Modify: `docs/technical/README.md`
- Modify: `docs/technical/101-win7-offline-maintenance.md`
- Create: `docs/user-manual/54-offline-component-packs.md`
- Modify: `docs/user-manual/README.md`

- [ ] **Step 1: 技术文档**

内容：
- `.sagepkg` 格式与签名校验链；
- `target` 语义（`user_data` 只允许 `models/`；`component_dir`）；
- 内网导入三条路径（UI / SageDoctor / 共享盘自动扫描）；
- 构建命令、CI secret、公钥替换流程；
- 安全边界（不执行 pip/npm、签名必需、zip slip 防护、路径白名单）；
- 全量安装包保持不变，组件包为独立资产。

- [ ] **Step 2: 用户手册**

内容：
- 内网管理员如何通过 SageDoctor `components import` 导入；
- 设置页「组件管理」操作步骤；
- 导入后重启生效；
- 常见错误（未配置公钥、签名无效、文件被占用、版本不匹配）。

- [ ] **Step 3: 更新 README 索引与 101 交叉链接**

- [ ] **Step 4: 提交**

```bash
git add docs/technical/161-offline-component-packs.md docs/technical/README.md \
  docs/technical/101-win7-offline-maintenance.md \
  docs/user-manual/54-offline-component-packs.md docs/user-manual/README.md
git commit -m "docs: document offline component packs"
```

---

## Task 10: 全量验证

- [ ] **Step 1: 后端针对性测试（py38）**

```bash
cd /home/fz/project/sage/.worktrees/feat-offline-component-packs
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py \
  backend/tests/unit/cli/test_components_cli.py \
  backend/tests/unit/cli/test_rescue_cli.py -q
```

- [ ] **Step 2: py38 兼容 / ruff**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python scripts/check_py38_compat.py
/home/fz/anaconda3/envs/sage-backend-py38/bin/ruff check \
  backend/services/components backend/cli/components.py backend/cli/rescue.py \
  scripts/build-component-packs.py scripts/gen-component-keypair.py
```

- [ ] **Step 3: 前端测试**

```bash
npx vitest run \
  src/pages/settings/__tests__/ComponentsTab.test.tsx \
  src/pages/settings/__tests__/settingsTabs.guards.test.ts \
  electron/__tests__/componentsIpc.test.ts \
  electron/__tests__/backendLauncher.test.ts
```

- [ ] **Step 4: 类型与架构**

```bash
npm run typecheck
npx tsc -p tsconfig.electron.json --noEmit
node scripts/architecture-check.mjs
```

- [ ] **Step 5: 端到端冒烟（本地）**

1. 生成密钥与组件包；
2. 运行 `backend.cli.components import --json --yes`；
3. 验证 `userData/models/...` 落盘与 `installed.json`；
4. 验证篡改包被拒绝；
5. 验证 `remove` 清理文件。

---

## 风险与边界

- **签名私钥管理**：私钥绝不可入库；CI 用 `SAGE_COMPONENT_SIGNING_KEY` secret。仓库中的 `resources/component-public-key.pem` 必须与发布私钥配对；替换密钥后旧组件包全部失效。
- **文件占用**：Sage 运行中导入模型可能被 Windows 文件锁拒绝；UI 需提示“重启 Sage 后重试”，CLI 返回可读错误。
- **版本漂移**：组件包记录 `python`/`arch`/`branch`，导入时校验 Python/架构；win7 包不可用于 main。
- **全量安装包不变**：本计划不构建瘦安装包；全量 NSIS 继续作为内网默认，组件包用于补装/修复/按需安装。
- **后续**：瘦安装包（core variant）、组件目录浏览、自动更新组件、回滚保留旧版本，列入下一阶段。
