# R161：py38 地雷扫描器 + wiki prompt 模板单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；py38 运行期地雷 AST 扫描器（#1500/
  #1514/#1517 双扫描器统一）/ wiki Ingest & RAG prompt 模板
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/py38_hazard_scan.py`（204 行，win7 线守门工具本身——R1~R12 规则
族 + FILE_EXEMPTS + 行级 `# py38-ok` 豁免 + 语法错误兜底）与
`wiki/llm_prompts.py`（122 行，Ingest/RAG prompt 模板与四个 format
函数）此前零测试。扫描器是 CI 门禁的守门人，其规则正确性必须钉死。

## 覆盖矩阵（约 26 例）

### `backend/tests/unit/tools/test_py38_hazard_scan.py`（15 例）

scan_file 逐规则：R1 isinstance 联合类型、R2 asyncio.to_thread、
R3 zip(strict=)、R4 Path.hardlink_to、R5 Path.is_relative_to、
R6 read_text(newline=)、R12 datetime.UTC、R7 str.removeprefix、
R8 import zoneinfo/graphlib（import 与 from 两种）、R9
functools.cache、R10 @dataclass(slots=)；**行级豁免** `# py38-ok`；
**干净代码零命中**（防误报）。FILE_EXEMPTS / main 退出码不测（I/O
层属薄壳）。

### `backend/tests/unit/wiki/test_llm_prompts.py`（11 例）

四个 format 函数：注入值出现、双花括号 JSON 样例 format 后保留字面
`{`/`}`、Step2 六参数全注入、RAG system 含中文规则与 context、user
含 query、模板常量形态（SCHEMA 版本字符串不在本文件，跳过）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
