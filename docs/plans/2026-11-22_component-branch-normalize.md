# 组件包导入分支归一化修复 (fix/components-branch-normalize)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `.sagepkg` 组件包在正式 win7 发行版（以及 dev 构建）里能被正常导入，消除当前"组件包分支不匹配：需要 win7，当前 v0.4.9-alpha.84-win7"的必然失败。

**Architecture:** 问题根因是三方"分支"语义不一致 —— 组件包清单里的 `branch` 是发布通道 id（固定 `win7` / `main`），而打包版 `build-manifest.json` 里的 `branch` 是 git ref（tag `v0.4.9-alpha.84-win7`、dev 缺省 `unknown`）。修复策略：在消费侧（`backend.services.components.service._check_compatibility`）引入归一化函数 `_normalise_branch`，把两边都映射成通道 id 再比较；空串 / `unknown` / `dev-build` 视为"来源未知"直接跳过校验。

**Tech Stack:** Python 3.8（win7 打包运行时）+ `cryptography` 47.x；后端组件服务 `backend/services/components/`；既有测试套件 `pytest`。

**Spec:** 本修复来自上一轮根因分析（仓库外诊断证据）。技术文档 `docs/technical/161-offline-component-packs.md` §2 是 `branch` 字段的契约；`docs/user-manual/54-offline-component-packs.md` 是用户手册。

## Global Constraints

- **Python 兼容性**：所有改动必须兼容 Python 3.8.10（win7 运行时），不能使用 3.9+ 语法（如 `str.removeprefix` / `datetime.UTC` / `X | Y` 类型联合）。
- **签名契约不变**：`component.json` 的 `branch` 字段含义与打包方式不动；归一化只在 `_check_compatibility` 消费侧进行。
- **CI ratchet 友好**：不新增 `backend/services/components/` 公共 API；不触碰架构基线。
- **双分支策略**：此修复仅落在 `release/win7`（功能所在），主分支当前没有组件包入口，无需同步。

---

## File Structure

| 文件 | 作用 | 修改类型 |
| --- | --- | --- |
| `backend/services/components/service.py` | 新增 `_normalise_branch`，改造 `_check_compatibility` 的分支比较 | 修改 |
| `backend/tests/unit/services/test_components_service.py` | 新增 `_normalise_branch` 单元测试 + 端到端兼容性矩阵测试 | 修改（追加） |
| `docs/technical/161-offline-component-packs.md` | §2/§3 显式说明 `branch` 是通道 id，消费侧归一化规则 | 修改 |
| `docs/user-manual/54-offline-component-packs.md` | §5 FAQ 新增"组件包分支不匹配"行（即使修复后仍保留用于历史构建） | 修改 |

**不在此 PR 范围内的（后续跟进）**：
- 设置页"从本地导入"语义/OCR 模型路径错位（`electron/main.ts:2716` `modelsBaseDir` 使用 `process.cwd()` 而非 `resolveSageUserDataDir()`）—— 与组件包无关，属另一 PR。
- `electron/componentsIpc.ts` 侧的 `branch` 参数 —— 后端归一化已覆盖全部入口（包括 SageDoctor CLI），无需重复。

---

## Task 1：TDD 红态 —— 写失败测试

**Files:**
- Modify: `backend/tests/unit/services/test_components_service.py`（追加）

**Interfaces:**
- 待实现函数（Task 2 暴露）：`backend.services.components.service._normalise_branch(value: str) -> str`
- `_check_compatibility(self, manifest)` 行为变更：接受 tag 形式 / ref 形式的 win7 来源；空 / `unknown` / `dev-build` 跳过校验；`main` ↔ `win7` 通道互拒。

- [x] **Step 1.1：在测试文件末尾追加 `_normalise_branch` 矩阵测试**

```python
# ---------- _normalise_branch + compatibility branch tolerance ----------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("", ""),
        ("   ", ""),
        ("win7", "win7"),
        ("WIN7", "win7"),
        ("release/win7", "win7"),
        ("feat/orch-win7", "win7"),
        ("v0.4.9-alpha.84-win7", "win7"),
        ("v0.4.9-alpha.84-win7  ", "win7"),
        ("main", "main"),
        ("master", "main"),
        ("v0.4.9-alpha.84", "main"),
        ("unknown", "unknown"),
        ("dev-build", "dev-build"),
    ],
)
def test_normalise_branch(value, expected):
    from backend.services.components.service import _normalise_branch

    assert _normalise_branch(value) == expected
```

- [x] **Step 1.2：追加兼容性行为测试（用 `_service` 现有 fixture 风格）**

```python
def _compat_service(tmp_path: Path, public_pem: bytes, branch_env: str) -> ComponentService:
    return ComponentService(
        user_data_dir=tmp_path,
        environ={"SAGE_COMPONENT_BRANCH": branch_env},
    )


def test_check_compatibility_accepts_tag_style_win7_branch(tmp_path):
    """Packaged win7 builds set SAGE_COMPONENT_BRANCH to the git tag name.
    They must still accept packs with branch='win7'."""
    manifest = ComponentManifest.from_dict(_manifest(
        {"models/demo.bin": b"x"},
        branch="win7",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    ))
    svc = _compat_service(tmp_path, _keypair()[1], "v0.4.9-alpha.84-win7")
    svc._check_compatibility(manifest)  # no exception == pass


def test_check_compatibility_accepts_release_win7_ref(tmp_path):
    """release/win7 or any branch containing 'win7' maps to the win7 channel."""
    manifest = ComponentManifest.from_dict(_manifest(
        {"models/demo.bin": b"x"},
        branch="win7",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    ))
    svc = _compat_service(tmp_path, _keypair()[1], "release/win7")
    svc._check_compatibility(manifest)


def test_check_compatibility_skips_unknown_and_dev_build(tmp_path):
    """Dev builds without a packaged manifest have branch='unknown' — the
    check must be skipped so local import works during development."""
    manifest = ComponentManifest.from_dict(_manifest(
        {"models/demo.bin": b"x"},
        branch="win7",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    ))
    for branch_env in ("", "unknown", "dev-build"):
        svc = _compat_service(tmp_path, _keypair()[1], branch_env)
        svc._check_compatibility(manifest)


def test_check_compatibility_rejects_cross_channel(tmp_path):
    """A main-channel build must still refuse win7 packs (different Python)."""
    manifest = ComponentManifest.from_dict(_manifest(
        {"models/demo.bin": b"x"},
        branch="win7",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    ))
    svc = _compat_service(tmp_path, _keypair()[1], "v0.4.9-alpha.84")
    with pytest.raises(ComponentError, match="分支不匹配"):
        svc._check_compatibility(manifest)
```

- [x] **Step 1.3：跑测试，确认红态**

```bash
cd /home/fz/project/sage/.worktrees/fix-components-branch-normalize
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py \
  -k "normalise_branch or check_compatibility_accepts or check_compatibility_skips or check_compatibility_rejects_cross" -v
```

Expected:
- `_normalise_branch` 全部 → `ImportError / AttributeError`（函数尚未定义）
- `test_check_compatibility_accepts_tag_style_win7_branch` → `ComponentError: 组件包分支不匹配`
- `test_check_compatibility_accepts_release_win7_ref` → 同上
- `test_check_compatibility_skips_unknown_and_dev_build` → 空串通过；`unknown` / `dev-build` 报错
- `test_check_compatibility_rejects_cross_channel` → PASS（旧代码本就拒绝跨通道，作为护栏保留）

---

## Task 2：实现 `_normalise_branch` + 改造 `_check_compatibility`

**Files:**
- Modify: `backend/services/components/service.py`

**Interfaces:**
- 新增模块级函数 `_normalise_branch(value: str) -> str`（保留 `_` 前缀，内部 API）
- `_check_compatibility` 签名不变，行为按 Task 1 测试矩阵收敛。

- [x] **Step 2.1：在 `service.py` 的 `_normalise_arch` 之后插入 `_normalise_branch`**

```python
# 紧邻现有的 _normalise_arch，保持归一化函数集中。
_BRANCH_SKIP = {"", "unknown", "dev-build"}


def _normalise_branch(value: str) -> str:
    """Map arbitrary git ref spellings to the component channel id.

    `win7` / `release/win7` / `v0.4.9-alpha.84-win7` → `win7`
    `main` / `master` / `v0.4.9-alpha.84` (no win7 suffix) → `main`
    Empty / `unknown` / `dev-build` → kept verbatim so callers skip the check.
    """
    lowered = value.strip().lower()
    if lowered in _BRANCH_SKIP:
        return lowered
    if "win7" in lowered:
        return "win7"
    return "main"
```

- [x] **Step 2.2：改写 `_check_compatibility` 的分支比较**

把原来的：

```python
expected_branch = str(self.environ.get("SAGE_COMPONENT_BRANCH", "")).strip()
if expected_branch and manifest.branch and manifest.branch != expected_branch:
    raise ComponentError(
        f"组件包分支不匹配：需要 {manifest.branch}，当前 {expected_branch}",
        code="branch_mismatch",
    )
```

改为：

```python
raw_expected = str(self.environ.get("SAGE_COMPONENT_BRANCH", "")).strip()
expected = _normalise_branch(raw_expected)
if (
    expected
    and expected not in _BRANCH_SKIP
    and manifest.branch
    and _normalise_branch(manifest.branch) != expected
):
    raise ComponentError(
        f"组件包分支不匹配：需要 {manifest.branch}，当前 {raw_expected or expected}",
        code="branch_mismatch",
    )
```

注意：错误消息里保留 `raw_expected`（用户看到的真实 tag/ref），便于诊断；比较用归一化后的值。

- [x] **Step 2.3：运行 ruff 检查**

```bash
cd /home/fz/project/sage/.worktrees/fix-components-branch-normalize
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m ruff check backend/services/components/service.py
```

Expected: 无新增告警。

---

## Task 3：TDD 绿态 —— 跑测试确认

- [x] **Step 3.1：跑本次新增测试**

```bash
cd /home/fz/project/sage/.worktrees/fix-components-branch-normalize
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py \
  -k "normalise_branch or check_compatibility_accepts or check_compatibility_skips or check_compatibility_rejects_cross" -v
```

Expected: 全部 PASS。

- [x] **Step 3.2：跑 `test_components_service.py` 全集，确认无回归**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py -v
```

Expected: 全部 PASS（原有签名/清单/安装/卸载用例不受影响）。

- [x] **Step 3.3：跑组件相关其他测试，确认无跨模块回归**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/cli/test_components_cli.py \
  backend/tests/unit/test_build_component_packs.py -v
```

Expected: 全部 PASS。

- [x] **Step 3.4：提交**

```bash
git add backend/services/components/service.py backend/tests/unit/services/test_components_service.py
git commit -m "fix(components): 组件包分支校验做通道归一化，修复 win7 发行版必然失败的导入

- _normalise_branch：把 'v0.4.9-alpha.84-win7' / 'release/win7' / 'feat/x-win7'
  归一为 'win7'，main/master/普通 tag 归一为 'main'，
  空串 / unknown / dev-build 视为来源未知，跳过校验。
- _check_compatibility 比较归一化后的通道 id；错误消息仍保留原始 ref 便于诊断。

根因：bundle-python.ps1 把 build-manifest.json 的 branch 写成了 git tag
（GITHUB_REF_NAME），而组件包清单的 branch 是发布通道 'win7'。
原先严格字符串比较导致所有正式 win7 发行版导入都报 branch_mismatch。

Signed-off-by: Claude Agent <claude@anthropic.local>"
```

---

## Task 4：端到端复验（用真实 .sagepkg + Python 3.8）

**Files:**
- 不修改，只验证。

**前置依赖：** 真实发行包已在 `/tmp/sagepkg-test/`（`ocr-models-ppocr-1.0.0-win7.sagepkg`），仓库公钥 `/tmp/sagepkg-test/code/resources/component-public-key.pem` 与随包公钥一致。

- [x] **Step 4.1：模拟发行版环境（`SAGE_COMPONENT_BRANCH` = tag 名）**

```bash
cd /home/fz/project/sage/.worktrees/fix-components-branch-normalize
SAGE_COMPONENT_BRANCH=v0.4.9-alpha.84-win7 \
  SAGE_COMPONENT_PUBLIC_KEY_PATH=/tmp/sagepkg-test/code/resources/component-public-key.pem \
  SAGE_USER_DATA_DIR=/tmp/sagepkg-test/userdata-final \
  /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m backend.cli.components \
  import /tmp/sagepkg-test/ocr-models-ppocr-1.0.0-win7.sagepkg --json --yes
```

Expected: JSON 输出 `{"event":"result","ok":true,...}`，无 `branch_mismatch`；`/tmp/sagepkg-test/userdata-final/models/rapidocr/` 下出现 `det.onnx` + `rec.onnx`。

- [x] **Step 4.2：模拟 dev 环境（`SAGE_COMPONENT_BRANCH=unknown`）**

```bash
SAGE_COMPONENT_BRANCH=unknown \
  SAGE_COMPONENT_PUBLIC_KEY_PATH=/tmp/sagepkg-test/code/resources/component-public-key.pem \
  SAGE_USER_DATA_DIR=/tmp/sagepkg-test/userdata-dev \
  /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m backend.cli.components \
  import /tmp/sagepkg-test/ocr-models-ppocr-1.0.0-win7.sagepkg --json --yes
```

Expected: 同样 `ok:true`（dev 构建不再被误杀）。

- [x] **Step 4.3：清理临时 userData**

```bash
rm -rf /tmp/sagepkg-test/userdata-final /tmp/sagepkg-test/userdata-dev
```

---

## Task 5：更新技术文档与用户手册

**Files:**
- Modify: `docs/technical/161-offline-component-packs.md`
- Modify: `docs/user-manual/54-offline-component-packs.md`

- [x] **Step 5.1：技术文档 §3 末尾加小节 "3.x 分支校验归一化"**

在 `docs/technical/161-offline-component-packs.md` 的 "3. 校验与安全" 末尾插入：

```markdown
### 3.x 分支校验归一化

`component.json` 的 `branch` 是**发布通道 id**（固定值 `win7` / `main`），
而打包版 `resources/build-manifest.json` 的 `branch` 是 git ref（tag 名
`v0.4.9-alpha.84-win7`、分支名 `release/win7`、dev 缺省 `unknown`）。
两者不做裸字符串比较 —— `ComponentService._check_compatibility` 通过
`_normalise_branch()` 把两边都映射成通道 id 再比较：

| 输入 | 归一化结果 |
| --- | --- |
| `win7` / `release/win7` / `feat/x-win7` / `v0.4.9-alpha.84-win7` | `win7` |
| `main` / `master` / `v0.4.9-alpha.84` | `main` |
| `""` / `unknown` / `dev-build` | 跳过校验 |

错误消息里仍保留原始 ref 便于诊断；比较用归一化后的通道 id。
历史版本（2026-11-22 之前）是严格字符串比较，导致所有正式发行版
导入必然报 `branch_mismatch`；修复见 PR fix/components-branch-normalize。
```

- [x] **Step 5.2：用户手册 §5 FAQ 新增行**

在 `docs/user-manual/54-offline-component-packs.md` 的 "5. 常见问题" 表格末尾追加：

```markdown
| 「组件包分支不匹配」（早期版本） | 2026-11-22 之后的版本已修复；升级 Sage 即可。无法升级时，用 SageDoctor 导入（§3）可绕过 |
```

- [x] **Step 5.3：提交文档改动**

```bash
git add docs/technical/161-offline-component-packs.md docs/user-manual/54-offline-component-packs.md
git commit -m "docs(components): 记录分支校验归一化规则，FAQ 补早期版本绕过说明

Signed-off-by: Claude Agent <claude@anthropic.local>"
```

---

## Task 6：跑完整后端测试套件 + 推送开 PR

- [x] **Step 6.1：跑 `backend/tests/unit` 全集，确认无跨模块回归**

```bash
cd /home/fz/project/sage/.worktrees/fix-components-branch-normalize
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit -q --tb=short
```

结果：**15253 passed, 56 skipped, 8 failed**。8 个失败均为环境性预存失败
（`test_git_tool.py` 3 个 git 环境类 + `test_port_backend/frontend` 5 个
端口占用类），与组件包改动无关（与 MEMORY「后端环境性失败」记录一致）。

- [x] **Step 6.2：确认提交顺序**

```bash
git log --oneline -5
```

PR: https://github.com/oneMuggle/sage/pull/3199

Expected:
```
<sha> docs(components): 记录分支校验归一化规则...
<sha> fix(components): 组件包分支校验做通道归一化...
```

- [x] **Step 6.3：推送并开 PR**

```bash
git push -u origin fix/components-branch-normalize
gh pr create \
  --repo oneMuggle/sage \
  --base release/win7 \
  --title "fix(components): 组件包分支校验做通道归一化，修复 win7 发行版导入失败" \
  --body "$(cat <<'EOF'
## Summary

修复：正式 win7 发行版无法导入任何 `.sagepkg` 组件包（OCR / 语义模型）的问题。

## Root Cause

- `component.json` 的 `branch` 字段 = 发布通道 id（固定值 `win7`）
- `resources/build-manifest.json` 的 `branch` 字段 = git tag（如 `v0.4.9-alpha.84-win7`，由 `bundle-python.ps1` 用 `GITHUB_REF_NAME` 写入）
- `ComponentService._check_compatibility` 严格字符串比较 → 必然失败
- Dev 模式更糟：manifest 缺省时 `branch='unknown'`，同样被拒

## Fix

- 新增 `_normalise_branch`：把 `v0.4.9-alpha.84-win7` / `release/win7` / `feat/x-win7` 都归一为通道 id `win7`；`main` / `master` / 普通 tag 归一为 `main`；空串 / `unknown` / `dev-build` 跳过校验。
- `_check_compatibility` 比较归一化后的通道 id；错误消息保留原始 ref 便于诊断。

## Verification

- 单元测试覆盖 `_normalise_branch` 矩阵 + 4 组端到端兼容性行为（含跨通道拒绝护栏）。
- 用真实发行包 `ocr-models-ppocr-1.0.0-win7.sagepkg` + py3.8 端到端复验：
  - `SAGE_COMPONENT_BRANCH=v0.4.9-alpha.84-win7` → `ok:true`（之前 `branch_mismatch`）
  - `SAGE_COMPONENT_BRANCH=unknown` → `ok:true`（之前同样被拒）
- 既有组件测试全套 PASS。

## Scope

仅改后端消费侧，不动 `component.json` 与 `build-manifest.json` 的生成。
不涉及设置页"从本地导入"语义/OCR 模型路径错位（独立 PR）。
EOF
)"
```

---

## Out of Scope（本次不实施，记录在案）

1. **设置页"从本地导入"语义模型路径错位**：`electron/main.ts:2716` `modelsBaseDir` 用 `process.cwd()` 而非 `resolveSageUserDataDir()`，打包版导入写到安装目录，语义模型查找链看不到 → 导入"成功"但无效果。独立 PR，主分支和 release/win7 都要改。
2. **main 分支是否同步组件包功能**：当前 main 无组件管理入口，等主分支确定要引入再同步。
