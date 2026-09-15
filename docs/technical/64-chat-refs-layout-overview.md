# 64 — @引用摘要带页眉/页脚/目录域概况（Round 16）

> 日期: 2026-09-12 · 分支: `feat/chat-refs-header-footer`
> 系列: Word/Office 写作能力增强第 10 轮（R15 读取侧闭环 #689 的直接衔接）

## 1. 变更

`@docx` 文件的摘要（`backend/chat/attachment_resolver.py::_digest_word`）
新增 `_render_layout_overview`：把 Round 15 读取字段转成概况行——

- `页眉(第N节): <文本>`
- `页脚(第N节): <文本> · 含页码域`
- `目录域: <instr>`

语义与批注概况（round-2 R3-digest）同款：**独立维度，不受正文截断
预算影响**；读取结果缺 Round 15 字段（旧序列化产物）时 getattr 兜底
为空，零报错。

## 2. Win7 对齐与测试

零新增依赖、零 API 面变更；不 cherry-pick（31-win7-lts.md §2）。
`tests/unit/test_attachment_layout_overview.py` 4 项：空/缺字段渲染空、
页眉+页码域、页脚文本+目录域。chat_refs 回归 21 项全绿。
