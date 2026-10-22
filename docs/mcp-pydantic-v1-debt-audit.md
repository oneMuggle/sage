# win7 分支 pydantic v1 债务勘察（结论：无实质债务）

日期：2026-10-22 ·  分支：`chore/win7-align-b3-20261021` ·  基线：`origin/release/win7`

## 背景

B3（#2291）连红两轮的根因是 pydantic v1/v2 的**注解解析时机**差异：v1 在类创建期
解析，v2 惰性解析。本地两个 conda 环境（`sage-backend` / `sage-backend-py38`）装的
**都是 pydantic 2.5.0**，只有 CI 的 py38 通道钉 1.10.13
（`backend/requirements-py38.txt:18`），所以「本地导入 OK / `--collect-only` 0 errors」
全是假绿，必须等 CI 才暴露。

修完 B3 后需要回答：仓库里是否还残留**其他** pydantic v1 债务，需要独立小 PR 清理？
本文记录勘察过程与结论，避免后人重复排查。

## 结论

**无实质债务。** 唯一真实的两类失败模式已在 `8960ac7c7` 变成静态闸门规则，
全仓扫描 0 violations。原先怀疑的「14 个文件直接 `from pydantic import ConfigDict`」
**不是债务** —— `ConfigDict` 在 pydantic 1.10.13 里就存在。

## 勘察明细

### 1. 垫片已覆盖的 v2 API（安全，不需拦）

`backend/compat/win7/pydantic_compat.py` 的 `install()` 在 v1 运行时给 `BaseModel`
注入以下方法，所以业务代码直接写这些 v2 API 是安全的：

`model_dump` · `model_dump_json` · `model_copy` · `model_construct` ·
`model_validate` · `model_validate_json` · `model_json_schema` · `model_fields`(property)

另有两处 monkey-patch：

- `pydantic.Field` → 把 v2 的 `pattern=` 转译成 v1 的 `regex=`
- `BaseModel` 的 metaclass `__new__` → 把 `model_config = ConfigDict(...)` 转成 v1 的
  `class Config`（`_win7_model_config_hook`）
- `pydantic.ValidationError.error_count` → v1 没有此方法，挂一个走 `len(self.errors())`

模块顶层自动调 `install()`（幂等）。历史教训写在源码注释里：2026-09-16 之前
docstring 要求使用方自己调 `install()`，但**实际没有任何调用点**，导致 hook 全部
失效、PR #892 的 CI py38 有 9 个 pytest 失败。

### 2. `ConfigDict` —— 误判为债务，实际合法

以下 14 个文件直接 `from pydantic import ConfigDict`，而非从垫片 import：

```
backend/api/git_status_routes.py:21        backend/office/capabilities.py:19
backend/api/office_lifecycle_routes.py:15  backend/office/excel_recalc.py:27
backend/api/office_quarantine_routes.py:37 backend/office/legacy_import.py:28
backend/api/project_ai_routes.py:43        backend/office/pdf_preview.py:33
backend/api/project_schemas.py:7           backend/office/ppt_template.py:24
backend/api/v1/design_routes.py:21         backend/office/template_thumbnail.py:29
backend/design/models.py:7                 backend/plugins/manifest.py:23
```

**这不是债务。** 权威证据 —— pydantic v1.10.13 的 `pydantic/__init__.py`：

```python
from .config import BaseConfig, ConfigDict, Extra   # 第 5 行
...
__all__ = [ ... 'BaseConfig', 'ConfigDict', 'Extra', ... ]
```

（来源：`raw.githubusercontent.com/pydantic/pydantic/v1.10.13/pydantic/__init__.py`）

`ConfigDict` 自 v1.10.0 起就存在（changelog #2557 “config customization directly
via a dict is now possible”）。这也解释了为什么 CI py38 通道跑全量 pytest
（`pytest -n auto --dist loadfile`）却是绿的：这些 import 在 1.10.13 下根本不会失败。

注：`backend/agents/profiles.py:72` 与 `backend/orchestration/llm_factory.py:225` 里的
`.model_config` **与 pydantic 无关**，是 LLM profile 的自定义配置属性，属同名巧合。

### 3. `field_validator` / `model_validator` —— 真 v2-only，但已全部走垫片

这两个符号**不在** v1.10.13 的 `__all__` 里（v1 只有 `validator` / `root_validator`），
直接从 `pydantic` import 会 ImportError。垫片在 v1 分支用 `_validator` /
`_root_validator` 实现了同名 fallback（含 `mode="before"` → `pre=True` 与
`allow_reuse=True` 的转译）。

全仓使用点**都已正确从垫片 import**：

```
backend/api/orch_routes.py:20            from ...pydantic_compat import field_validator
backend/models/update.py:7               from ...pydantic_compat import field_validator
backend/model_catalog/schemas.py:12      from ...pydantic_compat import field_validator
backend/office/journal/models.py:16      from ...pydantic_compat import ConfigDict, field_validator
backend/office/models.py:20              from ...pydantic_compat import ConfigDict, field_validator
backend/plugins/manifest.py:23           try: from pydantic import field_validator, model_validator
```

`plugins/manifest.py` 那处在 `try:` 块内，有 except 回退，不构成风险。

另有两处注释明确记录了「不再用 `field_validator` 装饰器（Pydantic 2 语法在
Pydantic 1 / Win7 不可用）」的历史决定：`backend/api/hex_routes.py:79`、
`backend/api/legacy_skills_routes.py:426`。

### 4. 其余 v2-only 属性 —— 全仓 0 使用

```
.model_computed_fields : 0 处      .model_post_init    : 0 处
.model_extra           : 0 处      .model_serializer   : 0 处
.model_fields_set      : 0 处
```

### 5. `model_rebuild` —— 唯一真实且已闸门化的债务类型

`model_rebuild` **不在** `install()` 的注入列表里，v1 的 `BaseModel` 没有这个属性，
裸调会在**模块导入期**抛 AttributeError。又因 FastAPI router 被 `main.py` 链式导入，
一处裸调就让整个测试套件在 collection 期全 E —— #2290 的 CI 日志因此膨胀到 56 MB
（11264 个用例全 E，pytest 为每个 error 打印完整 locals），`grep FAILED` 零命中。

全仓 4 个调用点**都已加双版本守卫**：

```
backend/api/project_ai_routes.py:77/79     if hasattr(...): model_rebuild() else: update_forward_refs()
backend/api/worktree_routes.py:139/140     同上（在 B2 分支）
backend/office/models.py:272/274           同上（OfficeWordReadResult）
backend/office/models.py:1559/1561         for _cls in (...) 循环守卫（ExcelSheetSpec / ExcelPrintSetupSpec）
```

标准守卫形态（v1 优先，因为 win7 是 LTS 目标）：

```python
if hasattr(_cls, "update_forward_refs"):
    _cls.update_forward_refs()   # pydantic v1
elif hasattr(_cls, "model_rebuild"):
    _cls.model_rebuild()         # pydantic v2
```

## 已落地的防回归措施

`8960ac7c7` 给 `scripts/check_py38_compat.py` 加了两条规则，把上述两类失败模式
变成 CI 静态可查（不再依赖 40 分钟的 pytest 反馈）：

1. **裸 `.model_rebuild()`** —— 豁免条件：调用行上方 6 行内有针对同一对象的
   `hasattr` 守卫，或该调用处在 `for _cls in (...)` 守卫循环体内。
2. **pydantic 模型字段前向引用本文件更晚定义的类** —— 豁免条件：该类被
   `update_forward_refs()` / `model_rebuild()` 守卫覆盖，或被引用类定义在使用点之前。

实现上有三个非显然的坑，都写在源码注释里：

- 守卫名本身写在字符串里（`hasattr(X, "model_rebuild")`），而 `_strip_strings` 会把
  字符串抹成空格 —— 所以**守卫必须用原始行匹配，调用才用 code_lines 匹配**。
  第一版两条都用 code_lines，结果 4 个已正确加守卫的点全被误报。
- 规则 2 用 `ast` 而非正则判「类字段」。正则按缩进猜会把**方法体内的局部变量注解**
  和**方法参数注解**也算成字段（`mock_server.py` 的 `state: MockLLMServer`、
  `download_tool.py` 的 `ctx: _DownloadContext` 就这样被误报）。
- 基类判定只看名字末段（`BaseModel` / `BaseSettings` / 本文件已判定的 pydantic 类）。
  第一版用 `"Model"`/`"Schema"` 子串猜测，把 `BaseHTTPRequestHandler` 之类误判成
  pydantic 类。

两条规则同时接进 `check_runtime_apis`（CI 全仓扫描走这条）和 `check_source`
（自测走这条）。只接前者会让自测测不到新规则 —— 负向验证 4/4 FAIL 才暴露出来。

## 验证记录

合成样本 13/13：负向 4 个全报（裸 rebuild、字段前向引用、守卫对象名不匹配、
`Optional["X"]` 字符串形式前向引用），正向 9 个全不报（三种守卫形态、普通类、
局部变量注解、方法参数注解、被守卫覆盖的类、被引用类在前、docstring 提及）。

真实历史样本 4/4（`git show` 取真实文件，不依赖临时副本）：

| 提交 | 行数 | 命中 | 期望 |
|---|---|---|---|
| `8a9b25383`（B3 第1轮，CI 红） | 1553 | 3 | 报 ✓ 精确复现 `section_breaks`/`figure_index`/`table_index` |
| `04cc201e4`（B3 第2轮，CI 红） | 1557 | 2 | 报 ✓ 复现剩余两处 |
| `7825ad594`（已修） | 1561 | 0 | 不报 ✓ |
| `origin/release/win7`（基线） | 1443 | 0 | 不报 ✓ |

自测固化：`backend/tests/unit/test_py38_compat_gate.py` 新增 10 个用例（5 → 15），
其中 3 个明确标注「回归」，锁住 `browser_launcher.py` / `mock_server.py` /
`download_tool.py` 这三种误报形态。

## 遗留限制

**本地无法验证 pydantic v1 行为。** 两个 conda 环境都是 2.5.0，隔离 venv 装 1.x
因 PyPI SSL 失败（`SSLError(SSLZeroReturnError(6, 'TLS/SSL connection has been
closed (EOF)'))`）。所以 v1 行为只能靠：静态检查 + `git show` 历史样本对照 +
CI 的 py38 通道。**不要再把任何「本地 py38 通过」当作 v1 证据。**
