# 78 — office_update 修订后 TOC 刷新（Round 41）

> 日期: 2026-09-18 · 分支: `feat/word-update-toc-refresh`
> 系列: Word/Office 写作能力增强第 42 轮（R39 生成 76 号 / R40 编排 77 号
> 之后的修订侧收口）

## 1. 定位

文档修订（增删段落）同样让目录过期——页码漂移、条目增减。R40 给
生成侧加了 `refresh_toc` 一步到位；本轮把同一标志补到 **office_update**：
修订成功后原地刷新目录域。至此 TOC 真页码故事线闭环：生成/修订 →
真页码，手工 F9 退出必选项。

## 2. 变更

- `office_update` 工具新增 `refresh_toc: boolean`（word 专用；
  dry_run 预览下自然无效果）：
  - **doc_id 受管路径**：upfront 守卫——service.update 前经
    `_managed_doc_info`（binding + doc row）解析文档类型，非 word 直接
    `refresh_toc_only_supported_for_word`（修订尚未发生，报错语义准确；
    解析失败放行，由成功后的 attach 降级兜底）；word 修订成功后定位
    落盘文件刷新，附加 `toc_refresh` 摘要（ok/toc_count/error），维持
    「不回显受管绝对路径」不变式。
  - **file_path 路径**：`_infer_doc_type` 已知类型即 upfront 严格拒绝
    非 word（ops 未执行——测试断言 xlsx 未被追加行）；word 成功后刷新
    （workspace 绑定优先、回退文件父目录）并附加摘要。
  - 降级契约同 R40：刷新失败不改写修订成功态。
- 搭车：report-writing SKILL.md 补 R37 横排分节+宽表场景文档——
  `format_spec.section_breaks: [{start_paragraph, page_setup:
  {orientation: "landscape"}}]`（NEW_PAGE 分节 + 新节页面设置），
  含"第 3 章整章横排放资金明细宽表"组合示例。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_office_update_tool.py` +4 项（真 DB + binding fixtures）：
受管 doc_id 摘要附加且路径不泄漏、COM 不可用降级不改写成功态、
file_path word 成功附加（无绑定回退父目录）、非 word upfront 拒绝且
ops 未执行；schema 键集断言同步 `refresh_toc`。refresh 函数统一
monkeypatch（linux CI 可跑）。
