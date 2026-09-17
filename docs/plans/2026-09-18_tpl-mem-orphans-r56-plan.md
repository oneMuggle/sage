# r56 批次计划：变量记忆失联条目管理（orphan 清理）

日期：2026-09-16（分支创建于 main@004d47d8）
文件面：TemplateFillDialog.tsx（+1 枚举辅助函数）、PromptTemplatesTab.tsx、
其 memory 测试；零后端改动。

## 背景

R31 变量记忆按模板**内容哈希**存 localStorage（`sage:tplfill:<djb2>`）。
模板内容一改或模板一删，旧键立即失联——数据永久残留、不可见、不可清
（只能开发者工具手删）。R38 加了按模板展示/清除，但失联条目没有任何入口。

## 方案（纯前端）

1. `TemplateFillDialog.tsx` 增 `listTplMemoryEntries()`：扫描 localStorage
   中 `sage:tplfill:` 前缀键，返回 `{key, hash, values, parseError}` 列表
   （读失败静默降级，与既有口径一致）。
2. `PromptTemplatesTab`：
   - 绑定键集合 = 当前模板逐一 `tplStorageKey(tpl.content)`；
   - 失联条目（无模板持有的键）渲染为列表尾部独立区块：短哈希 + 值预览
     （截断 120 字符）+ 单条删除 + 「全部清除」；
   - 无失联条目时整块不渲染（不占版面）。
3. 现有按模板记忆展示/清除逻辑不动。

## 测试
- 绑定 + 失联条目共存 → 失联区块只列失联键；
- 单条删除 → localStorage 键消失；
- 全部清除 → 失联键全清，绑定键保留；
- 全部绑定 → 区块不渲染。

## Win7 对齐
新功能，不 cherry-pick 到 release/win7。
