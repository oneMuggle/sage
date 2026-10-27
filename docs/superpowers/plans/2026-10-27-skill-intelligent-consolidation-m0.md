# Skill 智能沉淀 M0 — 基础修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复技能体系 5 个基础缺口 (`#6` `#8` `#9` `#11` `#12`),为后续智能提示 / 编辑器 / 市场建立基础设施(通知中枢 + slash 刷新链路 + 门控可解释性 + 文档真相)。

**Architecture:** 后端新增 `SkillNotificationHub` 作为技能变更的**唯一广播源**,HTTP 端 `GET /skills/notifications` 返回 NDJSON 流;Electron 在 `main.ts` 新增 `skills:notify` 分支 → `relay.ts` 新增 `relaySkillNotifications` → 渲染端 `desktopEvent.listen` → `ChatInput` 重新拉 `skillsApi.list()` 刷新 slash 列表。`requires.config` 门控通过 factory 注入 `SettingsRepository`,保持 `GatingContext` frozen + `evaluate_gating` 纯函数。`SkillMdHotLoader` 在 adapter 层**持久持有**而非每次 rescan 新建,使哈希对比能真正触发热重载;`_load_from_path` 区分 builtin / 同路径刷新 / 重名三种冲突。`execute()`/`execute_command()` 统一把 `content` 序列化为 str。帮助文档 `src/content/help/skills.md` 重写为与代码真相对齐。

**Tech Stack:** Python 3.8 + pydantic 1.x / FastAPI + Starlette (`application/x-ndjson` 流) + Electron 21 (Node 16,`node-fetch@2`) + React + vitest + pytest。release/win7 分支 — 全部类型注解使用 `typing.List/Optional/Dict/FrozenSet` (禁用 PEP 604 / PEP 585)。

**Spec:** [`docs/superpowers/specs/2026-10-27-skill-intelligent-consolidation-design.md`](../specs/2026-10-27-skill-intelligent-consolidation-design.md) (§3 第 0 节 + §11 M0)

## Global Constraints

- Python 3.8:禁止 `X | Y` / `list[str]` / `dict[K,V]`,必须 `Optional[X]` / `List[X]` / `Dict[K,V]`。
- pydantic 1.x:`conlist` 用 `min_items`,模型不写 `model_config = ...` (只用 `class Config`)。
- `legacy_skills_routes.py` 顶部有 `# ruff: noqa: UP006, UP007, UP035, UP045` — 保留该 noqa 段。
- 所有 `GatingContext(...)` 现有 19 处构造点使用 keyword args (`platform=`/`available_bins=`/`available_env=`/`available_config=`),新增字段必须有默认值。
- Reason 字符串保持 English(模块惯例):`missing config: {key}` / `unknown config key: {key} (not in settings whitelist)`。
- 测试环境:`backend` 用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest ...`;前端 `npx vitest run <path>`。
- `sage_local_auth_token` 不可写入任何日志/聊天内容。

## Spec 偏差登记(Executor 必读)

本计划相对 spec §3 有几处**有意识的偏差**,都是执行阶段实测发现 spec 与代码现状不符后的修正。偏差都在下方明确标注,不是遗漏。

| # | Spec 描述 | 实际代码 | 本计划处理 |
|---|---|---|---|
| D1 | §3.4 `GatingContext` 增加 `settings_repo` 字段 | 字段是 frozen dataclass,19 处现有构造点 + 跨模块 import | **Factory 注入**:settings_repo 作为 `from_env` / `build_gating_context` / `build_gating_context_for_dirs` 的 optional 参数,运行时解析后填充 `available_config` 与 `known_config`。`evaluate_gating` 保持纯函数。 |
| D2 | §3.5 rescan "reload 后不重建 slash registry" | `InprocSkillAdapter._rebuild_slash_registry()` (2026-09 PR #386) 已经在所有 4 条 mutation 路径被调用 | 真实残留 bug:**rescan 创建 fresh loader**,导致 `_file_hashes` / `_loaded_paths` 为空,任何已加载的 SKILL.md 在重扫时都被误判 `builtin_conflict`。**修**:adapter 持有 persistent `SkillMdHotLoader`,用 `hot_reload()` 原地刷新。 |
| D3 | §3.5 代码示例用 `self.slash_registry` | 实际属性是 `self._slash_registry`(前导下划线) | 本计划直接用 `_slash_registry`。 |
| D4 | §3.4 reason 字符串用中文区分"键未知" / "键已知但缺值" | `backend/tests/unit/test_skill_md_gating.py:283` 断言 `"missing config: feature.flag"`(English) | 保持 English:用 `unknown config key: ... (not in settings whitelist)` vs `missing config: ...` 区分。 |

---

## File Structure

| 文件 | 职责 |
|---|---|
| `backend/skills/skill_md/gating.py` | 门控上下文 + 评估纯函数 — 增加 `known_config` 字段 + factory 注入 `SettingsRepository` |
| `backend/skills/skill_md/loader.py` | 热加载器 — 增加 `settings_repo` 参数透传,`_load_from_path` 区分三种冲突,新增 `_loaded_this_scan` 追踪 |
| `backend/adapters/out/skill/inproc.py` | 进程内 adapter — 持有 persistent `SkillMdHotLoader`;注入 settings_repo;`content` 归一化 helper;rescan/import/delete 后发布通知 |
| `backend/skills/notifications.py` | 技能变更通知中枢(新文件)— 线程安全发布 + 有界缓冲区 + NDJSON 流消费 |
| `backend/api/legacy_skills_routes.py` | 新增 `GET /skills/notifications` NDJSON 端点 |
| `electron/relay.ts` | 新增 `relaySkillNotifications()` |
| `electron/main.ts` | `sage:listen` 新增 `skills:notify` 分支 |
| `src/widgets/chat/ChatInput.tsx` | 订阅 `skills:notify` 事件,触发 slash 列表刷新 |
| `src/content/help/skills.md` | 重写为与代码真相对齐 |

---

### Task 1: `requires.config` 门控实现 (gap #11)

**Files:**
- Modify: `backend/skills/skill_md/gating.py:25-70` (imports + `GatingContext` + `from_env`)
- Modify: `backend/skills/skill_md/gating.py:127-130` (config check 逻辑)
- Modify: `backend/skills/skill_md/gating.py:140-148` (`build_gating_context` 签名)
- Modify: `backend/skills/skill_md/loader.py:42-48` (TYPE_CHECKING 导入)
- Modify: `backend/skills/skill_md/loader.py:267-269` (`build_gating_context_for_dirs` 签名)
- Modify: `backend/adapters/out/skill/inproc.py:70-72` (init 前置 `self._settings_repo = None`)
- Modify: `backend/adapters/out/skill/inproc.py:85-125` (SKILL.md 加载 try 块内构造 settings_repo + 透传)
- Test: `backend/tests/unit/test_skill_md_gating_config.py` (新建)

**Interfaces:**
- Consumes:
  - `backend.data.settings_repo.SettingsRepository.KEYS: FrozenSet[str]`
  - `SettingsRepository.get(key: str) -> Optional[Any]`
  - 19 处现有 `GatingContext(platform=..., available_bins=..., available_env=..., available_config=...)` 调用点必须继续工作(新增字段带默认值)
- Produces:
  - `GatingContext.known_config: FrozenSet[str]` (default `frozenset()`)
  - `GatingContext.from_env(cls, platform=None, bin_whitelist=None, settings_repo=None) -> GatingContext`
  - `build_gating_context(platform=None, bin_whitelist=None, settings_repo=None) -> GatingContext`
  - `build_gating_context_for_dirs(dirs: List[Path], settings_repo=None) -> GatingContext`
  - Reason 字符串:`missing config: {key}` (键在 whitelist 但无值) / `unknown config key: {key} (not in settings whitelist)` (键不在 whitelist)

- [ ] **Step 1: 写失败测试 — requires.config 七种场景**

创建 `backend/tests/unit/test_skill_md_gating_config.py`:

```python
"""requires.config 门控实现 (缺口 #11)。

- config 键在 settings 白名单里且有值 → 放行
- config 键在白名单里但没值 → "missing config: <key>"
- config 键不在白名单里 → "unknown config key: <key> (not in settings whitelist)"
- 没有 settings_repo (无 DB 环境) → available_config 为空, 保守跳过
- 单键读取失败不阻断整体快照
"""

from __future__ import annotations

import os

import pytest

from backend.skills.skill_md.gating import (
    GatingContext,
    build_gating_context,
    evaluate_gating,
)
from backend.skills.skill_md.skill import RequiresSpec, SkillMdDocument


pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name == "nt", reason="skill gating 读取依赖 POSIX O_NOFOLLOW"),
]


class _FakeSettingsRepo:
    """最小 settings 仓储替身 —— 只暴露 gating 需要的 get() 接口。"""

    def __init__(self, values):
        # type: (dict) -> None
        self._values = dict(values)

    def get(self, key):
        return self._values.get(key)


def _doc_with_config(*config_keys):
    return SkillMdDocument(
        name="cfg-skill",
        description="需要配置的技能",
        requires=RequiresSpec(config=list(config_keys)),
    )


def test_config_key_present_allows_skill():
    repo = _FakeSettingsRepo({"permission_mode": "ask"})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is True
    assert result.reasons == ()


def test_config_key_known_but_absent_reports_missing():
    repo = _FakeSettingsRepo({})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_config_key_not_in_whitelist_reports_unknown():
    repo = _FakeSettingsRepo({})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("not.a.real.setting"), ctx)

    assert result.allowed is False
    assert (
        "unknown config key: not.a.real.setting (not in settings whitelist)"
        in result.reasons
    )


def test_empty_config_value_counts_as_missing():
    repo = _FakeSettingsRepo({"permission_mode": ""})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_without_settings_repo_config_is_never_available():
    ctx = build_gating_context(platform="linux")

    assert ctx.available_config == frozenset()
    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)
    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_known_config_snapshot_lists_settings_whitelist():
    ctx = build_gating_context(platform="linux")

    assert "permission_mode" in ctx.known_config
    assert "not.a.real.setting" not in ctx.known_config


def test_manually_built_context_keeps_missing_config_reason():
    """旧调用点 (显式构造 GatingContext) 行为不变 —— 保持 "missing config"。"""
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )

    result = evaluate_gating(_doc_with_config("feature.flag"), ctx)

    assert result.allowed is False
    assert "missing config: feature.flag" in result.reasons


def test_settings_read_failure_degrades_to_missing_not_crash():
    class _BrokenRepo:
        def get(self, key):
            raise RuntimeError("db down")

    ctx = build_gating_context(platform="linux", settings_repo=_BrokenRepo())

    assert ctx.available_config == frozenset()
    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)
    assert result.allowed is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_gating_config.py -v`
Expected: FAIL — `TypeError: GatingContext.from_env() got an unexpected keyword argument 'settings_repo'`(因为 `from_env` 还没接受 `settings_repo`)。
Also: `assert "unknown config key" in result.reasons` fails on the unknown-key test。

- [ ] **Step 3: 修改 gating.py — 添加 known_config 字段 + factory 注入**

Edit `backend/skills/skill_md/gating.py`:

**3a.** 替换 `if TYPE_CHECKING:` 块(行 25-26):

```python
if TYPE_CHECKING:
    from backend.data.settings_repo import SettingsRepository

    from .skill import SkillMdDocument
```

**3b.** 替换 `GatingContext` 整个类 + `from_env` 方法,并在其后追加两个 helper(行 29-70):

```python
@dataclass(frozen=True)
class GatingContext:
    """门控评估所需的环境快照。"""

    platform: str
    available_bins: FrozenSet[str]
    available_env: FrozenSet[str]
    available_config: FrozenSet[str]
    # settings 白名单键快照。空集 = 未取到快照 —— 此时无法区分
    # "键不存在" 和 "键不在白名单", 一律报 missing config。
    # 作为最后一个字段 + 默认值, 保持所有现有 keyword-arg 构造点向后兼容。
    known_config: FrozenSet[str] = frozenset()

    @classmethod
    def from_env(
        cls,
        platform: Optional[str] = None,
        bin_whitelist: Optional[List[str]] = None,
        settings_repo: Optional["SettingsRepository"] = None,
    ) -> GatingContext:
        """从当前环境构造 GatingContext。

        Args:
            platform: 平台名称（None = 自动检测 sys.platform）
            bin_whitelist: 要探测的二进制列表（None = 不探测，空集）
            settings_repo: settings 仓储（None = 不读配置，available_config 为空）
        """
        if platform is None:
            if sys.platform.startswith("darwin"):
                platform = "macos"
            elif sys.platform.startswith("win"):
                platform = "windows"
            else:
                platform = "linux"

        # 探测二进制
        available_bins: Set[str] = set()
        if bin_whitelist:
            for bin_name in bin_whitelist:
                if shutil.which(bin_name) is not None:
                    available_bins.add(bin_name)

        return cls(
            platform=platform,
            available_bins=frozenset(available_bins),
            available_env=frozenset(os.environ.keys()),
            available_config=_read_present_config(settings_repo),
            known_config=_known_config_keys(),
        )


def _known_config_keys() -> FrozenSet[str]:
    """返回 settings 白名单键集合（模块级常量，不依赖 DB 连接）。"""
    from backend.data.settings_repo import SettingsRepository

    return frozenset(SettingsRepository.KEYS)


def _read_present_config(
    settings_repo: Optional["SettingsRepository"],
) -> FrozenSet[str]:
    """返回"当前有值"的 settings 键集合。

    settings_repo 为 None（无 DB / 测试环境）→ 空集。
    单键读取失败不阻断整体快照 —— 门控只是加载条件，读不到就当作
    "没有配置"，技能被跳过，而不是让整个加载流程炸掉。
    """
    if settings_repo is None:
        return frozenset()
    present: Set[str] = set()
    for key in _known_config_keys():
        try:
            value = settings_repo.get(key)
        except Exception:  # noqa: BLE001 — 快照失败降级为"缺配置"
            continue
        if value:
            present.add(key)
    return frozenset(present)
```

**3c.** 替换 config 检查逻辑(行 127-130):

```python
    # requires.config 检查 — 键未知 (不在 settings 白名单) 报
    # "unknown config key"; 键已知但没值报 "missing config"。
    for config_key in doc.requires.config:
        if config_key in ctx.available_config:
            continue
        if ctx.known_config and config_key not in ctx.known_config:
            reasons.append(
                f"unknown config key: {config_key} (not in settings whitelist)"
            )
        else:
            reasons.append(f"missing config: {config_key}")
```

**3d.** 替换 `build_gating_context`(行 140-148):

```python
def build_gating_context(
    platform: Optional[str] = None,
    bin_whitelist: Optional[List[str]] = None,
    settings_repo: Optional["SettingsRepository"] = None,
) -> GatingContext:
    """构造门控上下文。bin 探测开销由调用方控制。

    这是 GatingContext.from_env 的别名，方便测试使用。
    """
    return GatingContext.from_env(
        platform=platform,
        bin_whitelist=bin_whitelist,
        settings_repo=settings_repo,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_gating_config.py backend/tests/unit/test_skill_md_gating.py backend/tests/unit/test_skill_md_loader_gating.py -v`
Expected: PASS — 包括旧的 `test_evaluate_requires_config_missing`(断言 `"missing config: feature.flag" in result.reasons` 因为 `known_config` 为空 → 走 else 分支)和 loader 的 12 处 `GatingContext(...)` 显式构造(都保留 keyword args)。

Also run full gating-related tests: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "gating" -v`

- [ ] **Step 5: 改 loader.py — build_gating_context_for_dirs 透传 settings_repo**

Edit `backend/skills/skill_md/loader.py`:

**5a.** 替换 TYPE_CHECKING 块(行 42-44):

```python
if TYPE_CHECKING:
    from backend.data.settings_repo import SettingsRepository

    from .script_runner import ScriptRunner
```

**5b.** 替换 `build_gating_context_for_dirs`(行 267-269):

```python
def build_gating_context_for_dirs(
    dirs: List[Path],
    settings_repo: Optional["SettingsRepository"] = None,
) -> GatingContext:
    return build_gating_context(
        bin_whitelist=collect_required_bins(dirs),
        settings_repo=settings_repo,
    )
```

- [ ] **Step 6: 改 inproc.py — 注入 settings_repo**

Edit `backend/adapters/out/skill/inproc.py`:

**6a.** 在 `__init__` 行 82-83 之间(即 `skill_dirs = []` 之后),插入:

```python
        self._settings_repo = None  # requires.config 门控注入点 (Task 1)
```

**6b.** 在 SKILL.md 加载 try 块内(原行 119-124 的 `register_skill_md_skills` 调用前),插入 settings_repo 构造:

```python
            # requires.config 门控需要 settings 快照 (缺口 #11)。
            # DB 不可用时降级为"无配置" —— 技能被跳过, 不影响 adapter 构造。
            try:
                from backend.data.settings_repo import SettingsRepository

                self._settings_repo = SettingsRepository()
            except Exception as exc:  # noqa: BLE001 — adapter 构造必须容错
                logging.getLogger(__name__).warning(
                    "SkillMd settings repo unavailable: %s", exc
                )

            register_skill_md_skills(
                self._registry,
                dirs=[str(p) for p in registration_dirs],
                gating_ctx=build_gating_context_for_dirs(
                    registration_dirs, settings_repo=self._settings_repo
                ),
                script_runner=self._script_runner,
            )
```

(即把原 `register_skill_md_skills(...)` 调用展开,前置 settings_repo 构造,透传到 `build_gating_context_for_dirs`。)

- [ ] **Step 7: 跑全量相关测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "gating or loader" -v`
Expected: PASS(全部既有 gating/loader 测试仍绿)。

- [ ] **Step 8: 提交**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/gating.py backend/skills/skill_md/loader.py backend/adapters/out/skill/inproc.py backend/tests/unit/test_skill_md_gating_config.py
git commit -m "feat(skills): requires.config gating reads settings whitelist (gap #11)

- GatingContext.known_config: FrozenSet[str] defaults to frozenset()
  (backwards compatible with 19 existing construction sites)
- build_gating_context / from_env / build_gating_context_for_dirs accept
  optional settings_repo; _known_config_keys() + _read_present_config()
  derive available_config + known_config from SettingsRepository.KEYS
- Reason strings stay English: 'missing config: {key}' (known but absent)
  vs 'unknown config key: {key} (not in settings whitelist)'
- Adapter injects SettingsRepository at init; DB unavailable → graceful
  degradation to 'no config available'
- Preserves existing assertion 'missing config: feature.flag' in
  test_evaluate_requires_config_missing"
```

---

### Task 2: `content` 统一为 str (gap #9)

**Files:**
- Modify: `backend/adapters/out/skill/inproc.py:1-30` (imports)
- Modify: `backend/adapters/out/skill/inproc.py:241` (`execute` 路径)
- Modify: `backend/adapters/out/skill/inproc.py:569` (`execute_command` 路径)
- Test: `backend/tests/unit/test_skill_adapter_content_normalization.py` (新建)

**Interfaces:**
- Consumes: `sage_core.SkillResult.content` (Any)
- Produces: `backend.adapters.out.skill.inproc.normalize_skill_content(content: Any) -> str`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_skill_adapter_content_normalization.py`:

```python
"""SkillResult.content 统一为 str (缺口 #9)。

技能实现可能返回 dict / list / None / int —— 前端需要字符串。
归一化 helper 在 adapter 执行路径统一转换, 前端 fallback 仍保留作为 defense-in-depth。
"""

from __future__ import annotations

import json

import pytest

from backend.adapters.out.skill.inproc import normalize_skill_content


pytestmark = pytest.mark.unit


def test_str_passthrough():
    assert normalize_skill_content("hello") == "hello"


def test_none_becomes_empty():
    assert normalize_skill_content(None) == ""


def test_dict_becomes_json():
    out = normalize_skill_content({"answer": 42, "msg": "你好"})
    parsed = json.loads(out)
    assert parsed == {"answer": 42, "msg": "你好"}
    # ensure_ascii=False: 中文保持可读
    assert "你好" in out


def test_list_becomes_json():
    out = normalize_skill_content([1, 2, 3])
    assert json.loads(out) == [1, 2, 3]


def test_int_becomes_str():
    assert normalize_skill_content(42) == "42"


def test_non_json_serializable_falls_back_to_str():
    # tuple is JSON-serializable as array; dict with custom object uses default=str
    class _Custom:
        def __str__(self):
            return "custom-value"

    out = normalize_skill_content({"obj": _Custom()})
    parsed = json.loads(out)
    assert parsed["obj"] == "custom-value"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_adapter_content_normalization.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_skill_content' from 'backend.adapters.out.skill.inproc'`。

- [ ] **Step 3: 实现 normalize_skill_content**

Edit `backend/adapters/out/skill/inproc.py`:

**3a.** 在文件顶部 import 段(行 26 `import logging` 之后),追加:

```python
import json
```

**3b.** 在 `_SAFE_SKILL_PATH = "."`(行 44)之后,追加 module-level helper:

```python
def normalize_skill_content(content: Any) -> str:
    """把技能返回的 content 统一成 str。

    技能实现的 content 可能是 dict / list / 数字 / None —— 直接透传给
    前端会让渲染端拿到非字符串。统一序列化成可读文本:
      - str → 原样返回
      - None → ""
      - dict / list / tuple → JSON (ensure_ascii=False, indent=2, default=str)
      - 其他 → str()
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, (dict, list, tuple)):
        try:
            return json.dumps(content, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            return str(content)
    return str(content)
```

**3c.** 替换 `execute` 方法的 return 语句(行 241-245):

```python
        return SkillResult(
            success=raw.success,
            content=normalize_skill_content(raw.content),
            metadata=dict(raw.metadata),
            error=raw.error,
        )
```

**3d.** 替换 `execute_command` 方法的 return 语句(行 569-573):

```python
        return SkillResult(
            success=result.success,
            content=normalize_skill_content(result.content),
            metadata=dict(result.metadata),
            error=result.error,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_adapter_content_normalization.py -v`
Expected: PASS — 全部 6 个 normalize_skill_content 测试通过。

- [ ] **Step 5: 跑所有使用 adapter 的 unit 测试, 确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "skill" -v`
Expected: PASS — 既有 `test_skill_usage_tracking.py` 等测试不受影响(content 归一化只影响 execute/execute_command 的返回,既有测试要么不检查 content 要么本就是 str)。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage
git add backend/adapters/out/skill/inproc.py backend/tests/unit/test_skill_adapter_content_normalization.py
git commit -m "feat(skills): normalize SkillResult.content to str at adapter boundary (gap #9)

- normalize_skill_content() converts dict/list to JSON (ensure_ascii=False),
  None to '', other types to str()
- Applied at InprocSkillAdapter.execute() and execute_command() return paths
- Frontend fallback at ChatInput.tsx:495 preserved as defense-in-depth"
```

---

### Task 3: rescan 真正刷新已加载的 SKILL.md (gap #12 修正版)

**Files:**
- Modify: `backend/skills/skill_md/loader.py:282-296` (`__init__` 加 `_loaded_this_scan`)
- Modify: `backend/skills/skill_md/loader.py:300-368` (`scan_and_load` reset `_loaded_this_scan` + 改为 skip 计数 delta)
- Modify: `backend/skills/skill_md/loader.py:389-396` (`_load_from_path` 的冲突处理块, 区分三种冲突)
- Modify: `backend/adapters/out/skill/inproc.py:84-160` (`__init__` 持有 persistent loader 替代 `register_skill_md_skills`)
- Modify: `backend/adapters/out/skill/inproc.py:682-725` (`rescan_skill_mds` 使用 persistent loader)
- Test: `backend/tests/unit/test_skill_md_rescan_refresh.py` (新建)

**Interfaces:**
- Consumes:
  - `SkillMdHotLoader.hot_reload(name) -> bool`
  - `SkillMdHotLoader._loaded_paths: Dict[str, str]`
- Produces:
  - `InprocSkillAdapter._skill_md_loader: Optional[SkillMdHotLoader]` (adapter 持有)
  - 新的 skip reason: `duplicate_skillmd` / `reload_failed`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_skill_md_rescan_refresh.py`:

```python
"""rescan 真正刷新已加载的 SKILL.md (缺口 #12 修正版)。

- 同路径 SKILL.md 内容变更 → hot_reload 成功, registry 替换, skipped 不增
- 同路径 SKILL.md 内容未变 → 静默 skip, 不进 skipped 列表
- 不同路径同名 SKILL.md → "duplicate_skillmd" (高优先级目录胜)
- 与 builtin 同名 → "builtin_conflict" (builtin 永远胜)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.base import BaseSkill, SkillResult, SkillSchema
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader
from backend.skills.skill_md.skill import SkillMdDocument, SkillMdSkill


pytestmark = pytest.mark.unit


def _write_skill(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\n{body}\n",
        encoding="utf-8",
    )
    return p


class _Builtin(BaseSkill):
    """builtin 占位符 —— 与 SkillMdSkill 类型不同, 用于测试 builtin_conflict。"""

    def __init__(self, name):
        self._name = name

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name=self._name,
            description="builtin",
            triggers=[self._name],
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, params, context):
        return SkillResult(success=True, content="builtin")


def test_same_path_refresh_updates_registry_and_hash(tmp_path):
    """SKILL.md 内容变更后, rescan 触发 hot_reload, registry 里的 skill 拿到新 body。"""
    path = _write_skill(tmp_path, "refreshme", "BODY-V1")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1 and skipped == 0

    # 修改文件内容
    path.write_text(
        "---\nname: refreshme\ndescription: refreshme skill\n---\nBODY-V2\n",
        encoding="utf-8",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1, "refresh 后应计数为 1 次重新加载"
    assert skipped == 0, "同路径刷新不应记入 skipped"
    skill = registry.get("refreshme")
    assert isinstance(skill, SkillMdSkill)
    assert "BODY-V2" in skill._doc.body


def test_unchanged_same_path_is_silent_skip(tmp_path):
    """SKILL.md 内容未变 → 静默跳过, 不进 skipped 列表。"""
    _write_skill(tmp_path, "same", "STABLE")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    loader.scan_and_load()

    # 第二次扫描: 同一份文件, 同一 loader 实例
    loaded, skipped = loader.scan_and_load()
    assert skipped == 0, "未变内容不应进入 skipped 列表"
    # loaded 可能是 1 (refresh 成功) 或 0 (无变化); 两者都算对
    assert loaded in (0, 1)


def test_different_path_same_name_is_duplicate(tmp_path):
    """两个不同目录有同名 SKILL.md → 高优先级目录胜, 低优先级记 duplicate_skillmd。"""
    high = tmp_path / "high"
    low = tmp_path / "low"
    high.mkdir()
    low.mkdir()
    (high / "dupe").mkdir()
    (high / "dupe" / "SKILL.md").write_text(
        "---\nname: dupe\ndescription: high\n---\nHIGH\n",
        encoding="utf-8",
    )
    (low / "dupe").mkdir()
    (low / "dupe" / "SKILL.md").write_text(
        "---\nname: dupe\ndescription: low\n---\nLOW\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    # 高优先级目录在前
    loader = SkillMdHotLoader(registry, dirs=[high, low])
    loaded, skipped = loader.scan_and_load()

    assert loaded == 1
    assert skipped == 1
    assert any(
        s["name"] == "dupe" and s["reason"] == "duplicate_skillmd"
        for s in loader.skipped
    )
    skill = registry.get("dupe")
    assert isinstance(skill, SkillMdSkill)
    assert "HIGH" in skill._doc.body


def test_builtin_conflict_unchanged(tmp_path):
    """与 builtin 同名 → 'builtin_conflict' (行为不变)。"""
    _write_skill(tmp_path, "search", "some body")
    registry = SkillRegistry()
    registry.register(_Builtin("search"))
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    loaded, skipped = loader.scan_and_load()

    assert loaded == 0
    assert skipped == 1
    assert loader.skipped[0]["reason"] == "builtin_conflict"
    # builtin 永远胜
    assert not isinstance(registry.get("search"), SkillMdSkill)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_rescan_refresh.py -v`
Expected: FAIL — `test_same_path_refresh_updates_registry_and_hash` 因为当前 loader 把所有重名都标 `builtin_conflict`(即使注册的是 SkillMdSkill 且路径相同), 所以第二次 scan 时 `refreshme` 被 skip, `loaded=0`;body 仍是 `BODY-V1`。

- [ ] **Step 3: 修改 loader.py — 区分三种冲突 + 追踪 `_loaded_this_scan`**

Edit `backend/skills/skill_md/loader.py`:

**3a.** 在 `SkillMdHotLoader.__init__`(行 294-296)的末尾加 `_loaded_this_scan`:

```python
    def __init__(
        self,
        registry: SkillRegistry,
        dirs: Optional[List[Path]] = None,
        gating_ctx: Optional[GatingContext] = None,
        script_runner: Optional[ScriptRunner] = None,
    ) -> None:
        self._registry = registry
        self._dirs: List[Path] = list(dirs or [])
        self._file_hashes: Dict[str, str] = {}
        self._loaded_paths: Dict[str, str] = {}  # skill_name -> file_path str
        self._gating_ctx = gating_ctx  # None = 不门控 (v1 行为)
        self._script_runner = script_runner
        self.skipped: List[Dict[str, str]] = []
        self._last_skip: Optional[Dict[str, str]] = None
        # 本次 scan_and_load 调用中新加载/刷新的名字 (供 rescan API 返回增量列表)
        self._loaded_this_scan: List[str] = []
```

**3b.** 在 `scan_and_load`(行 300-368)里:起始处重置 `_loaded_this_scan`,并把两处 `_load_from_path` 的调用改成 **skip 计数 delta**。

为什么必须用 delta:改造后 `_load_from_path` 多了一条"内容未变 → 静默 `return False`"的路径,它**不**调用 `_record_skip`。如果仍写 `else: skipped += 1`,未变文件就会被错记为 skip,`test_unchanged_same_path_is_silent_skip` 的 `assert skipped == 0` 会失败。

```python
    def scan_and_load(self) -> Tuple[int, int]:
        """..."""
        loaded = 0
        skipped = 0
        self.skipped = []
        self._loaded_this_scan = []
        for d in self._dirs:
            if not d.is_dir():
                continue
            # 形态 A: 子目录形态 <dir>/<name>/SKILL.md
            for entry in sorted(d.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.is_symlink():
                    continue
                if entry.name.startswith("."):
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file() or _has_symlink_component(skill_md):
                    continue
                try:
                    before = len(self.skipped)
                    if self._load_from_path(skill_md):
                        loaded += 1
                    elif len(self.skipped) > before:
                        # 只有真正记录了 skip 才计数; 内容未变的静默跳过不计
                        skipped += 1
                except Exception as exc:  # noqa: BLE001 - 防御性兜底
                    logger.warning(
                        "SKILL.md load failed for %s: %s",
                        skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    skipped += 1
                    self.skipped.append(
                        {"name": entry.name, "reason": "load_error"}
                    )
            # 形态 B: 单文件形态 <dir>/SKILL.md (Task 5)
            root_skill_md = d / "SKILL.md"
            if root_skill_md.is_file() and not _has_symlink_component(root_skill_md):
                try:
                    before = len(self.skipped)
                    if self._load_from_path(root_skill_md):
                        loaded += 1
                    elif len(self.skipped) > before:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SKILL.md single-file load failed for %s: %s",
                        root_skill_md,
                        sanitize_for_logging(str(exc), max_len=200),
                    )
                    self._record_skip(
                        root_skill_md.name,
                        "load_error",
                    )
                    skipped += 1
            if loaded or skipped:
                logger.info("SkillMd scan: %d loaded, %d skipped", loaded, skipped)
        return loaded, skipped
```

**3c.** 替换 `_load_from_path` 的冲突处理块(行 389-396,即 `if self._registry.exists(name) and not allow_existing:` 那一段):

```python
    def _load_from_path(
        self, path: Path, *, allow_existing: bool = False
    ) -> bool:
        """从单个 SKILL.md 路径加载, 返回 True 表示成功注册, False 表示跳过。

        冲突判定三态:
          (a) 注册表里是 builtin (非 SkillMdSkill) → "builtin_conflict" (builtin 永远胜)
          (b) 注册表里是同路径的 SkillMdSkill → 原地刷新 (hash 比对),
              hash 相同 → 静默跳过 (不进 skipped 列表);
              hash 不同 → hot_reload, 记入 _loaded_this_scan
          (c) 注册表里是不同路径的 SkillMdSkill → "duplicate_skillmd" (高优先级目录胜)
        """
        if _has_symlink_component(path):
            return False
        try:
            meta, body = _parse_no_follow(path)
        except (SkillMdParseError, UnicodeDecodeError) as exc:
            logger.warning(
                "SKILL.md parse error in %s: %s",
                path,
                sanitize_for_logging(str(exc), max_len=200),
            )
            self._record_skip(
                path.stem,
                "invalid_name"
                if isinstance(exc, SkillMdParseError)
                and _has_explicit_invalid_name(path)
                else "parse_error",
            )
            return False
        name = meta["name"]
        if self._registry.exists(name) and not allow_existing:
            existing = self._registry.get(name)
            if isinstance(existing, SkillMdSkill):
                existing_path = self._loaded_paths.get(name)
                if existing_path is not None and existing_path == str(path):
                    # 同路径 → 比对哈希, 有变更才 hot_reload
                    new_hash = self._compute_hash(path)
                    old_hash = self._file_hashes.get(str(path))
                    if old_hash == new_hash:
                        # 内容未变 → 静默 skip (不进 skipped 列表, 不进 _loaded_this_scan)
                        return False
                    if self.hot_reload(name):
                        self._loaded_this_scan.append(name)
                        return True
                    self._record_skip(name, "reload_failed")
                    return False
                # 不同路径的同名 SkillMdSkill → 高优先级目录胜
                self._record_skip(name, "duplicate_skillmd")
                return False
            # builtin 冲突: builtin 永远胜
            logger.warning(
                "SkillMd name collision: '%s' already in registry (builtin wins), skipping %s",
                name,
                path,
            )
            self._record_skip(name, "builtin_conflict")
            return False
        requires_data = meta.get("requires", {})
        # ... (后续逻辑不变)
```

注意:**不要**改动行 397 之后的代码(RequiresSpec 构造 / 评估门控 / SkillMdSkill 实例化 / hash 写入)。

**3d.** 在 `_load_from_path` 成功路径(行 505-508 区域),把名字记入 `_loaded_this_scan`:

```python
        file_hash = self._compute_hash(path)
        self._registry.register(skill)
        self._loaded_paths[name] = str(path)
        self._file_hashes[str(path)] = file_hash
        self._loaded_this_scan.append(name)
        logger.info(
            "SkillMd loaded: %s (version=%s) from %s",
            name,
            doc.version,
            path,
        )
        return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_rescan_refresh.py backend/tests/unit/test_skill_md_loader_gating.py -v`
Expected: PASS — 新测试 4 个全绿;旧 loader 门控测试不受影响(`_load_from_path` 在既有"首次加载"场景下行为不变: registry 没有该名字, 走到成功注册分支)。

Also: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -k "loader" -v` — 全绿。

- [ ] **Step 5: 改 inproc.py — adapter 持有 persistent loader**

Edit `backend/adapters/out/skill/inproc.py`:

**5a.** 替换 SKILL.md 加载 try 块(原行 92-124 区域),把 `register_skill_md_skills` 调用改为显式构造并持有 loader:

```python
        try:
            from backend.adapters.out.skill_script.cli_confirmation import (
                ConfiguredScriptConfirmationAdapter,
            )
            from backend.adapters.out.skill_script.subprocess_sandbox import (
                SubprocessSandboxAdapter,
            )
            from backend.skills.skill_md.loader import (
                SkillMdHotLoader,
                _discover_shipped_dir,
                build_gating_context_for_dirs,
                discover_skill_md_dirs,
            )
            from backend.skills.skill_md.script_runner import ScriptRunner

            skill_dirs = discover_skill_md_dirs()
            self._script_runner = ScriptRunner(
                sandbox=SubprocessSandboxAdapter(),
                confirmer=ConfiguredScriptConfirmationAdapter.from_environment(),
                allowed_roots=list(skill_dirs),
            )
            from backend.skills import register_skill_md_skills  # noqa: F401  (kept for other callers)

            # Build registration dirs = user roots + shipped fallback (dedup by resolved path).
            registration_dirs = list(skill_dirs)
            seen = {p.resolve() for p in registration_dirs}
            shipped = _discover_shipped_dir()
            if shipped is not None:
                shipped_resolved = shipped.resolve()
                if shipped_resolved not in seen:
                    registration_dirs.append(shipped)
                    seen.add(shipped_resolved)

            # requires.config 门控需要 settings 快照 (Task 1)
            try:
                from backend.data.settings_repo import SettingsRepository

                self._settings_repo = SettingsRepository()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "SkillMd settings repo unavailable: %s", exc
                )

            # 持久持有 loader (缺口 #12): rescan 时复用同一 loader 实例,
            # 使 _file_hashes / _loaded_paths 跨调用保留, 才能真正触发 hot_reload。
            self._skill_md_loader = SkillMdHotLoader(
                self._registry,
                dirs=[Path(p) for p in registration_dirs],
                gating_ctx=build_gating_context_for_dirs(
                    registration_dirs, settings_repo=self._settings_repo
                ),
                script_runner=self._script_runner,
            )
            self._skill_md_loader.scan_and_load()
        except Exception as exc:  # noqa: BLE001 — adapter 构造必须容错
            import logging

            logging.getLogger(__name__).warning("SkillMd loader skipped in adapter init: %s", exc)
            self._skill_md_loader = None
```

注意: 把原 `register_skill_md_skills(...)` 调用替换为 `self._skill_md_loader = SkillMdHotLoader(...)` + `.scan_and_load()`。`register_skill_md_skills` import 注释为 `# noqa: F401 (kept for other callers)` — 它现在不在本方法里调用,但其他模块可能还 import 它。

**5b.** 替换 `rescan_skill_mds`(原行 682-725):

```python
    def rescan_skill_mds(self) -> Dict[str, Any]:
        """重扫 SAGE_SKILLS_DIR / ~/.sage/skills / ./skills, 增量加载/刷新 SKILL.md。

        Returns:
            {
                "loaded": [{"name", "source", "path": "."}],
                "skipped": [{"name", "reason"}],
                "total_loaded": int,
            }
        """
        if self._skill_md_loader is None:  # init-time loader 构造失败
            return {"loaded": [], "skipped": [], "total_loaded": 0}
        from backend.skills.skill_md.loader import (
            SkillMdHotLoader,
            _discover_shipped_dir,
            build_gating_context_for_dirs,
            discover_skill_md_dirs,
        )

        # 目录可能在 adapter 初始化后才由审批/导入流程创建;每次重扫都
        # 重新发现根目录, 避免永久使用初始化时的快照。
        skill_dirs = discover_skill_md_dirs()
        self._skill_dirs = list(skill_dirs)
        if self._script_runner is not None:
            self._script_runner._allowed_roots = list(skill_dirs)

        # 重建 registration_dirs = user + shipped (与 __init__ 同逻辑)
        registration_dirs = list(skill_dirs)
        seen = {p.resolve() for p in registration_dirs}
        shipped = _discover_shipped_dir()
        if shipped is not None:
            shipped_resolved = shipped.resolve()
            if shipped_resolved not in seen:
                registration_dirs.append(shipped)
                seen.add(shipped_resolved)

        # 如果目录拓扑变了 (比如新增 shipped fallback), 需要重建 loader;
        # 否则沿用 persistent loader, 复用哈希缓存。
        new_dirs_key = sorted(str(p) for p in registration_dirs)
        old_dirs_key = sorted(str(d) for d in self._skill_md_loader._dirs)
        if new_dirs_key != old_dirs_key:
            self._skill_md_loader = SkillMdHotLoader(
                self._registry,
                dirs=[Path(p) for p in registration_dirs],
                gating_ctx=build_gating_context_for_dirs(
                    registration_dirs, settings_repo=self._settings_repo
                ),
                script_runner=self._script_runner,
            )
        else:
            # 复用 persistent loader: _loaded_paths / _file_hashes 保留,
            # 使 check_for_updates / hot_reload 能识别到文件变化。
            self._skill_md_loader._dirs = [Path(p) for p in registration_dirs]
            self._skill_md_loader._gating_ctx = build_gating_context_for_dirs(
                registration_dirs, settings_repo=self._settings_repo
            )

        self._skill_md_loader.scan_and_load()
        self._rebuild_slash_registry()
        # 返回本次 scan 中**新加载 + 刷新**的名字 (来自 _loaded_this_scan)
        loaded_names = list(self._skill_md_loader._loaded_this_scan)
        total_loaded = len(self._skill_md_loader._loaded_paths)
        return {
            "loaded": [
                {"name": name, "source": "skillmd", "path": _SAFE_SKILL_PATH}
                for name in loaded_names
            ],
            "skipped": list(self._skill_md_loader.skipped),
            "total_loaded": total_loaded,
        }
```

注意: `register_skill_md_skills` import 行(原 707 行附近)可以删除, 改为 `SkillMdHotLoader` + `_discover_shipped_dir` + `build_gating_context_for_dirs` + `discover_skill_md_dirs`。

- [ ] **Step 6: 跑集成级 adapter 测试**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_md_rescan_refresh.py backend/tests/integration/test_skill_import.py backend/tests/integration/test_skill_md_integration.py backend/tests/integration/test_routes_skills.py -v`
Expected: PASS — 既有 adapter/rescan 测试(比如 `test_routes_skills.py` 的 rescan endpoint 测试)继续通过。

- [ ] **Step 7: 提交**

```bash
cd /home/fz/project/sage
git add backend/skills/skill_md/loader.py backend/adapters/out/skill/inproc.py backend/tests/unit/test_skill_md_rescan_refresh.py
git commit -m "fix(skills): rescan actually refreshes modified SKILL.md (gap #12)

- SkillMdHotLoader now distinguishes three conflict cases in _load_from_path:
  (a) builtin name → 'builtin_conflict' (unchanged)
  (b) same-path SkillMdSkill → hot_reload if hash changed, silent skip if unchanged
  (c) different-path same-name SkillMdSkill → 'duplicate_skillmd'
- _loaded_this_scan tracks names loaded/refreshed during a single scan
- InprocSkillAdapter holds a persistent SkillMdHotLoader (instead of fresh
  loader per rescan), so _file_hashes / _loaded_paths survive across rescans
  and check_for_updates / hot_reload actually detect file changes
- rescan_skill_mds() returns the delta (loaded_this_scan) not the full set"
```

---

### Task 4: 技能变更通知中心 — 后端 (gap #6a)

**Files:**
- Create: `backend/skills/notifications.py`
- Modify: `backend/adapters/out/skill/inproc.py` — 在 rescan/import/delete 后 publish
- Modify: `backend/api/legacy_skills_routes.py` — 新增 `GET /skills/notifications`
- Test: `backend/tests/unit/test_skill_notification_hub.py` (新建)

**Interfaces:**
- Consumes:
  - `backend.adapters.out.skill.inproc.InprocSkillAdapter.rescan_skill_mds / import_skill_mds / import_skill_directory / delete_skill_md` 的返回结果
  - Starlette `StreamingResponse(media_type="application/x-ndjson")`
- Produces:
  - `SkillNotificationHub.publish(event) -> None` / `wait_for(after, timeout) -> List[Event]`
  - `GET /api/v1/skills/notifications` — NDJSON 流, 每行 `{seq, event, data, ts}`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_skill_notification_hub.py`:

```python
"""技能变更通知中枢 (缺口 #6a)。

- publish → wait_for 返回事件
- wait_for 超时返回空列表
- bounded buffer 丢弃最旧事件
- 线程安全: 多 producer 并发 publish 不丢事件
"""

from __future__ import annotations

import threading
import time

import pytest

from backend.skills.notifications import (
    SkillNotificationEvent,
    SkillNotificationHub,
    iter_ndjson,
)


pytestmark = pytest.mark.unit


def test_publish_and_wait_returns_event():
    hub = SkillNotificationHub(max_size=16)

    hub.publish({"kind": "skill_changed", "name": "my-skill"})
    events = hub.wait_for(after=0, timeout=0.1)

    assert len(events) == 1
    assert events[0].event["kind"] == "skill_changed"
    assert events[0].event["name"] == "my-skill"
    assert events[0].seq > 0


def test_wait_for_timeout_returns_empty_when_no_new_events():
    hub = SkillNotificationHub()
    hub.publish({"kind": "old"})

    # after=最新 seq → 没有新事件 → 快速返回空
    latest = hub._seq
    events = hub.wait_for(after=latest, timeout=0.05)

    assert events == []


def test_wait_for_returns_only_events_after_given_seq():
    hub = SkillNotificationHub()
    hub.publish({"kind": "e1"})
    after_e1 = hub._seq
    hub.publish({"kind": "e2"})
    hub.publish({"kind": "e3"})

    events = hub.wait_for(after=after_e1, timeout=0.1)

    kinds = [e.event["kind"] for e in events]
    assert kinds == ["e2", "e3"]


def test_bounded_buffer_drops_oldest():
    hub = SkillNotificationHub(max_size=2)

    hub.publish({"kind": "e1"})
    hub.publish({"kind": "e2"})
    hub.publish({"kind": "e3"})

    # buffer 只保留最新 2 个 (e2, e3)
    events = hub.wait_for(after=0, timeout=0.1)
    kinds = [e.event["kind"] for e in events]
    assert kinds == ["e2", "e3"]


def test_concurrent_publish_preserves_all_events():
    hub = SkillNotificationHub(max_size=100)
    errors = []

    def producer(prefix, count):
        try:
            for i in range(count):
                hub.publish({"kind": f"{prefix}-{i}"})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=producer, args=(f"t{i}", 20)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    events = hub.wait_for(after=0, timeout=0.1)
    assert len(events) == 100


def test_iter_ndjson_yields_lines_with_newline():
    hub = SkillNotificationHub()
    hub.publish({"kind": "a"})
    hub.publish({"kind": "b"})

    lines = []
    gen = iter_ndjson(hub, after=0, poll_interval=0.01, max_iterations=2)
    for line in gen:
        lines.append(line)
        if len(lines) >= 2:
            break

    assert len(lines) == 2
    for line in lines:
        assert line.endswith("\n")
        # 是合法 JSON
        import json

        json.loads(line)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_notification_hub.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkillNotificationHub' from 'backend.skills.notifications'`(模块不存在)。

- [ ] **Step 3: 实现 SkillNotificationHub**

创建 `backend/skills/notifications.py`:

```python
"""技能变更通知中枢 (缺口 #6a)。

设计要点
--------
- 单一广播源: rescan / import / delete 成功后 publish 一次事件
- 同步 + 线程安全: threading.Condition 守护 _events + _seq
- 有界 buffer: 慢消费者最多收到 max_size 个最新事件, 旧事件被丢弃
- NDJSON 流: iter_ndjson 把事件序列化为单行 JSON (带换行符),
  供 FastAPI StreamingResponse 直接迭代
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillNotificationEvent:
    """已分派序号的事件。"""

    seq: int
    event: Dict[str, Any]
    ts: float  # monotonic, 仅用于日志/诊断


class SkillNotificationHub:
    """技能变更通知中枢。

    Args:
        max_size: buffer 最大事件数。慢消费者最多收到最新 max_size 个事件。
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._events: List[SkillNotificationEvent] = []
        self._seq: int = 0
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

    def publish(self, event: Dict[str, Any]) -> None:
        """发布一个事件。线程安全。"""
        with self._cv:
            self._seq += 1
            entry = SkillNotificationEvent(
                seq=self._seq, event=dict(event), ts=time.monotonic()
            )
            self._events.append(entry)
            # 有界 buffer: 超过 max_size 时丢弃最旧
            overflow = len(self._events) - self._max_size
            if overflow > 0:
                del self._events[:overflow]
            self._cv.notify_all()

    def wait_for(
        self, after: int, timeout: float = 5.0
    ) -> List[SkillNotificationEvent]:
        """等待 after 之后的新事件, 最多 timeout 秒。

        返回按 seq 升序排列的事件列表。timeout 后无新事件返回空列表。
        """
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                new = [e for e in self._events if e.seq > after]
                if new:
                    return new
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._cv.wait(timeout=remaining)


# ===== 模块级单例 =====
_HUB: Optional[SkillNotificationHub] = None
_HUB_LOCK = threading.Lock()


def get_notification_hub() -> SkillNotificationHub:
    """获取模块级单例 hub (lazy init, 进程内共享)。"""
    global _HUB
    if _HUB is None:
        with _HUB_LOCK:
            if _HUB is None:
                _HUB = SkillNotificationHub()
    return _HUB


def reset_notification_hub_for_testing() -> None:
    """测试用: 重置单例。"""
    global _HUB
    with _HUB_LOCK:
        _HUB = None


def iter_ndjson(
    hub: SkillNotificationHub,
    after: int = 0,
    poll_interval: float = 0.5,
    max_iterations: Optional[int] = None,
    keep_alive: float = 15.0,
) -> Generator[str, None, None]:
    """把 hub 的事件流转换为 NDJSON 行迭代器 (FastAPI StreamingResponse 消费)。

    每条 line 是单行 JSON (trailing newline), 字段: {seq, event, ts}。
    客户端断连时, 生成器被 FastAPI 销毁, 线程退出。

    Args:
        hub: 通知中枢
        after: 初始游标 (0 = 取 buffer 里全部)
        poll_interval: 等待轮询间隔
        max_iterations: 测试用, 限制最大迭代次数
        keep_alive: 每 keep_alive 秒发送一次 {} 心跳 (防止中间件超时)
    """
    cursor = after
    iterations = 0
    last_emit = time.monotonic()
    while max_iterations is None or iterations < max_iterations:
        events = hub.wait_for(after=cursor, timeout=min(poll_interval, keep_alive))
        for e in events:
            payload = {"seq": e.seq, "event": e.event, "ts": e.ts}
            yield json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            cursor = max(cursor, e.seq)
            last_emit = time.monotonic()
        if not events:
            # 心跳 (避免反向代理 idle timeout 切断连接)
            if time.monotonic() - last_emit >= keep_alive:
                yield "{}\n"
                last_emit = time.monotonic()
        iterations += 1
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_notification_hub.py -v`
Expected: PASS — 全部 5 个 hub 测试通过。

- [ ] **Step 5: 在 inproc.py 中 publish 通知**

Edit `backend/adapters/out/skill/inproc.py`:

**5a.** 在文件顶部 import 段附近, 新增 module-level import (放在 `from backend.skills.registry import ...` 之后):

```python
from backend.skills.notifications import get_notification_hub
```

**5b.** 在 `rescan_skill_mds` 的 `return` 之前(在 `self._rebuild_slash_registry()` 之后), 插入:

```python
        hub = get_notification_hub()
        hub.publish(
            {
                "kind": "skills_rescanned",
                "loaded_count": len(loaded_names),
                "skipped_count": len(self._skill_md_loader.skipped),
                "total_loaded": total_loaded,
            }
        )
```

(注意: `loaded_names` / `total_loaded` 是前面 step 5b 已经定义好的本地变量, 在 `return` 之前使用。)

**5c.** 在 `import_skill_mds` 的 `return safe_result` 之前, 插入:

```python
        hub = get_notification_hub()
        hub.publish(
            {
                "kind": "skills_imported",
                "imported_count": len(safe_result.get("imported", [])),
                "skipped_count": len(safe_result.get("skipped", [])),
            }
        )
```

**5d.** 在 `import_skill_directory` 的 `return safe_result` 之前, 插入同样的 publish 模式 (kind=`skills_directory_imported`)。

**5e.** 在 `delete_skill_md` 的 `return safe_result` 之前, 插入:

```python
        hub = get_notification_hub()
        hub.publish(
            {
                "kind": "skill_deleted",
                "name": name,
            }
        )
```

- [ ] **Step 6: 在 legacy_skills_routes.py 新增 NDJSON 端点**

Edit `backend/api/legacy_skills_routes.py`:

**6a.** 在文件顶部 import 段(行 20 `from fastapi import ...` 附近)追加:

```python
from fastapi.responses import StreamingResponse
```

**6b.** 在 `rescan_skills` 函数之后(行 379 附近), 新增端点:

```python
@router.get("/skills/notifications")
def skill_notifications(after: int = 0):
    """技能变更通知流 (缺口 #6a)。

    - 200 + NDJSON 流, Content-Type: application/x-ndjson
    - 每行: ``{"seq": int, "event": {...}, "ts": float}``
    - 客户端断连时, 生成器被 FastAPI 销毁, 线程退出

    客户端典型用法:
      EventSource 或 fetch(stream: true) → 收到事件后重新拉 skillsApi.list()
    """
    from backend.skills.notifications import get_notification_hub, iter_ndjson

    hub = get_notification_hub()
    return StreamingResponse(
        iter_ndjson(hub, after=after),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 7: 跑集成测试验证端点**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_notification_hub.py backend/tests/integration/test_routes_skills.py -v`
Expected: PASS — 既有 routes 测试不受影响(新 GET 端点是 additive)。

- [ ] **Step 8: 提交**

```bash
cd /home/fz/project/sage
git add backend/skills/notifications.py backend/adapters/out/skill/inproc.py backend/api/legacy_skills_routes.py backend/tests/unit/test_skill_notification_hub.py
git commit -m "feat(skills): notification hub + NDJSON endpoint for skill changes (gap #6a)

- SkillNotificationHub: threading.Condition-guarded, bounded buffer (256 default),
  publish() / wait_for(after, timeout) / iter_ndjson()
- Module-level singleton via get_notification_hub() (lazy init, process-shared)
- InprocSkillAdapter publishes on rescan/import/import_directory/delete
- GET /api/v1/skills/notifications returns application/x-ndjson stream
- Heartbeat every 15s to survive reverse-proxy idle timeouts"
```

---

### Task 5: Electron 通知中继 (gap #6b)

**Files:**
- Modify: `electron/relay.ts` — 新增 `relaySkillNotifications()`
- Modify: `electron/main.ts:1482-1488` — 新增 `skills:notify` 分支
- Test: `electron/__tests__/relay.skillNotifications.test.ts` (新建)

**Interfaces:**
- Consumes:
  - `relay.ts` 既有 `parseNdjsonStream` / `WebContentsLike` / `canSend`
  - `node-fetch@2` default import
  - `BACKEND_URL` + `backendAuthToken`(main.ts 内已有)
- Produces:
  - `relaySkillNotifications(webContents, eventName, backendUrl, signal, authToken?) -> Promise<void>`
  - main.ts 新增 `skills:notify` 分支(在 `session-notify-click` 之前)

- [ ] **Step 1: 写失败测试**

创建 `electron/__tests__/relay.skillNotifications.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Readable } from 'node:stream';

vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  return {
    ...actual,
    default: vi.fn(),
  };
});

import nodeFetch from 'node-fetch';
import { relaySkillNotifications } from '../relay';

const mockedFetch = nodeFetch as unknown as ReturnType<typeof vi.fn>;

class MockWebContents {
  sent: Array<{ channel: string; payload: unknown }> = [];
  isDestroyedCalled = 0;
  destroyed = false;
  send(channel: string, payload: unknown) {
    this.sent.push({ channel, payload });
  }
  isDestroyed() {
    this.isDestroyedCalled += 1;
    return this.destroyed;
  }
}

function makeNdjsonReadable(lines: string[]): NodeJS.ReadableStream {
  const body = lines.join('\n') + '\n';
  return Readable.from([body]) as unknown as NodeJS.ReadableStream;
}

function makeNdjsonFetchResponse(lines: string[], init: { status?: number; ok?: boolean } = {}): unknown {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body: makeNdjsonReadable(lines),
  };
}

describe('relaySkillNotifications', () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it('fetches /api/v1/skills/notifications and forwards each NDJSON line as sage:event', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([
        JSON.stringify({ seq: 1, event: { kind: 'skills_rescanned' }, ts: 100 }),
        JSON.stringify({ seq: 2, event: { kind: 'skill_deleted', name: 'x' }, ts: 101 }),
      ]),
    );
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const calledUrl = mockedFetch.mock.calls[0][0];
    expect(calledUrl).toBe('http://127.0.0.1:8765/api/v1/skills/notifications');
    expect(wc.sent.length).toBe(2);
    expect(wc.sent[0].channel).toBe('sage:event:skills:notify');
    expect(wc.sent[0].payload).toEqual({ seq: 1, event: { kind: 'skills_rescanned' }, ts: 100 });
  });

  it('includes Authorization header when authToken provided', async () => {
    mockedFetch.mockResolvedValueOnce(makeNdjsonFetchResponse([]));
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(
      wc,
      'skills:notify',
      'http://127.0.0.1:8765',
      abort.signal,
      'secret-token',
    );

    const headers = mockedFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe('Bearer secret-token');
  });

  it('returns silently when fetch returns non-2xx (e.g. 401)', async () => {
    mockedFetch.mockResolvedValueOnce({ ok: false, status: 401, body: null });
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });

  it('returns silently on network error', async () => {
    const err = new Error('ECONNREFUSED');
    err.name = 'Error';
    mockedFetch.mockRejectedValueOnce(err);
    const wc = new MockWebContents();
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });

  it('does not send after webContents is destroyed', async () => {
    mockedFetch.mockResolvedValueOnce(
      makeNdjsonFetchResponse([
        JSON.stringify({ seq: 1, event: { kind: 'e1' }, ts: 1 }),
        JSON.stringify({ seq: 2, event: { kind: 'e2' }, ts: 2 }),
      ]),
    );
    const wc = new MockWebContents();
    wc.destroyed = true; // destroyed before processing
    const abort = new AbortController();

    await relaySkillNotifications(wc, 'skills:notify', 'http://127.0.0.1:8765', abort.signal);

    expect(wc.sent.length).toBe(0);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run electron/__tests__/relay.skillNotifications.test.ts`
Expected: FAIL — `ImportError: cannot import name 'relaySkillNotifications' from '../relay'` 的等价 TS 报错。

- [ ] **Step 3: 在 relay.ts 实现 relaySkillNotifications**

Edit `electron/relay.ts`:

在文件末尾( `relayOrchEventsStream` 之后)追加:

```typescript
/**
 * Subscribe to skill change notifications and forward to renderer.
 *
 * Flow:
 *   1. renderer calls listen('skills:notify', handler)
 *   2. main process opens GET /api/v1/skills/notifications (NDJSON stream)
 *   3. Each NDJSON line → webContents.send('sage:event:skills:notify', event)
 *   4. renderer re-fetches skillsApi.list() on receipt
 *
 * Gap #6a/6b: single broadcast channel for rescan/import/delete notifications.
 */
export async function relaySkillNotifications(
  webContents: WebContentsLike,
  eventName: string,
  backendUrl: string,
  signal: AbortSignal,
  authToken?: string,
): Promise<void> {
  let res: import('node-fetch').Response;
  try {
    res = await fetch(`${backendUrl}/api/v1/skills/notifications`, {
      method: 'GET',
      headers: {
        Accept: 'application/x-ndjson',
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    // 网络错误静默吞掉, 不要把 main 进程炸了
    return;
  }

  if (!res.ok) {
    // 非 2xx (如 401/500) 静默返回, renderer 侧会收到流结束信号
    return;
  }

  await parseNdjsonStream(
    res.body,
    (event) => {
      // 心跳空行 → 跳过 (iter_ndjson 偶发 yield "{}\n")
      if (typeof event === 'object' && event !== null && Object.keys(event as object).length === 0) {
        return;
      }
      if (canSend(webContents)) webContents.send(`sage:event:${eventName}`, event);
    },
    signal,
  );
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run electron/__tests__/relay.skillNotifications.test.ts electron/__tests__/relay.test.ts`
Expected: PASS — 新测试 5 个通过 + 既有 relay 测试不受影响。

- [ ] **Step 5: 在 main.ts 新增 `skills:notify` 分支**

Edit `electron/main.ts`:

在 `session-notify-click` 分支(行 1482)之前, 插入新分支:

```typescript
      // 技能变更通知 (gap #6b): renderer 订阅后由 backend NDJSON 推送,
      // 前端收到事件后重新拉 skillsApi.list() 刷新 slash 菜单。
      if (event === 'skills:notify') {
        const abort = new AbortController();
        eventSubscriptions.set(event, abort);
        relaySkillNotifications(
          senderWebContents,
          event,
          BACKEND_URL,
          abort.signal,
          backendAuthToken ?? undefined,
        ).catch((e) => {
          if (e instanceof Error && e.name !== 'AbortError') {
            logger.error('ipc: skill notify relay error', { err: e.message });
          }
        });
        return { ok: true, event };
      }
```

同时在 `main.ts` 顶部 import `relaySkillNotifications`:

```typescript
import {
  relayChatStream,
  relayOrchEventsStream,
  relaySkillNotifications,
  // ... 其他既有 import
} from './relay';
```

(具体位置请参照现有 `relayChatStream` / `relayOrchEventsStream` 的 import 语句, 在同一行加 `relaySkillNotifications`。)

- [ ] **Step 6: 跑 Electron 层测试**

Run: `cd /home/fz/project/sage && npx vitest run electron/__tests__/relay.skillNotifications.test.ts electron/__tests__/eventRouting.test.ts`
Expected: PASS — 新测试通过;既有 eventRouting 测试不受影响(新分支是 additive,不改变 `sage:listen` 的其他行为)。

- [ ] **Step 7: 提交**

```bash
cd /home/fz/project/sage
git add electron/relay.ts electron/main.ts electron/__tests__/relay.skillNotifications.test.ts
git commit -m "feat(electron): relay skill notifications to renderer (gap #6b)

- relay.ts: add relaySkillNotifications() (mirrors relayOrchEventsStream pattern)
- main.ts: add 'skills:notify' branch in sage:listen handler before the
  unknown-event fallback; uses existing BACKEND_URL + backendAuthToken
- Network errors / non-2xx responses silently no-op (renderer receives
  stream-end signal)"
```

---

### Task 6: 前端订阅刷新 slash 列表 (gap #6c)

**Files:**
- Modify: `src/widgets/chat/ChatInput.tsx:1-20` (imports)
- Modify: `src/widgets/chat/ChatInput.tsx:223-246` (mount-only loader → subscribe + reload)
- Test: `src/widgets/chat/__tests__/ChatInput.skillNotify.test.tsx` (新建)

**Interfaces:**
- Consumes:
  - `src/shared/api/desktopEvent.ts` `listen<T>(event, handler, options?) -> Promise<UnlistenFn>`
  - `src/shared/api/skillsApi.list()`
- Produces: 订阅 `skills:notify` 事件, 触发 `setDynamicSlashCommands` 刷新

- [ ] **Step 1: 写失败测试**

创建 `src/widgets/chat/__tests__/ChatInput.skillNotify.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

// Mock 与 ChatInput.btw.test.tsx 对齐
vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

vi.mock('../../../features/chat/useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: vi.fn(),
    close: vi.fn(),
    isOpen: false,
    question: '',
    answer: '',
    isLoading: false,
  }),
}));

vi.mock('../../../features/chat/AtFileMenu', () => ({
  AtFileMenu: () => null,
}));

// ===== 核心 mock: skillsApi.list 用 spyOn (不用 barrel mock) =====
// 理由: barrel 整体 mock 会连带打断 ChatInput 从同目录导入的其他 api
// (worktreeApi / fileSearchClient / types), 且手写的 fixture 容易漏掉 Skill
// 的必填字段。spyOn 只替换 list 一个方法, 其余保持真实对象, 类型零妥协。
import { skillsApi } from '../../../shared/api/skillsApi';
import type { Skill } from '../../../shared/api/types';

const makeSkill = (over: Partial<Skill> = {}): Skill => ({
  name: 'skill-a',
  description: 'A',
  triggers: ['a'],
  parameters: {},
  examples: [],
  enabled: true,
  usage_count: 0,
  dispatch: {
    disable_model_invocation: false,
    user_invocable: true,
    user_invocable_name: null,
    command_dispatch: 'prompt',
  },
  ...over,
});

let listSkillsMock: MockInstance<typeof skillsApi.list>;

type ListenHandler = (e: { payload: unknown }) => void;
let skillsNotifyHandler: ListenHandler | null = null;
const unlistenMock = vi.fn();
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: vi.fn(async (event: string, handler: ListenHandler) => {
    if (event === 'skills:notify') {
      skillsNotifyHandler = handler;
    }
    return unlistenMock;
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — skills:notify subscription', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillsNotifyHandler = null;
    listSkillsMock = vi
      .spyOn(skillsApi, 'list')
      .mockResolvedValue([makeSkill()]);
  });

  afterEach(() => {
    listSkillsMock.mockRestore();
  });

  it('subscribes to skills:notify on mount', async () => {
    const { listen } = await import('../../../shared/api/desktopEvent');

    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    await waitFor(() => expect(listen).toHaveBeenCalledWith('skills:notify', expect.any(Function), undefined));
  });

  it('re-fetches skills list when skills:notify event arrives', async () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    await waitFor(() => expect(skillsNotifyHandler).not.toBeNull());

    // 初始 mount 已拉 1 次
    const initialCalls = listSkillsMock.mock.calls.length;
    expect(initialCalls).toBeGreaterThanOrEqual(1);

    // 触发 notify 事件 → 应再拉一次
    skillsNotifyHandler!({ payload: { kind: 'skills_rescanned', loaded_count: 1 } });

    await waitFor(() => expect(listSkillsMock.mock.calls.length).toBeGreaterThan(initialCalls));
  });

  it('does not crash if handler fires before skills list resolves', async () => {
    // 让首次 list 永远 pending
    let pendingResolver: (v: Skill[]) => void;
    listSkillsMock.mockReturnValueOnce(
      new Promise<Skill[]>((resolve) => {
        pendingResolver = resolve;
      }),
    );

    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    // 等 handler 注册完成
    await waitFor(() => expect(skillsNotifyHandler).not.toBeNull());

    // 触发事件 — 不应抛出
    expect(() =>
      skillsNotifyHandler!({ payload: { kind: 'skill_deleted', name: 'x' } }),
    ).not.toThrow();

    // resolve pending, 避免未处理 promise 泄漏
    pendingResolver!([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.skillNotify.test.tsx`
Expected: FAIL — `Expected "listen" to have been called with "skills:notify"`(当前 ChatInput 没有订阅)。

- [ ] **Step 3: 在 ChatInput.tsx 实现订阅**

Edit `src/widgets/chat/ChatInput.tsx`:

**3a.** 在文件顶部 import 段(行 15 的 `import { knowledgeApi, promptApi, skillsApi } from '../../shared/api';` 之后)追加:

```typescript
import { listen as desktopListen } from '../../shared/api/desktopEvent';
```

**3b.** 替换 skills 加载 useEffect(行 226-246 区域)为"加载 + 订阅"版本:

```tsx
  // 首次挂载拉 skills 列表 + 订阅 skills:notify 事件触发刷新。
  // 旧实现 (gap #6c): mount-only, 新装/删除/重扫 SKILL.md 后 slash 菜单不更新,
  // 需重启 app。新实现: 订阅后端技能变更中枢推送, 收到事件后重新拉 list()。
  const reloadSkills = useCallback(() => {
    skillsApi
      .list()
      .then((skills) => {
        const dynamic = skills
          .filter((s) => s.dispatch?.user_invocable === true)
          .map((s) => ({
            commandName: s.dispatch?.user_invocable_name ?? `/${s.name}`,
            description: s.description,
          }));
        setDynamicSlashCommands(dynamic);
      })
      .catch(() => {
        setDynamicSlashCommands([]);
      });
  }, []);

  useEffect(() => {
    reloadSkills();
    let unlisten: (() => void) | undefined;
    let disposed = false;
    desktopListen('skills:notify', () => {
      if (disposed) return;
      reloadSkills();
    })
      .then((fn) => {
        if (disposed) fn?.();
        else unlisten = fn;
      })
      .catch(() => {
        // 浏览器 / 纯 Web 环境没有 preload 注入的 electronAPI,
        // desktopEvent.listen 会 reject —— 忽略即可, 不影响斜杠菜单首次加载。
      });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [reloadSkills]);
```

注意: `setDynamicSlashCommands` 来自哪里? 原代码已有 `setDynamicSlashCommands` 调用(行 237),所以 state setter 已经在组件顶部某处定义。本 step 不引入新 state。

另外, `skillsApi` 已经在原文件 import 了(行 18:`import { knowledgeApi, promptApi, skillsApi } from '../../shared/api';`)。`reloadSkills` 是新增的 useCallback。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.skillNotify.test.tsx src/widgets/chat/__tests__/ChatInput.btw.test.tsx`
Expected: PASS — 新测试 3 个通过 + 既有 btw 测试不受影响。

- [ ] **Step 5: 跑所有 ChatInput 相关测试**

Run: `cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/`
Expected: PASS — 整个 `ChatInput` 测试套件绿。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage
git add src/widgets/chat/ChatInput.tsx src/widgets/chat/__tests__/ChatInput.skillNotify.test.tsx
git commit -m "feat(chat): refresh slash menu on skill change notifications (gap #6c)

- ChatInput subscribes to 'skills:notify' on mount via desktopEvent.listen
- On notification, re-fetches skillsApi.list() and updates dynamic slash
  commands without requiring app restart
- Extracts reloadSkills() as useCallback to share between mount-load and
  notification-refresh paths
- Cleanup: unsubscribe + dispose flag on unmount"
```

---

### Task 7: 帮助文档校正 (gap #8)

**Files:**
- Modify: `src/content/help/skills.md` (重写)
- Create: `backend/tests/unit/test_skill_help_doc.py`

**Interfaces:**
- Consumes:
  - `backend/skills/__init__.py` `register_all_skills` (注册 builtin 名字)
  - `backend/skills/skill_md/frontmatter.py` (SKILL.md 字段真相)
  - `backend/chat/entity_refs.py` `@skill:<name>` 实体引用语法
- Produces: 文档与代码真相对齐

- [ ] **Step 1: 写 lint 测试 — 验证文档中列出的 builtin 名字真实存在**

创建 `backend/tests/unit/test_skill_help_doc.py`:

```python
"""帮助文档 skills.md 与代码真相对齐 (缺口 #8)。

- 文档中列出的 builtin 技能名必须实际注册
- 文档中提到的 SKILL.md 字段名必须在 frontmatter 解析白名单里
- 文档不提到已经废弃的概念 (如技能市场)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills import register_all_skills


pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "src" / "content" / "help" / "skills.md"


def _get_builtin_names() -> set:
    reg = SkillRegistry()
    register_all_skills(reg)
    return {schema.name for schema in reg.list()}


def test_doc_lists_only_real_builtin_names():
    """文档中任何 ``| name |`` 形态的 builtin 表格行, 必须是真实注册的 builtin。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    # 找 builtin 表格 (以 | 开头, 第二列是 description)
    listed_names: set = set()
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and "内置技能" in text[: text.find(stripped) + 100]:
            # 粗略判定: 当前行位于"内置技能"附近的表格
            parts = [p.strip() for p in stripped.split("|") if p.strip()]
            if len(parts) >= 2 and parts[0] not in ("名称", "---", "Name"):
                listed_names.add(parts[0])
    # 仅当文档确实列了 builtin 名字时才检查
    if not listed_names:
        pytest.skip("文档未列出 builtin 名字表格")
    real = _get_builtin_names()
    bogus = listed_names - real
    assert not bogus, f"文档列出的 builtin 名字不存在: {bogus} (实际: {real})"


def test_doc_mentions_at_skill_syntax():
    """文档必须提到 @skill:<name> 语法 (而非错误的 @技能名)。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "@skill:" in text, "文档未提到 @skill:<name> 实体引用语法"


def test_doc_does_not_mention_skill_market():
    """文档不应提到不存在的'技能市场'概念 (避免误导用户)。"""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "技能市场" not in text, "文档提到了不存在的'技能市场'"


def test_doc_exists_and_nonempty():
    assert DOC_PATH.exists(), f"文档缺失: {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert len(text) > 500, "文档过短 (< 500 字符)"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_help_doc.py -v`
Expected: FAIL — 旧文档包含错误的 builtin 名字 (`code-review`/`commit`/`office` 等都不存在), 以及"技能市场"等概念。

- [ ] **Step 3: 重写 src/content/help/skills.md**

用下面的内容完全替换 `src/content/help/skills.md`:

```markdown
# Sage 技能 (Skills) 使用指南

本指南说明如何使用、编写和调试 Sage 的技能系统。

---

## 一、内置技能

Sage 自带 4 个 Python 内置技能，开箱即用：

| 名称       | 用途                                   |
|------------|----------------------------------------|
| `search`   | 网络搜索与信息提取                     |
| `writer`   | 长文本写作与文档生成                   |
| `coder`    | 代码生成、调试、重构                   |
| `travel`   | 旅行规划与行程推荐                     |

这些技能会被模型自动识别并在合适时机调用。

> 实际可用列表以 `backend/skills/__init__.py::register_all_skills` 注册结果为准，
> 启动时会随版本演进。文档中的名字必须能在 `backend/tests/unit/test_skill_help_doc.py`
> 校验通过。

---

## 二、SKILL.md 自定义技能

### 2.1 放置位置（按优先级）

Sage 按以下顺序扫描 SKILL.md 文件：

1. **环境变量 `$SAGE_SKILLS_DIR`**（最高优先级）
2. **Settings 中的 `skills_dir` 字段**（用户通过配置指定）
3. **当前工作目录下的 `./skills/`**
4. **`~/.sage/skills/`**（用户全局目录）
5. **打包的 shipped 目录**（只读模板，仅当以上都无同名技能时生效）

每个技能是一个目录，结构：

```
<name>/
├── SKILL.md          # 必须：元数据 + 提示词正文
└── scripts/          # 可选：脚本文件（受 ScriptRunner 安全约束）
```

也支持单文件形态 `<dir>/SKILL.md`（深度 1）。

### 2.2 SKILL.md 前置字段（frontmatter）

```yaml
---
name: my-skill                       # 必须：技能名（小写 + 短横线，≤64 字符）
description: "一句话说明"              # 必须：用途简介
version: "1.0.0"                     # 可选：语义化版本
triggers:                            # 可选：触发关键词（模型辅助识别）
  - "关键字 A"
  - "关键字 B"
when-to-use: "详细说明何时使用"        # 可选：自动激活依据 (A16)
requires:                            # 可选：加载条件
  bins: [git, docker]                #   必须存在的二进制
  env: [OPENAI_API_KEY]              #   必须存在的环境变量
  config: [permission_mode]          #   必须在 settings 中存在且有值的键
os: [macos, linux]                   # 可选：平台过滤
always: false                        # 可选：跳过 requires 检查（平台仍生效）
user-invocable: true                 # 可选：允许用户用 /name 触发
user-invocable-name: /custom         # 可选：自定义 slash 命令名
disable-model-invocation: false      # 可选：禁止模型自动调用（仅用户手动）
command-dispatch: auto               # 可选：auto / prompt / script
license: MIT                         # 可选：许可证
compatibility: "Sage ≥ 0.2"          # 可选：兼容性声明
allowed-tools:                       # 可选：白名单工具
  - bash
  - read
---
这里是技能正文，作为 system prompt 注入到模型调用。
```

### 2.3 字段语义

- `when-to-use`（或 `when_to_use`）：自动激活依据。模型在对话中匹配到该描述时主动调用，
  **不要与 `triggers` 混淆** —— `triggers` 只是关键词提示，`when-to-use` 是完整语义匹配。
- `requires.config`：依赖 settings 表中的键。`permission_mode` / `auto_memory` 等都是
  合法的键；不存在的键会报 `unknown config key`，技能被跳过。
- `always: true`：跳过 `requires.bins/env/config` 检查，但 `os` 仍然生效。
- `user-invocable: true`：让用户能在输入框用 `/name` 触发，否则仅模型可调用。
- `command-dispatch`：`auto`（自动判断 prompt/script）/ `prompt`（强制 prompt 注入）/
  `script`（强制脚本执行）。

---

## 三、触发方式

### 3.1 模型自动调用

模型根据 `description` / `when-to-use` / `triggers` 判断是否调用。无需用户干预。

### 3.2 实体引用 `@skill:<name>`

在输入框使用 `@skill:<name>` 显式提示模型使用该技能。例如：

```
请用 @skill:writer 帮我写一份技术报告
```

> 注意：不是 `@writer` 也不是 `@技能名`，必须用 `@skill:<name>` 格式。
> 参见 `backend/chat/entity_refs.py::_ENTITY_RE`。

### 3.3 Slash 命令 `/name`

如果 SKILL.md 设置了 `user-invocable: true`，可以用 `/name` 直接触发：

```
/writer 写一份 Q1 总结
```

> Slash 命令只列出 `user-invocable: true` 的技能；其他技能仅模型可调用。

---

## 四、技能调试

- 技能加载失败会记录在启动日志中，常见原因：
  - `parse_error`：YAML 格式错误
  - `invalid_name`：`name` 字段不匹配 `^[a-z0-9-]{1,64}$`
  - `missing bin: <name>`：依赖的二进制未安装
  - `missing env: <name>`：依赖的环境变量未设置
  - `missing config: <key>`：settings 中该键未设置或为空
  - `unknown config key: <key> (not in settings whitelist)`：settings 中不存在该键
  - `platform mismatch`：当前 OS 不在 `os` 列表内
  - `builtin_conflict`：与内置技能同名（内置永远优先）
  - `duplicate_skillmd`：多个目录有同名 SKILL.md（高优先级目录优先）
  - `reload_failed`：热重载时解析或门控失败
- 在聊天输入框输入 `/` 可查看当前可用的 slash 命令列表。
- 技能变更后（新建 / 编辑 / 删除 SKILL.md），前端会收到通知并自动刷新 slash 列表，
  无需重启应用（见 `/api/v1/skills/notifications` NDJSON 端点）。

---

## 五、技能管理

### 5.1 导入

- 通过设置面板导入 `.sk` 技能包或包含 SKILL.md 的目录。
- 也可直接把 SKILL.md 放到 `~/.sage/skills/<name>/SKILL.md`。

### 5.2 编辑

- 直接编辑磁盘上的 SKILL.md 文件。文件保存后，可通过 `POST /api/v1/skills/rescan`
  触发重扫（或直接等通知机制识别文件变化）。
- 编辑后 slash 菜单会自动更新。

### 5.3 删除

- 通过设置面板或 `DELETE /api/v1/skills/{name}` 物理删除。
- 内置技能不可删除。

### 5.4 归档

- 归档是软删除（`POST /api/v1/skills/{name}/archive`），文件保留但不再参与自动激活
  和 slash 候选。可恢复。

---

## 六、常见问题

**Q：我写的 SKILL.md 没被加载？**
A：检查启动日志中的 skip 原因（见第四节）。最常见是 `name` 格式错误、`requires` 条件
不满足、或放置位置不在扫描路径。

**Q：模型没调用我的技能？**
A：`description` 和 `when-to-use` 写得不够明确。把它们当成给同事的说明 —— 如果同事
看不懂什么时候该用，模型也看不懂。

**Q：slash 菜单不显示新装的技能？**
A：确认 SKILL.md 中有 `user-invocable: true`。技能变更后通知中枢会自动推送刷新。

**Q：为什么我的技能被标记为 `missing config: permission_mode`？**
A：`permission_mode` 必须在 settings 表中有值。通过设置面板配置该项，或者把 `requires.config`
从 SKILL.md 中移除。

---

## 七、与外部系统的关系

- **Prompt 模板**：技能是"长期提示词"的载体；模板是"一次性提示词"。技能适合反复使用
  的工作流（如 `writer` / `coder`），模板适合一次性任务（如"生成会议纪要"）。
- **Memory**：技能可调用 `memory` 相关工具读写记忆，形成"有状态的技能"。
- **Entity refs**：`@skill:<name>` 是显式触发；模型自动调用是隐式触发。两者最终都
  走 `InprocSkillAdapter.execute`。
```

- [ ] **Step 4: 跑 lint 测试确认通过**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_help_doc.py -v`
Expected: PASS — 新文档包含真实 builtin 名字 (`search`/`writer`/`coder`/`travel`), 提到 `@skill:` 语法, 不含"技能市场"。

- [ ] **Step 5: 跑全量 unit 测试确认无回归**

Run: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/ -x --timeout=60`
Expected: PASS(允许 pre-existing 6 个环境性失败, 见 memory `sage-backend-preexisting-test-failures.md`)。

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage
git add src/content/help/skills.md backend/tests/unit/test_skill_help_doc.py
git commit -m "docs(skills): rewrite skills.md help to match code truth (gap #8)

- Correct builtin list: search/writer/coder/travel (was listing nonexistent
  code-review/commit/office)
- Correct invocation syntax: @skill:<name> (was @技能名)
- Document all SKILL.md frontmatter fields (was missing when-to-use/requires/
  os/license/compatibility/allowed-tools/user-invocable-name/command-dispatch)
- Remove fabricated '5-10% token' savings claim
- Remove reference to nonexistent skill marketplace
- Add pytest guard test_skill_help_doc.py that cross-checks documented builtin
  names against register_all_skills()"
```

---

## Self-Review

### 1. Spec coverage (M0 缺口覆盖)

| 缺口 | 覆盖 Task | 状态 |
|---|---|---|
| #6 技能变更通知链 | Task 4 (hub) + Task 5 (relay) + Task 6 (subscribe) | ✓ |
| #8 帮助文档 | Task 7 | ✓ |
| #9 content 归一化 | Task 2 | ✓ |
| #11 requires.config | Task 1 | ✓ |
| #12 rescan 刷新 | Task 3 | ✓ |

### 2. Placeholder scan

通读 plan, 无 TBD / TODO / "similar to Task N" / "add appropriate error handling" 占位符。所有代码步骤都有实际代码块。所有测试步骤都有实际 assert。

### 3. Type consistency

- `normalize_skill_content` — Task 2 定义 / Task 2 Step 3 调用 / Task 2 Step 1 import ✓
- `SkillNotificationHub.publish / wait_for` — Task 4 Step 3 定义 / Task 4 Step 1 调用 / Task 4 Step 5 adapter 调用 ✓
- `iter_ndjson` — Task 4 Step 3 定义 / Task 4 Step 6 routes 调用 ✓
- `relaySkillNotifications` — Task 5 Step 3 定义 / Task 5 Step 5 main.ts 调用 / Task 5 Step 1 测试 ✓
- `GatingContext.known_config` — Task 1 Step 3 定义 / Task 1 Step 1 测试 ✓
- `build_gating_context_for_dirs(..., settings_repo=...)` — Task 1 Step 5 改签名 / Task 1 Step 6 调用 ✓
- `SkillMdHotLoader._loaded_this_scan` — Task 3 Step 3 定义 / Task 3 Step 5 inproc 调用 ✓
- `desktopListen` — Task 6 Step 3 调用 / Task 6 Step 1 测试 mock ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-10-27-skill-intelligent-consolidation-m0.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
