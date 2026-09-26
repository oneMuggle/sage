# R139：MemoryContext 分层记忆上下文单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；Hermes 冻结快照 + Mem0 原子事实分层 /
  P2 项目画像 / P4 composite_score 排序
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/memory.py`（139 行，MemoryContext 四层记忆 + Token 预算感知的
format()：核心画像分用户/项目双块、工作记忆取末 3 条、情景+语义按
composite_score → importance → rrf_score 降序填充预算）此前零测试——
它直接决定注入 LLM prompt 的记忆形态。

## 覆盖矩阵（15 例）

1. has_memories：全空 False、任一层单独 True；
2. format 全空 → ""；
3. format 仅 core → 【用户画像】块 + "- content" 行；content 截断
   150；
4. scope='project' 条目单独进【项目画像】块（不与用户画像混读）；
5. working 取末 3 条、"- [role]: content" 形态、content 截断 100；
6. 情景+语义合并进【相关记忆】、按 composite_score 降序（未打分回退
   importance、再回退 rrf_score）；summary 优先于 content；
7. 预算：core 超自身预算整体跳过；working 预算不足跳过；记忆行逐行
   填充到预算截断（break）；
8. _estimate_tokens：中文字符 1.5 字/token、其他 4 字符/token。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
