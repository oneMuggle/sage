# 90 — Word 脚注/尾注支持设计评审稿（Round 56）

> 日期: 2026-09-19 · 分支: `docs/footnotes-design`
> 系列: Word/Office 写作能力增强第 57 轮（设计评审稿，非实现）
> 性质: **设计文档**——脚注（footnotes）是 Word 写作线程最后一个大特性，
> 因 python-docx 无原生 API 需自建 OOXML part，先行评审再排期实现。

## 1. 需求与现状

学术论文/出版稿件依赖脚注（引文出处、补充说明）。当前 office_create
无法生成脚注：**python-docx 1.1 无 footnotes API**，且其默认模板根本
不含 `footnotes.xml` part——支持脚注必须做 OOXML 包装层手术。

## 2. OOXML 结构分析（实现的关键事实）

脚注需要四件套，缺一 Word/WPS 打开即报"内容有问题"：

1. **part 本体** `word/footnotes.xml`，content-type
   `application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml`；
2. **document part → footnotes part 的 relationship**；
3. **两个系统脚注**：`id=0`（separator）与 `id=1`
   （continuationSeparator）——缺失时 Word 仍能打开但脚注分隔线异常；
4. **正文引用 run**：`<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>
   </w:rPr><w:footnoteReference w:id="N"/></w:r>`；脚注内容段含
   `<w:footnoteRef/>` + 空格 + 正文，样式 `FootnoteText`。

样式表（styles.xml）缺 `FootnoteText`/`FootnoteReference` 样式时 Word
回退 Normal——可接受但建议补样式定义（与 R42 SEQ 题注补样式同思路）。

python-docx 的 OPC 层（`doc.part.package` / `Part` / `Relationships`）
足以手工挂载以上四件——无需绕开 python-docx 直接操作 zip。

## 3. 接口设计（拟）

- 模型：`WordFootnoteSpec`（text, 必填）；
- 锚点语法与 R45 交叉引用同哲学：正文段落文本写 `[^1]`（或
  `{{fn:备注文本}}` 内联式），生成器按出现顺序解析为
  footnoteReference run，脚注内容按序写入 footnotes part；
  - 内联式对 LLM 更自然（一处写完，无两列表对齐负担），推荐内联式；
- 读取侧：`read_docx` 增 `footnotes: List[str]` 回读；
- 编号由 Word 渲染期自动维护（跨节连续；分节重编需 `w:footnotePr`
  节属性，Phase B）。

## 4. 分期

- **Phase A（1 轮）**：写侧最小闭环——内联标记解析 + footnotes part
  挂载 + read 回读 + lint `footnote/residue`（未解析标记）；
- **Phase B（1 轮）**：样式定义（FootnoteText/FootnoteReference 注入
  styles.xml）+ `w:footnotePr` 每节重编开关 + office_update 追加脚注；
- **Phase C（可选）**：尾注（endnotes.xml，结构同构）。

## 5. 风险

- **part 手术**：python-docx 的 part 注册 API 属半公开层，升级兼容
  需盯上游；缓解：封装为 `footnotes_part.py` 单模块 + 特性测试锁行为；
- **兼容性**：WPS/老 Word 对缺失样式的容错需真实环境验证（项目无
  WPS CI——发布说明标注"建议 Word 2016+"）；
- **read 侧复杂度**：`_render_paragraph_text` 需感知
  footnoteReference run（输出 `[^N]` 标记回写 markdown 语义）。

## 6. 结论

可行，工程量 Phase A 约 1 轮、完整 2-3 轮。建议评审点：
(1) 内联 `{{fn:}}` vs 两列表锚点选型；(2) 是否同轮做尾注；
(3) Windows/真实 Word 的人工验证步骤。
