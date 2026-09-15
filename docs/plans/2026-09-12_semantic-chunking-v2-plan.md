# Round 17 批次 C —— 语义索引分块 v2：函数边界分块（检索精度优化）

> 背景：`codebase_search` 的语义索引（Round 5 批次 E）按固定 40 行滑窗切块，
> 函数体被拦腰切断、无关行混入向量，是检索噪声的主要来源。
> 本批把切块策略升级为「顶层函数/类边界优先，无定义回退滑窗」。

## 设计

### chunk 策略（workspace_index.py）
- `chunk_file(path, lines)`：按扩展名分派——
  - 有语义边界提取器的扩展 → `chunk_file_semantic`；
  - 其他（md/txt/yaml/css/html/json/sh/sql/toml）→ v1 滑窗 `chunk_file_lines`。
- `chunk_file_semantic`：
  1. 收集**顶层**定义起始行（无缩进的 def/class/function/fn/func/struct/trait/impl/interface/enum 等，按语言族正则；Python 装饰器行回溯并入起始行）；
  2. 相邻边界之间的块若 ≤ `SEMANTIC_MAX_LINES`（80）→ 整块一个 chunk（start_line = 定义行）；
  3. 超长块内部再按 40 行滑窗切分（保 25% 重叠，同 v1）；
  4. 首个定义之前的前导区（imports/注释头）→ 滑窗切块；
  5. 无任何定义的文件 → 整体回退 v1 滑窗。
- 语言族（v2 范围，保守起步）：
  - py：`async def` / `def` / `class`（+装饰器）
  - js/ts/tsx/jsx：`function` / `class` / `interface` / `type` / `const fn =`（可选 export/async 前缀）
  - go：`func` / `type X struct|interface`
  - rs：`fn` / `struct` / `trait` / `enum` / `impl`（可选 pub）
  - java/cs：`class` / `interface` / `enum`（可选修饰符）
  - rb：`def` / `class`
  - c/h/cpp/hpp：`struct` / `class`（函数签名正则误报率高，v2 不做）

### 索引失效
- `meta['chunker_version'] = '2'`；与库内不符 → `DELETE FROM chunks/files` 重建
  （与 dim 变更同路径，`_index_workspace` 内先查后写）。

### 不变
- 向量化/余弦检索/增量 mtime+size 跳过逻辑、`MAX_FILES`/`MAX_FILE_BYTES`/
  单文件 256 chunk 上限、搜索接口与响应结构。

## 测试（backend/tests/unit/test_workspace_index.py 增补）
- Python 多函数文件 → 每函数一个 chunk，start_line 对齐定义行；
- 带装饰器的函数 → 装饰器并入 chunk；
- 超长函数（>80 行）→ 内部再切且不丢行；
- 无定义文件（md）→ 与 `chunk_file_lines` 输出一致（回退）；
- `chunker_version` 变更 → 重建（沿用 `test_dim_change_rebuilds` 模式）；
- 既有滑窗测试保持绿（回退路径复用）。

## 不做
- tree-sitter AST 级解析（v3 候选）、类方法级边界、跨行签名归一。
