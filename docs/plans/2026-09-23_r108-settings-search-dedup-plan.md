# R108 批次计划 —— 设置搜索索引：重复条目修复 + 不变量测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r108-scan`（基于 origin/main afa6ac36）

## 发现的真 bug

`settingsSearchIndex.ts` 末尾 **`zotero` 条目重复登记两次**（一次多行、一次
单行，内容相同）。`searchSettings` 按 `SETTINGS_SEARCH_INDEX.filter` 返回，
设置页搜索"zotero/文献"会出现重复结果项。定位方式：全文件键提取发现
`duplicate keys: ["zotero"]`。

## 批次内容

1. **修复**：删除重复的单行 zotero 条目（保留多行版，61 → 60 条）。
2. **测试** `src/pages/settings/__tests__/settingsSearchIndex.test.ts`
   （10 用例）：
   - 不变量：key 全局唯一（本 bug 的回归锁）；四字段非空；keywords 全小写
     （消费方按 toLowerCase 匹配的前提）；tab 值在已知集合内；zotero 恰好
     一条；
   - `searchSettings` 行为：空/空白查询 → []；中文命中 label（'主题'）；
     英文大小写不敏感（'ZOTERO'）；keywords 别名命中（'telegram' →
     gateway）；多词 AND 语义（'font size' 命中 / 加不存在词归零）；无命中
     返回空数组。

## 验证矩阵

- 本机 vitest：10/10 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest（覆盖率棘轮只增不减）。

## win7 对齐

设置搜索索引为 main 侧功能面（前端不回移 win7），无需 cherry。
