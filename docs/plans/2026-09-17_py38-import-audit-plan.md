# py38 导入链审计——main 运行时与 win7 对齐修复（Round 18）

日期：2026-09-17 ｜ 分支：`feat/py38-import-audit` ｜ 基线：#792（f528cbe7）

## 背景

main 分支自「py38 纪律」松动后，运行时导入链积累了大量 py39+/py310+ 语法，
`import backend.main` 在 win7 的 Python 3.8 下导入即崩。这类地雷会随 win7
同步 cherry-pick 过去，炸掉 release/win7 的构建。触发点：#935 批次中
`import backend.wiki.community`（wiki/__init__ → mcp_server → wiki_routes）
在 py38 直接失败。

## 修复范围（backend 非测试代码，103 文件）

| 类别 | 数量 | 说明 |
|---|---|---|
| PEP 604 union（`X \| None`） | 254 处 | 仅运行时求值位置：FastAPI 路由签名（装饰期）、pydantic 模型字段（类创建期）、无 `__future__` 模块的全部注解 |
| PEP 585 内建泛型（`dict[str]`） | 67 文件 | `Dict/List/Tuple/Set/FrozenSet` |
| collections.abc 下标 | 10 文件 | `Mapping[K,V]` 等改回 typing 别名 |
| `typing.Annotated` | 1 文件 | → typing_extensions（py38 无） |
| 模块级类型别名 union | 1 处 | permission_gate.ApprovalContextResolver |
| backend.main 返回注解 | 1 处 | `str \| None` → Optional[str] |

修复由 AST 引导（只动求值位置，不碰纯注解字符串），文本级替换保留原格式；
未运行全局 `ruff format`（会重排全库 1000+ 文件，污染 diff）。

## 测试侧配套

- `office/test_pdf.py` 的 `Path.stat` 存根签名改为 `*args, **kwargs` 双版本兼容
  （原仅兼容 py3.12 的 follow_symlinks，py38 反向炸）

## 验证

- py38 环境（sage-backend-py38 / 3.8.20）：`import backend.main` 通过；
  unit 全套件（4 个 py39 语法测试文件除外）运行通过
- modern 环境（sage-backend / 3.11+）：unit 全套件运行通过（语义无回归）
- `ruff check backend/` 干净

## 已知范围外

- 4 个测试文件使用 py39+ 括号 `with` 语法（test_credential_vault/
  test_http_factory/test_storage_schema/test_web_cache），win7 分支有自己的
  py38 适配版本，main 侧测试文件不在本批范围
