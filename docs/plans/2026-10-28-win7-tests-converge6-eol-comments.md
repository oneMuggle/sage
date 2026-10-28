# Win7 第六批：收敛纯 EOL 与纯注释差异

- 日期：2026-10-28
- 基线：`release/win7` @ `bdd0c176b`
- 对照：`main` @ `99ed15b98`
- 范围：`backend/tests` actionable 55 个里的「非代码差异」部分

## 分类方法

前五批处理的是「有真实代码差异」的文件，靠双版本实测 + test id 比对。这批要处理
「看起来没差」的文件，问题反过来：**怎么证明它们真的只差 EOL 和注释？**

做法是 AST 比对：

1. 把行尾统一（`\r\n` / `\r` → `\n`）后逐字节比，相同即 **仅 EOL**；
2. 否则用 `ast.parse` 取 `ast.dump` 比对，相同即 **仅注释/格式**（AST 不含注释与空白）；
3. 都不相同才是 **真实代码差异**。

55 个 actionable 文件的分类结果：

| 类别 | 数量 |
|---|---|
| 仅 EOL | 8 |
| 仅注释/格式 | 9 |
| 真实代码差异 | 38 |

本批处理前 17 个（8 + 9），38 个真实差异留待后续按批实测。

## 关键：AST 相同 ≠ py3.8 可解析

17 个文件按分类全部取 main 内容后，py3.8 兼容闸门报 **4 个文件 9 处违规**：

```
test_adapter_tag_graph.py:209,242
test_project_advisor.py:120,191
test_project_knowledge_extractor.py:395,422,457
test_project_task_decomposer.py:380,420
  py38 runtime: parenthesized `with (a as x, b as y):` is Py3.9+ grammar
```

原因：main 把这些文件的嵌套 `with` 合写成了括号形式。**我的 AST 比对是跑在
py3.11 上的，括号 `with` 在 3.11 能解析、且产出与原写法完全等价的 AST**，于是被判为
「仅格式差异」——但它落在 py3.8 上是 `SyntaxError`。

这和第五批踩的是同一个坑的变体（那次是 `test_chat_stream.py`，靠闸门拦下）。
**结论：py3.8 闸门不是补充检查，是这类收敛的唯一安全网。**

处理方式：对这 4 个文件跑官方 `scripts/py38_compat_rewrite.py`，把单元素的
`with ((...))` 还原成普通 `with`，保留 main 的注释与行尾。改写后闸门归零。

因此最终状态：

- 13 个文件：blob 与 main **完全一致**；
- 4 个文件：内容取 main + py3.8 改写，与 main 只差 `with` 的写法（不可避免）。

## 验证

```
py3.11   17 文件分组    67 + 91 + 95 + 36 = 289 passed
py3.8    17 文件分组    144 + 103 + 42     = 289 passed
py3.8 闸门              Scanned 1890 files; 0 with violations
ruff 15 文件            All checks passed
```

改写后另外确认 13 个未改动文件的 blob 与 main 逐一相同。

## 未纳入

38 个「真实代码差异」文件不在本批。它们需要逐文件双版本实测 + test id 比对，
按前五批的节奏分批处理；其中已知会碰到 main 使用 py3.9+ 语法的情形，须先过闸门。
