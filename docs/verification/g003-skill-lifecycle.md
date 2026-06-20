# g003: 技能生命周期 (Skill Lifecycle) 验证映射

> Sage 技能系统 — Python `BaseSkill` 类 + SKILL.md 文件两种形态，
> 由 `SkillRegistry` 统一管理，`SkillMdHotLoader` 提供热重载与门控加载。

---

**状态**: 🔴 未验证  
**维护者**: @backend-team  
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- 职责 1：**技能注册与匹配** — `SkillRegistry` 管理技能生命周期（register/unregister/get/match/match_all/execute），支持触发词匹配
- 职责 2：**Python 技能管理** — 内置 `BaseSkill` 子类（`CoderSkill`, `SearchSkill`, `WriterSkill`, `TravelSkill`）的注册和执行
- 职责 3：**SKILL.md 技能发现与加载** — `SkillMdHotLoader` 从 `$SAGE_SKILLS_DIR` → `./skills` → `~/.sage/skills` 三级目录发现 `<name>/SKILL.md` 模式
- 职责 4：**技能热重载** — 基于 MD5 哈希的 SKILL.md 内容变化检测，支持 `hot_reload()` 和 `hot_reload_all()`
- 职责 5：**门控条件评估** — `GatingContext` + `evaluate_gating()` 实现 requires/os/always 条件加载
- 职责 6：**安全验证** — `validation.py` 提供路径遍历防御和不可信内容脱敏

### 不负责

- 非职责 1：技能脚本的沙箱执行（由 `backend/adapters/out/skill_script/` 负责）
- 非职责 2：技能触发的 LLM 调用（由 g004-agent-orchestration 负责）
- 非职责 3：技能的版本发布和分发（Sage 不内置技能市场）

### 依赖

- 依赖 `backend.skills.skill_md.frontmatter`：YAML frontmatter 解析
- 依赖 `backend.skills.skill_md.gating`：门控条件评估
- 依赖 `backend.skills.skill_md.validation`：路径安全验证

---

## 2. 接口契约

### 2.1 输入断言

| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `skill.name` | `str` | 非空，slug 格式 | `assert skill.name and skill.name == skill.name.lower()` |
| `skill.triggers` | `list[str]` | 可为空列表，元素非空 | `assert all(isinstance(t, str) and t for t in triggers)` |
| `text` (match) | `str` | 非空 | `assert text and isinstance(text, str)` |
| `params` (execute) | `dict` | 可为空字典 | `assert isinstance(params, dict)` |
| `context` (execute) | `dict` | 可为空字典 | `assert isinstance(context, dict)` |
| SKILL.md `name` | `str` | 非空，slug 格式 | `assert name and name == name.lower()` |
| SKILL.md `dirs` | `list[Path]` | 路径必须存在且为目录 | `assert all(d.is_dir() for d in dirs)` |

### 2.2 输出断言

| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `SkillResult.success` | `bool` | True/False | `assert isinstance(result.success, bool)` |
| `SkillResult.content` | `Any` | 成功时有值 | `if result.success: assert result.content is not None` |
| `SkillResult.error` | `str \| None` | 失败时非 None | `if not result.success: assert result.error is not None` |
| `match()` | `BaseSkill \| None` | 匹配时返回实例 | `assert result is None or isinstance(result, BaseSkill)` |
| `match_all()` | `list[BaseSkill]` | 可为空列表 | `assert isinstance(result, list)` |
| `scan_and_load()` | `(int, int)` | (loaded, skipped) ≥ 0 | `assert loaded >= 0 and skipped >= 0` |

### 2.3 错误处理

| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|
| SKILL.md 解析失败 | `SkillMdParseError` | WARNING 日志 + 跳过该文件 |
| 技能名冲突（builtin vs SKILL.md） | 无异常 | builtin 优先，SKILL.md 跳过 + WARNING |
| 门控条件不满足 | 无异常 | INFO 日志 + 跳过加载 |
| 技能执行异常 | `Exception` | 捕获并返回 `SkillResult(success=False)` |
| SKILL.md 目录不存在 | 无异常 | 过滤掉不存在的目录 |
| frontmatter YAML 格式错误 | `SkillMdParseError` | WARNING + 跳过 |
| 路径遍历攻击 | `ValidationError` | 拦截并记录 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 技能名称唯一性

**定义**：`SkillRegistry` 中每个技能名称唯一。重复注册覆盖旧技能并记录警告。builtin 优先于 SKILL.md。

**验证方法**：
```python
def verify_skill_name_uniqueness(registry: SkillRegistry) -> bool:
    """验证技能名称唯一性"""
    names = registry.list_names()
    return len(names) == len(set(names))
```

**检查频率**：
- [x] 每次 register() 调用后

**测试用例**：
```python
def test_skill_name_uniqueness():
    """测试技能注册不会导致名称重复"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.builtin.search_skill import SearchSkill

    registry = SkillRegistry()
    registry.register(SearchSkill())
    registry.register(SearchSkill())

    assert len(registry.list()) == 1
    assert verify_skill_name_uniqueness(registry)
```

#### 不变量 2: builtin 优先于 SKILL.md

**定义**：SKILL.md 的 `name` 与 builtin 冲突时，builtin 保留，SKILL.md 跳过。

**测试用例**：
```python
def test_builtin_priority_over_skill_md(tmp_path):
    """测试 builtin 技能优先于同名 SKILL.md"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.builtin.search_skill import SearchSkill
    from backend.skills.skill_md.loader import SkillMdHotLoader

    registry = SkillRegistry()
    builtin = SearchSkill()
    registry.register(builtin)

    skill_dir = tmp_path / "search"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: search\ndescription: override\n---\nbody"
    )

    loader = SkillMdHotLoader(registry, [tmp_path])
    _, skipped = loader.scan_and_load()

    assert registry.get("search") is builtin
    assert skipped >= 1
```

#### 不变量 3: 隐藏目录跳过

**定义**：以 `.` 开头的目录在 SKILL.md 发现时被跳过。

**测试用例**：
```python
def test_hidden_directory_skipped(tmp_path):
    """测试隐藏目录中的 SKILL.md 不被加载"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.skill_md.loader import SkillMdHotLoader

    hidden_dir = tmp_path / ".hidden_skill"
    hidden_dir.mkdir()
    (hidden_dir / "SKILL.md").write_text(
        "---\nname: hidden\ndescription: no\n---\nbody"
    )

    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, [tmp_path])
    loaded, _ = loader.scan_and_load()

    assert loaded == 0
    assert not registry.exists("hidden")
```

### 3.2 行为不变量

#### 触发词匹配一致性

**定义**：`match()` 大小写不敏感，相同输入返回相同结果。

```python
def test_trigger_matching_consistency():
    """测试触发词匹配一致性"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.builtin.search_skill import SearchSkill

    registry = SkillRegistry()
    registry.register(SearchSkill())

    result1 = registry.match("帮我搜索一下")
    result2 = registry.match("帮我搜索一下")
    assert result1 is result2
```

#### 热重载幂等性

**定义**：`hot_reload()` 对未变更文件执行后，技能仍可用。

```python
def test_hot_reload_idempotent(tmp_path):
    """测试热重载幂等性"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.skill_md.loader import SkillMdHotLoader

    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test\ndescription: test\n---\nbody"
    )

    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, [tmp_path])
    loader.scan_and_load()

    assert loader.hot_reload("test") is True
    assert registry.exists("test")
```

#### execute 异常安全

**定义**：`SkillRegistry.execute()` 不因技能内部异常崩溃。

```python
def test_execute_exception_safety():
    """测试技能执行异常安全"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.base import BaseSkill, SkillSchema, SkillResult

    class BrokenSkill(BaseSkill):
        def _build_schema(self):
            return SkillSchema(name="broken", description="broken", triggers=["broken"])
        def execute(self, params, context):
            raise RuntimeError("intentional failure")

    registry = SkillRegistry()
    registry.register(BrokenSkill())

    result = registry.execute("broken task", {}, {})
    assert result is not None
    assert result.success is False
```

### 3.3 性能不变量

#### 技能匹配延迟 < 1ms

```python
import time

def test_match_latency():
    """测试技能匹配延迟 < 1ms（50 技能）"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.base import BaseSkill, SkillSchema, SkillResult

    registry = SkillRegistry()
    for i in range(50):
        class S(BaseSkill):
            def __init__(self, idx):
                self._idx = idx
                super().__init__()
            def _build_schema(self):
                return SkillSchema(name=f"skill_{self._idx}", description=f"s{self._idx}", triggers=[f"trigger_{self._idx}"])
            def execute(self, params, context):
                return SkillResult(content="ok")
        registry.register(S(i))

    start = time.perf_counter()
    registry.match("trigger_25")
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 1, f"match 延迟 {elapsed:.2f}ms"
```

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: SKILL.md 解析失败

**触发条件**：YAML frontmatter 格式错误或缺少必需字段。

**影响**：严重性低，仅该文件不加载。

**恢复策略**：捕获 `SkillMdParseError`，WARNING 日志，`skipped` +1。

**验证测试**：
```python
def test_skill_md_parse_failure(tmp_path):
    """测试 SKILL.md 解析失败"""
    from backend.skills.skill_md.frontmatter import parse_file, SkillMdParseError

    bad_file = tmp_path / "bad.md"
    bad_file.write_text("no frontmatter here")
    try:
        parse_file(bad_file)
        assert False, "should have raised"
    except SkillMdParseError:
        pass
```

### 4.2 失败模式 2: 技能名冲突

**触发条件**：SKILL.md `name` 与已注册技能同名。

**恢复策略**：后加载者跳过 + WARNING 日志。

**验证测试**：
```python
def test_skill_name_collision(tmp_path):
    """测试技能名冲突处理"""
    from backend.skills.registry import SkillRegistry
    from backend.skills.skill_md.loader import SkillMdHotLoader

    registry = SkillRegistry()
    d1 = tmp_path / "a" / "shared"
    d1.mkdir(parents=True)
    (d1 / "SKILL.md").write_text("---\nname: shared\ndescription: A\n---\nA")

    loader = SkillMdHotLoader(registry, [tmp_path / "a"])
    loader.scan_and_load()
    assert registry.exists("shared")

    d2 = tmp_path / "b" / "shared"
    d2.mkdir(parents=True)
    (d2 / "SKILL.md").write_text("---\nname: shared\ndescription: B\n---\nB")

    loader2 = SkillMdHotLoader(registry, [tmp_path / "b"])
    _, skipped = loader2.scan_and_load()
    assert skipped >= 1
```

### 4.3 失败模式 3: 门控条件不满足

**触发条件**：`requires.bins` 中可执行文件不存在 / `os` 不匹配 / `always=False`。

**恢复策略**：INFO 日志 + 跳过。`always=True` 可绕过门控。

**验证测试**：
```python
def test_gating_blocks_unsupported():
    """测试门控阻止不满足条件的技能"""
    from backend.skills.skill_md.gating import GatingContext, evaluate_gating
    from backend.skills.skill_md.skill import SkillMdDocument, RequiresSpec, DispatchMode

    doc = SkillMdDocument(
        name="test", description="test", triggers=[], body="body",
        base_dir="/tmp",
        requires=RequiresSpec(bins=["nonexistent_binary_xyz"]),
    )
    result = evaluate_gating(doc, GatingContext())
    assert not result.allowed
```

### 4.4 失败模式 4: 技能目录发现失败

**触发条件**：所有 SKILL.md 搜索目录均不存在。

**恢复策略**：`discover_skill_md_dirs()` 返回空列表 → 仅 builtin 可用。

**验证测试**：
```python
def test_discovery_with_no_dirs():
    """测试无可用目录时的技能发现"""
    from backend.skills.skill_md.loader import discover_skill_md_dirs
    dirs = discover_skill_md_dirs()
    for d in dirs:
        assert d.is_dir()
```

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/verification/g003/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/verification/g003/ -v --cov=backend/skills
```

**覆盖范围**：
- [ ] SkillRegistry register/unregister/get/match/match_all/execute
- [ ] BaseSkill 子类 Schema + 触发词匹配
- [ ] SkillMdHotLoader scan_and_load / hot_reload
- [ ] discover_skill_md_dirs() 三级目录发现
- [ ] frontmatter.parse_file() YAML 解析
- [ ] gating.evaluate_gating() 条件评估
- [ ] builtin 优先 + 隐藏目录跳过

### 5.2 集成测试

**位置**：`tests/integration/g003/`

**覆盖范围**：
- [ ] SkillRegistry → InprocSkillAdapter → SkillPort 桥接
- [ ] 端到端 SKILL.md 发现 → 加载 → 匹配 → 执行
- [ ] 热重载流程

### 5.3 属性测试

**测试的属性**：
- [ ] 匹配幂等性：同一文本多次 match 返回相同结果
- [ ] 注册幂等性：register → unregister → register 状态一致
- [ ] 异常安全性：任何输入不导致 execute 崩溃

### 5.4 性能测试

**测试的指标**：
- [ ] 技能匹配延迟 < 1ms（50 技能）
- [ ] SKILL.md 加载延迟 < 10ms/技能

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 已加载技能数 | 仪表 | builtin + SKILL.md | < builtin_count | SkillRegistry |
| SKILL.md 加载失败率 | 计数器 | 0 | > 3/天 | WARNING 日志 |
| 热重载触发次数 | 计数器 | 按需 | > 50/天 | HotLoader.get_stats() |

### 6.2 健康检查

**端点**：`GET /health/skills`

**返回格式**：
```json
{
  "status": "healthy",
  "checks": {
    "registry": "ok",
    "builtin_count": 4,
    "skill_md_count": 2,
    "skill_names": ["search", "writer", "coder", "travel", "custom_1", "custom_2"]
  },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 性能测试 | 🔴 | 0% | - |
| 属性测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 技能名称唯一性 | ❌ | - |
| builtin 优先 | ❌ | - |
| 隐藏目录跳过 | ❌ | - |
| 匹配一致性 | ❌ | - |
| 热重载幂等 | ❌ | - |
| execute 异常安全 | ❌ | - |

### 7.3 失败模式测试

| 失败模式 | 检测测试 | 恢复测试 | 状态 |
|----------|----------|----------|------|
| SKILL.md 解析失败 | ❌ | ❌ | 🔴 |
| 技能名冲突 | ❌ | ❌ | 🔴 |
| 门控不满足 | ❌ | ❌ | 🔴 |
| 目录发现失败 | ❌ | ❌ | 🔴 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [BaseSkill / SkillSchema / SkillResult](../../backend/skills/base.py) — 技能基类
- [SkillRegistry](../../backend/skills/registry.py) — 技能注册表
- [SkillMdHotLoader](../../backend/skills/skill_md/loader.py) — SKILL.md 热加载器
- [SkillMdDocument / SkillMdSkill](../../backend/skills/skill_md/skill.py) — SKILL.md 数据结构
- [frontmatter parser](../../backend/skills/skill_md/frontmatter.py) — YAML 解析
- [GatingContext](../../backend/skills/skill_md/gating.py) — 门控条件
- [validation](../../backend/skills/skill_md/validation.py) — 路径安全
- [builtin skills](../../backend/skills/builtin/) — 内置技能
