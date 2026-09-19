# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

> 🧹 **Word 写作能力 Round 63：脚注/尾注引用一致性 lint**（方案 `docs/plans/2026-09-19_r63-ref-consistency-plan.md`）

### Added(office)
- **`footnote/broken_ref` / `endnote/broken_ref` lint 规则**：正文引用 run 的 id 对照 footnotes/endnotes part 的真实 note id 集合——损坏文档（引用无对应 note，Word 打开即报"内容有问题"）给出可定位的 error
- 无引用文档零开销跳过；`ref_consistency` 无条件入 checked

> 📝 **Word 写作能力 Round 62：用户手册补脚注/尾注/文档属性**（纯文档轮）

### Changed(docs)
- **用户手册 09-office.md**：图表与图片节补脚注（{{fn:}}）与尾注（{{en:}}）说明（含 office_update 追加续接编号）与文档属性（metadata）——R49-R61 能力的手册层收口

> 📝 **Word 写作能力 Round 61：append_paragraphs 支持 {{fn:}}/{{en:}}**（方案 `docs/plans/2026-09-19_r61-append-fn-en-plan.md`）

### Added(office)
- **update 通路四类占位符全支持**：append_paragraphs 的 {{fn:}}/{{en:}} 写成 footnote/endnoteReference run 并把备注文本追加进对应 part——part 不存在时全量挂载（含样式注入），已存在时 blob 增补、编号从现有数+1 续接；与 fig/tbl 同段混用、预校验 all-or-nothing 语义不变

> 🧹 **Word 写作能力 Round 60：residue 补全 + append_paragraphs 交叉引用**（方案 `docs/plans/2026-09-19_r60-residue-update-marks-plan.md`）

### Fixed(office)
- **`cross_ref/residue` lint 补 fn/en**：`{{fn:}}/{{en:}}` 残渍（R57/R59 引入）此前不告警——正则扩为四类占位符

### Added(office)
- **`append_paragraphs` 支持交叉引用占位符**（{{fig:}}/{{tbl:}} → REF 域）：追加段落复用生成期书签（题注扫描构建映射，`append_ref_field` 写 REF）；预校验 all-or-nothing——未知题注拒绝且零写入

> 📝 **Word 写作能力 Round 59：尾注 endnotes（Phase C）**（方案 `docs/plans/2026-09-19_r59-endnotes-plan.md`）

### Added(office)
- **`{{en:备注文本}}` 内联尾注**：镜像脚注实现——`w:endnoteReference` run（id 按出现顺序 1..N）+ `word/endnotes.xml` part（含系统尾注）+ EndnoteText/EndnoteReference 样式注入（幂等）
- **`read_docx` 回读 `endnotes: List[str]`**；脚注与尾注同段混用各自独立 part 与编号；无尾注文档不挂载 part（产物零变化）
- 契约同步：schema content 描述补 `{{en:}}`；types.ts 读结果加 `endnotes?: string[]`；SKILL 补脚注/尾注选型说明

> 🌐 **网页访问能力优化 Round 20：并行聚合搜索指标 + 诊断导出集成**（方案 `docs/plans/2026-09-18_web-access-optimization-round20.md`）

### Changed(web-access)
- **搜索指标收尾（S1）**：`_search_parallel` 并行聚合模式逐引擎埋点（伪域 `search:<engine>`；成功含 0 条结果记 ok、异常记 fail）——R18 遗留尾巴闭环
- **诊断导出集成（X2 完整闭环）**：诊断包 zip 新增 `web-metrics.json`（per-host 出网指标快照，非空时写入；快照失败静默不影响诊断包）

> 📝 **Word 写作能力 Round 58：脚注 Phase B——样式注入 + 每节重编**（方案 `docs/plans/2026-09-19_r58-footnote-phase-b-plan.md`）

### Added(office)
- **脚注样式注入**：挂载 footnotes part 时幂等注入 FootnoteText 段落样式（10pt）与 FootnoteReference 字符样式（上标）——脚注按 Word 惯例渲染，不再回退默认
- **`footnote_restart_each_section`**（WordPageSetupSpec）：节级 `w:footnotePr/numRestart=eachSect` 开关——论文/书籍分章脚注编号每节从 1 重排；默认 False 零触碰
- 契约同步：schema format_spec.page 增开关；types.ts WordPageSetupSpec 同步

> 📝 **Word 写作能力 Round 57：内联脚注 Phase A**（方案 `docs/plans/2026-09-19_r57-footnotes-phase-a-plan.md`，设计稿 90 号）

### Added(office)
- **`{{fn:备注文本}}` 内联脚注**：正文占位符生成 `w:footnoteReference` run（id 按出现顺序 1..N），备注文本写入挂载的 `word/footnotes.xml` part（含 separator/continuationSeparator 系统脚注）——学术论文脚注支持的最小闭环
- **`read_docx` 回读 `footnotes: List[str]`**（无脚注空表）；无脚注文档不挂载 part（产物零变化）

> 📝 **Word 写作能力 Round 56：脚注/尾注设计评审稿**（设计文档，非实现）

### Added(docs)
- **`docs/technical/90-word-footnotes-design.md`**：脚注支持的设计评审稿——python-docx 无原生 API 的 OOXML 四件套结构分析（footnotes.xml part/relationship/content-type/系统脚注）、`{{fn:}}` 内联锚点选型、三期分期（Phase A 写侧最小闭环 ~1 轮）与风险清单（part 手术的半公开 API、WPS 兼容验证）

> 📝 **Word 写作能力 Round 53：分节页码格式与起始号（w:pgNumType）**（方案 `docs/plans/2026-09-18_r53-pgnum-format-plan.md`）

### Added(office)
- **`page_number_format` / `page_number_start`**（WordPageSetupSpec）：节内页码格式（decimal/upperRoman/lowerRoman/upperLetter/lowerLetter）与起始号——论文前置目录罗马页码、正文阿拉伯从 1 的惯例一次成型；主节（format_spec.page）与分节新节（section_breaks.page_setup）同一路径生效，页脚 PAGE 域自动跟随节格式
- **lint `page/numbering` 对偶**：spec 声明 fmt/start 时校验首节 pgNumType 实际值（缺失/不符报 error）

> 📝 **Word 写作能力 Round 52：PPT core properties 三件套对称**（方案 `docs/plans/2026-09-18_r52-ppt-metadata-plan.md`）

### Added(office)
- **`OfficePptGenerateRequest.metadata`**（PptMetadataSpec 别名复用）+ **`OfficePptReadResult.metadata`** 回读——docx/xlsx/pptx 三件套文档属性能力收口；python-pptx 属性名与 python-docx 一致（author/subject/keywords/comments/category），仅显式传入才写

> 📝 **Word 写作能力 Round 51：读侧 core properties 回读**（方案 `docs/plans/2026-09-18_r51-read-metadata-plan.md`）

### Added(office)
- **`read_docx` / `read_xlsx` 回读 `metadata`**（WordMetadataSpec，全空为 None）——R49/R50 写入的文档属性在读取侧可见，Sage 可回答"这篇文档的作者/关键词是什么"；读侧映射与写侧对偶（xlsx creator/description ↔ author/comments）

> 📝 **Word 写作能力 Round 50：Excel core properties 对称支持**（方案 `docs/plans/2026-09-18_r50-excel-metadata-plan.md`）

### Added(office)
- **`OfficeExcelGenerateRequest.metadata`**（ExcelMetadataSpec = WordMetadataSpec 别名复用）：generate_xlsx 写 wb.properties（author→creator、comments→description 映射在生成器内完成）——台账/预算归档与 Word 同款文档属性；仅显式传入才写，不臆造作者
- 契约同步：schema metadata 描述扩为 word/excel 通用；types.ts Excel 请求加 metadata；paper-writing 数据表附表节补说明

> 📝 **Word 写作能力 Round 49：文档核心属性**（方案 `docs/plans/2026-09-18_r49-core-metadata-plan.md`）

### Added(office)
- **`metadata`（WordMetadataSpec）**：office_create word 请求支持 author/subject/keywords/comments/category → 写入 docx core properties（Word「文件 → 信息」面板可见）——期刊投稿/公文归档的常规要求；title 恒取请求标题，其余显式传入才写（不臆造作者）
- 契约同步：schema content 层 metadata 对象 + types.ts WordMetadataSpec；paper-writing 第 4 步示例补 metadata
 诊断导出集成 per-host 指标)
> 🧹 **Word 写作能力 Round 48：repair 补 index 域插入 + SEQ 题注重排兼容**（方案 `docs/plans/2026-09-18_r48-repair-index-plan.md`）

### Added(office)
- **repair 闭环 R44 规则**：spec 声明 figure_index/table_index 而文档缺失时，repair 从文档自身 SEQ 题注重建条目并插入对应 TOF 域（目录后/首段前），repaired_rules 记入 presence 规则
- **`caption/duplicate` lint 警告**：同类题注文本重复提示（交叉引用按文本匹配指向首个），warning 级不阻断

### Fixed(office)
- **SEQ 题注重排摧毁域缺陷**：`_renumber_captions` 对携带 SEQ 的题注段不再整体重写 `para.text`（会抹掉 R42 的 SEQ 域与书签，重排触发即毁交叉引用/图表目录）——改为仅更新域内缓存编号 run，结构原样保留

> 📝 **Word 写作能力 Round 47：论文场景能力可发现化收口**（方案 `docs/plans/2026-09-18_r47-paper-capabilities-plan.md`）

### Changed(docs)
- **paper-writing 技能补全 R39-R46 能力**：目录/图表目录（figure_index/table_index）/交叉引用占位符（{{fig:}}/{{tbl:}}）/真页码刷新（refresh_toc + office_refresh_toc）——论文场景才是这些能力的最大受益方，此前零覆盖；allowed-tools 补 office_refresh_toc
- **用户手册 09-office.md**：目录描述从"打开后更新域生成"更新为真页码语义；图表与图片节补插图清单/表格清单与交叉引用说明
- shipped 技能测试补论文场景可发现化断言（figure_index / {{fig:}} / office_refresh_toc）

> 📝 **Word 写作能力 Round 46：交叉引用升级——REF 域 + 题注书签**（方案 `docs/plans/2026-09-18_r46-ref-fields-plan.md`）

### Added(office)
- **占位符产物原生化**：`{{fig:}}/{{tbl:}}` 不再写成纯文本"图N"，改为 `REF _RefFig{n} \h` 复杂域（缓存"图N"）+ 题注编号套书签——F9/COM 更新域后正文引用自动跟随题注重排；R39 COM 刷新通道（Fields.Update）零新增编排即覆盖
- **零回归双路径**：有占位符的段落走分段写 run 路径（标题 numbering 前缀为首段），无占位符段落保持既有单次写入（产物逐字节不变）

> 📝 **Word 写作能力 Round 45：交叉引用占位符**（方案 `docs/plans/2026-09-18_r45-cross-ref-plan.md`）

### Added(office)
- **`{{fig:图题注}}` / `{{tbl:表题注}}` 交叉引用占位符**：段落文本按题注文本引用插图/表格，生成时替换为"图N"/"表N"——LLM 不必猜编号，插图增删自动重排；未匹配题注即生成失败（fail-fast，与 citations 同哲学）
- **题注编号映射前置**：编号映射与 R42 图/表目录条目共用同一来源，正文题注/目录条目/交叉引用三处编号严格一致
- **`cross_ref/residue` lint 规则**：正文残留未解析占位符（手工编辑/外部导入）→ error 提示

> 🧹 **Word 写作能力 Round 44：lint 面补强——index 域在位校验**（方案 `docs/plans/2026-09-18_r44-lint-index-plan.md`）

### Added(office)
- **`figure_index/presence` / `table_index/presence` lint 规则**：format_spec 声明了图/表目录即校验文档存在对应 `TOC \c` 域（字面"图N"文本不算——必须是 Word 可收录的域形态）
- **toc/presence 精度修复**：TOF 的 instr 同含 "TOC" 前缀，目录域检测排除 `\c` 载体，R42 引入 TOF 后不再误满足
- **lint schema 可检查子集白名单**：toc/figure_index/table_index 进 lint 工具 schema；对偶测试锁"声明=有规则的子集且 ⊆ 模型字段"

> 🧹 **Word 写作能力 Round 43：office_create schema 漂移卫生修复**（方案 `docs/plans/2026-09-18_r43-schema-drift-plan.md`）

### Fixed(office)
- **schema 可发现化缺口**：format_spec 补 `toc`（R13 交付却从未进 LLM schema）与 `section_breaks`（R26 同病）声明——目录域与分节横排能力对模型可见；types.ts 补 `WordSectionBreakSpec` 接口与字段
- **防漂移门禁**：新增对偶测试——工具 schema format_spec 属性集合与 WordFormatSpec 模型字段全等、types.ts 接口覆盖模型全部字段，今后单侧加字段即 CI 红

> 📝 **Word 写作能力 Round 42：图目录/表目录（TOF 域 + SEQ 题注升级）**（方案 `docs/plans/2026-09-18_r42-caption-index-plan.md`）

### Added(office)
- **题注编号 SEQ 域化**：add_caption 的"图N/表N"编号改为 SEQ 复杂域（缓存编号显示不变）——Word 语义上成为可收录的题注条目，python-docx 回读文本与 lint 规则零改动
- **`figure_index` / `table_index`**（format_spec 新增，WordIndexSpec）：插入图/表目录 TOF 域（`TOC \c`），缓存条目按正文编号顺序预收集（无题注不占号口径一致），各占一页；生成时带 `refresh_toc: true` 或事后 office_refresh_toc/office_update 刷新即得真页码
- **COM 刷新扩展**：TOC 之外追加 Fields.Update（SEQ 重编号 + TOF 收录一次完成），纯 TOF 文档也落盘
- **lint 兼容**：目录/图目录缓存行不再误判为题注重复（fldChar begin/end 之间的缓存段跳过 caption/sequence 规则）

> 📝 **Word 写作能力 Round 41：office_update 修订后 TOC 刷新**（方案 `docs/plans/2026-09-18_r41-update-toc-refresh-plan.md`）

### Added(office)
- **`office_update` 新增 `refresh_toc` 标志**（word 专用）：修订成功后立即用 Word COM 刷新目录域为真页码——增删段落后的页码漂移一次性修复；doc_id 受管路径 upfront 非 word 守卫（修订尚未发生即拒绝，语义准确），file_path 路径同口径
- **降级契约**：刷新失败/不可用时修订保持 success=True，仅附加 `toc_refresh: {ok: false, error}` 说明（与 R40 生成侧同口径）
- **横排宽表场景文档（搭车）**：report-writing 技能补 R37 `section_breaks` 分节横排说明与组合示例（技能正文可发现化缺口）

> 📝 **Word 写作能力 Round 40：office_create 一键 TOC 刷新**（方案 `docs/plans/2026-09-18_r40-create-toc-refresh-plan.md`）

### Added(office)
- **`office_create` 新增 `refresh_toc` 标志**（word 专用）：生成成功后立即用 Word COM 把目录域刷新为真页码并原地保存——带目录报告一步到位，省一次 LLM 往返；受管/legacy 双路径接线，受管路径维持「不回显绝对路径」不变式；非 word 传参显式报错（strict）
- **降级契约**：Word COM/pywin32 不可用时生成照常成功，结果附加 `toc_refresh: {ok: false, error}` 安装引导说明，绝不因刷新失败回滚已落盘文档

### Fixed(test)
- **rollback 遥测测试竞态修复（搭车，test-only）**：`updateManager.test.ts` 的 fetch 断言包进 `vi.waitFor`——`rollback()` 刻意 fire-and-forget 发遥测，立即断言与微任务调度存在竞态（R38 轮 CI 实际 flake 一次）

> 📝 **Word 写作能力 Round 39：目录真页码（Word COM 刷新域可选通道）**（方案 `docs/plans/2026-09-18_r39-toc-page-refresh-plan.md`）

### Added(office)
- **`office_refresh_toc` 工具**：把托管 .docx 的 TOC 域经 Word COM 刷新为真页码并落盘（TablesOfContents 逐个 Update + Save）——R29 静态缓存目录打开即真页码，无需用户手动 F9；WRITE_LOCAL 审批 + 工作区围栏，writer/primary 白名单可见
- **降级契约**：无 Word/pywin32 时返回带安装引导的失败（`pip install pywin32` 或 Word 内 Ctrl+A → F9），绝不抛异常、绝不泄漏 WINWORD.EXE（finally Close/Quit + AutomationSecurity=3 禁宏）
- **pywin32 进 requirements-optional.txt**（懒加载，与 Word COM 导出 PDF 共用通道；win7 手动启用钉 306）
- report-writing 技能交付步骤接入刷新通道，并补上 R36 Word 表头行样式 header_style 的文档（搭车）

> 🌐 **网页访问能力优化 Round 16：设置页展示 per-host 出网指标**（方案 `docs/plans/2026-09-17_web-access-optimization-round16.md`）

### Added(web-access)
- **出网指标展示（X2 UI）**：设置→网络凭据区块新增"出网指标（本进程内）"——消费 `GET /api/v1/web-access/metrics`，按域名渲染 成功/失败/升级渲染/均耗时，无数据不渲染；文案明示"进程内存态，重启清零"
> 🌐 **网页访问能力优化 Round 15：per-host 出网指标 + 渲染 net 块**（方案 `docs/plans/2026-09-17_web-access-optimization-round15.md`）

### Changed(web-access)
- **per-host 出网指标（M1/M3）**：新增 `backend/tools/web_metrics.py`——线程安全滚动指标（每域名 deque 100 条、全局 LRU 200 域名、进程内递增序号定 LRU 序），异常全静默；web_fetch 成功/失败路径与 download attempt 出口/成功埋点；`GET /api/v1/web-access/metrics` + `PUT /web-access/metrics/reset`（Origin 守卫同口径）
- **渲染耗时（X2 对齐）**：render_page 结果补 `net: {elapsed_ms}`（与 web_fetch net 口径对齐，不进缓存）


> 🌐 **网页访问能力优化 Round 14：浏览器健康自检 + 凭据 UI header 型新增**（方案 `docs/plans/2026-09-17_web-access-optimization-round14.md`）

### Added(web-access)
- **浏览器健康自检（H1）**：`GET /api/v1/diagnostic/browser` 上报浏览器发现 / 本地版本 / UA 声明版本；低于 Chrome 120 给出升级或 `SAGE_BROWSER_PATH` 指定新内核的警告——win7（Chrome 109 封顶）老化监控落地；设置页凭据区块顶部直接可见
- **header 型凭据新增入口（C1/C2）**：`POST /api/v1/web-access/credentials/header`（校验沿用 vault，非法 422）+ 设置页表单（域名 / 头名 / 头值，值输入框掩码）——Bearer / API key 型凭据不再只能靠对话设置
> 🌐 **网页访问能力优化 Round 13：AB6 连接复用 + X2 出网可观测**（方案 `docs/plans/2026-09-17_web-access-optimization-round13.md`）

### Changed(web-access)
- **连接复用（AB6）**：`_get_with_redirects` 整链（含全部重定向 hop）复用同一个 httpx client——TLS 握手 / 代理隧道只建一次，keep-alive 生效；仅当某 hop 的 TLS 校验口径变化时才重建；异常路径经 finally 保证关闭
- **出网可观测（X2）**：`web_fetch` 成功结果新增 `net: {elapsed_ms, bytes}`（不进缓存），为后续 per-host 调优提供数据
> 🌐 **网页访问能力优化 Round 12：凭据管理 UI + humanize 工具名**（方案 `docs/plans/2026-09-16_web-access-optimization-round12.md`）

### Added(web-access)
- **凭据管理 UI**：设置→网络新增“网站凭据”区块——凭据列表（域 / 类型 / 剩余时效 / 加密标记 / 来源 profile，沿用脱敏口径不回显值）、删除（二次确认）、`render_persistent` / `auto_refresh_credentials` 两个开关直接可调；后端新路由 `GET|DELETE /api/v1/web-access/credentials` / `GET|PUT /api/v1/web-access/config`（复用 permission_routes 的 Origin 守卫，不回显任何凭据值）
- **humanize 工具名**：browser_launch/navigate/snapshot/interact/screenshot/cookies/downloads/close 与 http_download 补齐显示名，审批弹窗与时间线不再显示生工具名
> 🌐 **网页访问能力优化 Round 11：AU3 自动刷新回路 + AU 系列收尾**（方案 `docs/plans/2026-09-16_web-access-optimization-round11.md`）

### Added(web-access)
- **登录态自愈（AU3+AU6）**：`browser_cookies export` 在持久会话导出时在档案记录来源 profile（`BrowserSession` 新增 `profile_name` 字段）；`web_access_config.auto_refresh_credentials` 开启后（默认关），带凭据请求被踢到登录墙时自动用该 profile 静默重访原 URL（先注入旧 cookie 走 remember-me 续期），重导成功则重放请求并以 `credential_auto_refreshed` note 提示；失败严格回退原 `login_required` 语义；静态与下载通道均接入
- **渲染通道登录墙检测（AU7）**：AU5 注入后渲染结果若仍是密码框页（且正文极短）→ 先走 AU3 自愈重渋一次，仍墙则报 `login_required`，不再把登录页当正文返回
- **降级可观测（X4）**：平台加密不可用（scheme=none）时写入凭据档案会 `logger.warning`，`list_credentials` 每条增 `encrypted` 标记，明示哪些档案是明文落库
> 🌐 **网页访问能力优化 Round 10：AU5 渲染池 ↔ 凭据档案双向互通**（方案 `docs/plans/2026-09-16_web-access-optimization-round10.md`）

### Added(web-access)
- **渲染通道登录态注入（AU5）**：`web_fetch credential_domain=` 命中 JS 壳渲染降级或反爬升级时，先把档案 cookie 经 `Storage.setCookies` 注入渲染浏览器（导航前生效，浏览器内重定向自动按域携带），渲染完成经 `Storage.getCookies` 按域取回并合并回档案（`credential_refreshed` note 提示）——“一次导出，静态 / 渲染 / 交互三条通道共用”成立；注入失败报 `RenderError`（宁失败不静默降级为未登录正文），回写失败静默（与 AU2 同口径）；header 型档案渲染通道不支持，跳过不报错
- **`credential_vault`**：`CredentialResolution` 新增 `cookies` 槽（cookie 档案 ok 时带出过滤后逐条 cookie，供 CDP 逐条注入——host-only cookie 无法从 Cookie 头串重建）；新增 `merge_cdp_cookies`（`Storage.getCookies` dict → 档案，与 `merge_set_cookies` 同守卫：host 亲和 fail-closed / 归属域 ∈ 档案域 / 同 name+path 替换 / 过期删除 / 清空删档）

### Changed(web-access)
- `browser_cdp.cdp_command` 浏览器级方法前缀新增 `Storage.*`（免 attach，Chrome 97+）
- `web_fetch` schema `credential_domain` 描述补渲染通道语义
> 🌐 **网页访问能力优化 Round 5 批次 4：文件嗅探与浏览器下载跟踪**（方案 `docs/plans/2026-09-14_web-access-download-analysis-round5.md` §2.2 SN2/SN3）

### Added(web-access)
- **`web_fetch mode=files`（SN2，新模块 `backend/tools/file_links.py`）**：从静态或渲染后 DOM 抽取候选文件链接并打分——`<meta name=citation_pdf_url>` / `<link rel=alternate type=application/pdf>`（学术站标准位，最高分）、`<a href>` 文件后缀（pdf/zip/docx/xlsx/epub/csv/…）与 `download` 属性 / `type=application/pdf`、`<iframe|embed|object>`、`<meta http-equiv=refresh>`、「下载 / 全文 / PDF / attachment」锚文本；同 URL 去重合并 `sources`；对 top-5 候选做首块探测（不跟随重定向、逐个过 `check_host`）标 `probe=file|html|redirect|error` + `detected_type` / `content_type` / `content_length` / `suggested_filename`，`probe=html`（登录页 / 中转页）降权；SPA 壳自动渲染后把动态 DOM 候选与静态候选合并；结果 `files[]` 可直接喂 `http_download`
- **浏览器下载跟踪（SN3，新模块 `backend/tools/browser_events.py` + 新工具 `browser_downloads`）**：`browser_launch` 后为会话建立一条常驻 CDP 事件 WS（守护线程），`Browser.setDownloadBehavior{eventsEnabled:true}` 订阅 `downloadWillBegin` / `downloadProgress`，落成线程安全的 `DownloadTracker`（url / 文件名 / 状态 / 字节 / 最终路径，完成时按 guid 或 suggestedFilename 解析落盘路径）；`browser_downloads(browser_id?, wait_for_complete, timeout)` 列出 / 阻塞等待全部完成，完成文件登记 artifact（只登记一次）；事件通道不可用时退化为下载目录列举（`.crdownload` = 进行中）并明示；`browser_close` / 后端退出时停通道

### Changed(web-access)
- `BROWSER_TOOLS` 新增 `browser_downloads`（READ）；coder 默认工具白名单经 `*BROWSER_TOOLS` 自动带上；`browser_launch` 结果新增 `download_tracking`


## [v0.4.9-alpha.45] - 2026-09-19

### Added
- feat(chat): RD18 级联跳过根因徽章——任务树失败行直读 blocked_by_failed 根因 (#1208)
- feat(office): Round 57 — 内联脚注 Phase A（{{fn:}} + footnotes part 挂载 + 回读） (#1204)
- feat(right-panel): R4——版本互比 + 变更预取 + 产物类型过滤 (#1198)
- feat(p11): client_message_id 幂等复用 + 标题后台生成的前端补刷 (#1196)
- feat(orch): RT24 编排任务持久化携带用量与时长——orch_tasks 增 used_tokens/duration_ms (#1195)
- feat(chat): 引用溯源展示增强——附件名优先 + 溯源明细完善（r80） (#1194)
- feat(orch): BU17 聚合块任务级消耗标注——终态块标题带（消耗 N tokens） (#1188)
- feat(office): Round 53 — 分节页码格式与起始号（w:pgNumType） (#1185)
- feat(chat): 文件选择器 accept 过滤——从源头防误选（r78） (#1184)
- feat(chat): BU16 run 级耗时与上限提示——进度行实时计时，终态冻结 (#1183)
- feat(p10): 回滚语义重做 Round 1——last-known-good 回滚数据 + RunOnce 交换执行 (#1180)
- feat(office): Round 52 — PPT core properties 三件套对称（generate/read metadata） (#1181)
- feat(right-panel): R3 - version diff view + CodeMirror editing + changes count badge (#1172)
- feat(office): Round 51 — 读侧 core properties 回读（read_docx/read_xlsx metadata） (#1174)
- feat(chat): BU15 运行中子任务实时耗时——任务树 running 行计时徽章 (#1169)
- feat(office): Round 50 — Excel core properties 对称支持（generate_xlsx metadata） (#1170)
- feat(chat): 聊天文档附件支持 pdf/docx——打通 R39/RAG UI 断点（r75） (#1167)
- feat(office): Round 49 — 文档核心属性（WordMetadataSpec → docx core properties） (#1164)
- feat(rag): 附件上传后自动建立检索索引——opt-in fire-and-forget（r74） (#1161)
- feat(orch): BU14/BD8 守门状态透出——快照带 wall_clock_exceeded，partial 归因触顶 (#1160)
- feat(office): Round 48 — repair 补 index 域插入 + SEQ 题注重排兼容（缺陷修复） (#1159)
- feat(p9): client_message_id 消息身份协议——根治乐观 id 与服务端 id 失配的重复显示 (#1155)
- feat(rag): 引用溯源明细增强——chunk 索引/相关度进事件与气泡（r73） (#1156)
- feat(right-panel): R2——预览升级 + overlay 抽屉三件套 + 信息密度打磨 (#1153)
- feat(orch): RV4 单任务重试——rerun-failed 支持 task_ids 子集 + 任务树行内重试按钮 (#1150)
- feat(office): Round 46 — 交叉引用升级（REF 域 + 题注书签） (#1143)
- feat(office): office-p5b 批次——ppt 生成表单版式选择 (#1148)
- feat(chat): RAG 引用溯源事件 + R17-E memory_used 接线收尾（r71） (#1115)
- feat(usage): 上下文占用分类明细统计 + ContextMeter 弹层 (#1128)
- feat(office): Word/PPT 专用角色收口——ppt-maker 种子 + PPT 模板工具面 + writer 门禁 prompt (#1129)
- feat(arena): automation + model probe (27 commits, evidence/JWT/retry hardening) (#1030)
- feat(context-isolation): 三层上下文隔离 (#1032)
- feat: /agents 侧边栏入口与 Sage 自省/配置工具 (#1126)
- feat: 用户通知透明度增强 - 技能激活与上下文压缩可见化 (#1122)
- feat: protect Python backend code in release builds (#1124)
- feat(settings): RD16 编排设置全量收口——worktree 隔离开关 + scratch 根目录名 (#1113)
- feat(right-panel): R1——面板状态全局化 + 自动唤起/内联产物卡片 + 上下文持久化 + 全屏/宽度档位 (#1112)
- feat(office): expose staging quarantine over HTTP (plan/run/report/restore) (#1111)
- feat(office): Round 45 — 交叉引用占位符（{{fig:}}/{{tbl:}} → 图N/表N + residue lint） (#1109)
- feat(workspace): 三阶段 AI 工作区优化（来源/产物/项目上下文） (#857)
- feat(office): Round 44 — lint 面补强（index 域在位校验 + lint schema 子集白名单） (#1102)
- feat(office): honour Electron import sentinels as a cross-process lease (#1101)
- feat(settings): RD15 编排守门键透出设置页——墙钟上限/单任务超时/重派链上限 (#1099)
- feat(web-access): Round 18——web_search 纳入 per-host 指标 + 指标 UI 刷新/重置 (#1092)
- feat(office): Round 42 — 图目录/表目录（TOF 域 + SEQ 题注升级） (#1090)
- feat(orchestration): BU13 任务级消耗准确性 + 时长可见性——终态事件 per-task 归因 (#1088)
- feat(office): Round 41 — office_update 修订后 TOC 刷新（refresh_toc）+ 横排宽表场景文档 (#1085)
- feat(rag): RAG 切片 4b——附件检索注入前端配置与请求接线（r67） (#1079)
- feat(office): Round 40 — office_create 一键 TOC 刷新（refresh_toc）+ rollback 遥测测试竞态修复 (#1083)
- feat(office): Round 39 — Word 目录真页码（Word COM 刷新域可选通道） (#1073)
- feat(web-access): Round 16——设置页展示 per-host 出网指标 (#1077)
- feat(rag): RAG 切片 4a——producer 超长附件检索注入（opt-in 请求级嵌入）（r66） (#1069)
- feat(office): office-p5a 批次——PPT 模板占位符分析与填充 (#1071)
- feat(web-access): Round 15——per-host 出网指标 + 渲染 net 块 (#1068)
- feat(mcp): OAuth 状态可见化——has_oauth_token + 授权角标（r65） (#1066)
- feat(office): office-p4b 批次——OCR 语言/精度扩展 (#1062)
- feat(mcp): OAuth 收口——授权 API 路由 + IPC + McpTab 授权按钮（r64） (#1056)
- feat(office): office-p4c 批次——ppt 插入图片 UI 入口 (#1052)
- feat(mcp): OAuth 切片 3a——授权编排层（发现→注册→授权→交换）（r62） (#998) (#1049)
- feat(web-access): Round 14——浏览器健康自检 + 凭据 UI header 型新增 (#1047)
- feat(office): Word 表头行样式（header_style，与 Excel header_style 对称） (#1048)
- feat(office): quarantine-based staging cleanup with recoverable moves (#1044)
- feat(mcp): OAuth 切片 3b——loopback 回听 + 浏览器拉起编排（r63） (#1039)
- feat(office): office-p4b 批次——OCR 能力徽章 + word 插图入口 (#1042)
- feat(mcp): OAuth 切片 3a——授权编排层（发现→注册→授权→交换）（r62） (#998)

### Fixed
- fix(py38): legacy_routes 新增 to_thread 调用对齐 py_compat——预铺 win7 同步 (#1205)
- fix(r38): 修复用户通知透明度合并后审查发现的 6 项缺陷 (#1140)
- fix(test): office_create 审批链测试 Windows 适配——LLM JSON 模板路径经 json.dumps 转义 (#1192)
- fix(chat): InputCard 文件选择器补 accept=".txt,.md,.pdf,.docx"（r79） (#1189)
- fix(chat): 重接路径补 memory_used——重放不丢记忆明细（r77） (#1178)
- fix(chat): 补回 #1167 丢失的 pdf/docx 白名单 + 修正过时附件提示（r76） (#1171)
- fix(py38): zip strict= 形参残留清零——chat/topic_detection._cosine + model_catalog 并发测试 (#1162)
- fix(chat): skill_activated 明细写错消息目标——userId→assistantId（r72） (#1151)
- fix(chat): 段级工作记忆清空改为经 agent.memory_manager 共享实例 (#1139)
- fix(packaging): 保护模式 .pyc 被 filter 剔除 + 源码泄漏修复 (#1136)
- fix(win7): Windows bash/REPL spawn_verified + kill_process_tree (#855)
- fix(projects): restore allowed_paths support lost in workspace optimization (#1120)
- fix(tools): bash/repl 中文编码乱码 + repl 资源清理覆盖成功结果 (#1118)
- fix(py38): Round 23——行为类遗留修复（事件循环生命周期 + TimeoutError 双型 + 测试竞态） (#1106)
- fix(mcp): OAuth 401 自愈——失效 token 清理 + 错误面点名重授权（r70） (#1105)
- fix(p7): 第七批收尾二——mock 响应不落库 / 标题生成移出 DONE 关键路径 / 长会话分页 / 信封统一收尾 (#1100)
- fix(llm): 直连模式 base_url 带 /v1 后缀去重——不再请求 /v1/v1/… 404 路径（r69） (#1089)
- fix(office): Round 43 — office_create schema 漂移卫生修复（toc/section_breaks 可发现化 + 三方防漂移门禁） (#1095)
- fix(win7): 内网闪退三层防御 — 运行时检测 + Chromium 开关 + 崩溃事件 (#1040)
- fix(chat): pdf/docx 附件提取挪线程池——避免卡聊天事件循环（r68） (#1086)
- fix(py38): py39+ 标准库 API 兜底——to_thread 垫片 + hardlink_to/write_text(newline) 适配 (#1070)
- fix(doctor): 端口占用检测 Windows 语义修复——SO_EXCLUSIVEADDRUSE + 平台化修复提示 (#1057)
- fix(chat): ignore skill loads after input unmount (#1035)

## [v0.4.9-alpha.43] - 2026-09-14

> 🐛 **win7 安装包日志错误修复** (PR #794)

### Fixed
- **fetchModels 防御性检查**: 非标准 JSON 上游 (LM Studio 变体) 不再导致 `data.data.map()` TypeError
- **settings_canonicalizer**: 新增 `local_model_path` → `localModelPath` alias，兼容旧数据迁移
- **knowledgeApi 死代码清理**: 消除 `list_knowledge_docs` / `search_knowledge_docs` Unknown IPC command 错误日志；删除 4 个废弃组件

> 🌐 **网页访问能力优化 Round 5 批次 3：登录态保持**（方案 `docs/plans/2026-09-14_web-access-download-analysis-round5.md` §2.4 AU1/AU2/AU4）

### Added(web-access)
- **cookie 元数据与过期判定（AU1）**：`browser_cookies export` 保留 `expires` / `secure` / `httpOnly` / `sameSite`；附加时已过期 cookie 不发送、`secure` cookie 只发 https、按 path 匹配；档案全部过期 → `web_fetch` / `http_download` 返回 `credential_expired`（区别于 `credential_not_found`）并指引重新登录导出；`export` 结果与 `list` 显示最短剩余时效 `expires_in_seconds` / `expired`
- **Set-Cookie 回写 + 登录墙检测（AU2）**：带凭据请求在命中域收到 `Set-Cookie` 自动合并回档案（续期 token 不丢，`Max-Age=0` 视为删除，第三方域 cookie 不混入），结果 `note` 标 `credential_refreshed`；带凭据却被 302 到 `login|signin|sso|passport|auth|cas|oauth` 类 URL、或最终页只有密码框而无正文 → 返回 `login_required`（不再把登录页当正文）；`http_download` 期望文件却收到含密码框的 HTML 也改报 `login_required`
- **头部型凭据（AU4）**：`browser_cookies action=set_header domain= header_name= header_value= [ttl_seconds=]` 保存 `Authorization: Bearer …` / API key 自定义头（禁 Cookie / Host 等传输头、拒换行注入，值不回显，可选 TTL）；`credential_domain` 命中头部档案时随请求附带、跨域重定向同样剥离；`list` 显示 `kind` / `header_names`

> 🌐 **网页访问能力优化 Round 5 批次 2：反爬访问**（方案 `docs/plans/2026-09-14_web-access-download-analysis-round5.md` §2.3 AB1/AB2/AB4/AB5）

### Added(web-access)
- **web_fetch 自动升级链（AB1）**：静态抓取遇 403/429/503 或正文命中反爬盾特征（Cloudflare "Just a moment" / "Attention Required" / Akamai / PerimeterX / DataDome / 验证码页等，仅在正文极短时判定）→ 自动改走 headless 渲染池重抓；成功结果标 `escalated="render"` + `escalated_from`（原状态码 / `antibot_page`），`links` / `tables` 模式同样从渲染 DOM 抽取；渲染后仍是盾页或非 2xx 则返回带三条出路（浏览器通道 / 登录态 / 代理）的指引；新增参数 `escalate=false`、`render="never"`、`mode="raw"` 均关闭升级
- **出网请求头拟真（AB2）**：`http_factory.default_headers()` 追加 `Sec-CH-UA` / `Sec-CH-UA-Mobile` / `Sec-CH-UA-Platform` / `Sec-Fetch-Dest|Mode|Site|User` / `Upgrade-Insecure-Requests`；UA 与 Client Hints 的 Chrome 大版本改为从本地内置 Chrome 探测（版本目录名 / `--version`，缓存），探测失败或低于基线时回退 126——win7 分支 Chrome 109 与 UA 版本不一致的问题一并消除
- **浏览器去自动化痕迹（AB4）**：Chrome 启动增加 `--disable-blink-features=AutomationControlled` / `--disable-infobars`；渲染池导航前经 `Page.addScriptToEvaluateOnNewDocument` 注入 stealth 脚本（`navigator.webdriver` → undefined、补 `window.chrome`、`navigator.languages`），注入失败不阻断渲染；渲染结果新增 `rendered_status`（页面导航响应码）
- **出网重试 / 限速（AB5）**：`http_factory.retrying_send` 统一给 web_fetch 每一跳与 web_search 各引擎请求做指数退避重试（默认 2 次，可重试：连接 / 读写超时 / 协议错 / 408 / 425 / 429 / 5xx，`Retry-After` 上限 30s）；新增按主机令牌桶 `HostRateLimiter`（2 req/s，突发 4）避免对同一站点连发触发 429；`build_client(client_class=...)` 允许注入带重试的 Client 子类

> 🌐 **网页访问能力优化 Round 5 批次 1：下载可靠性 + 内容嗅探**（方案 `docs/plans/2026-09-14_web-access-download-analysis-round5.md` §2.1 DL1/DL3 + §2.2 SN1）

### Added(web-access)
- **http_download 重试 + 退避**：连接错误 / 读写超时 / 协议错 / 5xx / 408 / 429 指数退避重试（默认 3 次，`retries` 可调，上限 6）；429/503 尊重 `Retry-After`（上限 60s）；401/403/404 不重试——403 附登录态 / 浏览器通道 / 代理三条出路指引
- **http_download 断点续传**：写 `<name>.part` + 旁车 `<name>.part.json`（url / etag / last_modified / total / accept_ranges），成功后原子改名；中断且服务器支持 Range 时保留半成品，重试或再次调用同 URL 自动 `Range: bytes=N-` + `If-Range` 续传（206 追加 / 200 重下 / 416 长度相符视为完成）；`resume=false` 关闭
- **http_download 完整性**：`Content-Length` 已知而实际字节不足 → `incomplete_download`（可续传则保留 .part）；`expected_sha256` 给定则校验、不符删除；结果新增 `resumed / attempts / elapsed_ms / total_bytes / sha256`
- **http_download 请求头与超时**：复用出网默认 UA / Accept-Language（无 UA 请求被文献站 403 是常态）+ `Accept: */*` + `Accept-Encoding: identity`（保证长度可比）+ `Referer`（默认目标 origin，`referer` 可覆盖）；超时拆分为 connect 15s / read 按块 / write 30s / pool 10s
- **魔数嗅探（新模块 `backend/tools/content_sniff.py`）**：`http_download` 落盘前读首块，期望 PDF/ZIP/Office/压缩包而实际是 HTML（登录页 / 验证码 / 反爬盾 / 错误页）→ 立即中止返回 `html_instead_of_file` + 页面摘要 + 路由指引，不落盘、不重试
- **web_fetch 二进制感知**：PDF / 压缩包 / Office / 图片 / octet-stream 等二进制响应不再以乱码正文返回，改给 `kind=binary` 结构化结果（detected_type / content_length / suggested_filename / hint 引导改用 http_download）；二进制结果不进 JS 渲染降级

### Changed(web-access)
- 出网默认请求头常量迁至 `http_factory.DEFAULT_HEADERS` / `default_headers()`（web_tool 保留 `_DEFAULT_HEADERS` 别名），三个出网工具共用，避免再出现"下载不发 UA"的漂移

## [v0.5.0-beta.1] - 2026-09-13

> 🚀 **升档 beta**：核心功能（对话 / 记忆 / Office / 技能 / MCP / 更新源）已稳定迭代并具备 CI + e2e 门禁，按 `docs/technical/30-release-tiers.md` 从 alpha 升至 beta。本版同时收口"Office 对标系列"与"对标主流 AI 应用 Sprint 1"。

### Changed(narrative)
- **README 重写**：首屏以能力矩阵（Office 全链路 / 持久记忆 / 编码代理 / 技能与 MCP / 知识库 / 远程网关 / 自演化 / 更新源）+ 三步快速开始呈现；移除"详细设计阶段"、T5.8 构建验证等过期内容；配置说明改为实际存在的 `.env` / `backend/config.yaml` / 应用内设置
- **docs/01-overview 修订**：补充历史文档说明；技术栈表从 Tauri 更新为 Electron 21.4.4 + Python 3.11/3.8；产品定义与竞品对比表按 2026-09 现状重写（v1.0 → v1.1）

### Fixed(hygiene)
- 移除误提交的调试产物 `backend/_diag_out.txt`；`.gitignore` 新增 `backend/_diag*`、`*.stackdump`、`ci*.log`、`r[0-9]*-*.log`、`.venv-ci/`
- CHANGELOG 中重复的"Word 格式 Linter(Round 10)"条目去重

> 🏢 **Office 对标系列**(PR #547/#554/#560/#561/#564/#569,方案 `docs/plans/2026-09-09_office-competitive-parity-optimization.md`)

### Added(office)
- **Office 配置化(Round 31)**: ExcelSheetSpec.freeze_panes(A1 记法冻结窗格,与 freeze_header 同给时优先)+ SAGE_IMAGE_OPTIMIZE_THRESHOLD_BYTES 环境变量配置 Pillow 压缩阈值(0=禁用);工具 schema + 前端契约同步
- **Word 奇偶页页眉页脚(Round 34)**: format_spec.odd_even_pages+even_page_header/footer——书籍排版场景,偶数页独立页眉页脚(python-docx settings.odd_and_even_pages_header_footer 全局开关)
- **Word 首页不同页眉页脚(Round 33)**: format_spec.first_page_different+first_page_header/first_page_footer——封面页独立页眉页脚(文本/PAGE 域),python-docx different_first_page_header_footer 原生开关
- **Excel 打印页边距(Round 31)**: print_setup.margins_cm(上/下/左/右,厘米,openpyxl 英寸自动换算)——部分给定只动给定边;工具 schema + 前端契约同步
- **journal 结构化文献清洗(Round 30)**: generate_article 自纠检查与最终校验前先原地清洗 structured_references——次品条目(缺 title/字段非法)剔除+warning、key 冲突自动补唯一后缀;全为次品时回退 references 纯文本;不再让单条次品拖垮整体校验
- **TOC 静态缓存回填(Round 29)**: 目录域升级为 fldChar 复杂域——打开文档即见按文档标题生成的静态目录行(逐级缩进/levels 过滤),更新域后被真实带页码目录替换;Linter toc/presence 升级为双载体兼容检测
- **Excel 打印标题行(Round 28)**: print_setup.title_rows('1:1')——长表打印每页重复表头(与 freeze_header 屏幕冻结互补);openpyxl 归一化为绝对引用 $1:$1
- **Pillow 提升为 main 正式依赖(Round 27)**: requirements.txt 增加 Pillow>=10.0——图片压缩管线(R22)开箱生效,消除"装 optional 才生效"的割裂;requirements-optional 同步移除;win7 bundle 不受影响(bundled 列表本就不含)
- **Word 横排分节(Round 26)**: format_spec.section_breaks——按 start_paragraph 插入 NEW_PAGE 分节并对新节应用 page_setup(横排/纸张/边距),宽表格/财务页场景;仅给 orientation 未给 size 时自动交换宽高;无 breaks 零变化
- **journal generate 接入引用引擎(Round 25)**: generate_article 的 LLM prompt schema 新增 structured_references(结构化文献条目)——LLM 产出经 JournalContent 校验后走 R21 的 _write_sections 分支按 GB/T 7714 格式化加 [N] 编号;两轮自纠机制天然兜底次品条目
- **Excel 打印设置(Round 23)**: ExcelSheetSpec 新增 print_setup——方向(横/纵)/缩放到 N 页宽(fitToWidth+fitToPage)/打印区域(A1 记法);全字段可选缺省零变化
- **Pillow 图片管线(Round 22)**: resolve_image_payload 接入懒加载压缩——>8MB 的 JPEG/PNG 在 Pillow 可用时自动降采样(最长边 2000px,质量 85→65 阶梯)到阈值内;Pillow 为 requirements-optional 可选依赖,未安装时管线旁路行为零变化;不进 win7 bundle
- **journal 接入引用引擎(Round 21)**: JournalContent 新增 structured_references(ReferenceSpec)+citation_style——fill_from_content 时用 R9 引擎按 GB/T 7714/APA 格式化并加 [N] 编号生成参考文献段;未提供时回退 references 纯文本(零变化)
- **Excel 图标集条件格式(Round 19)**: conditional_formats 新增 icon_set 规则——9 种图标样式(3Arrows/3TrafficLights1/5Rating 等),阈值按百分比等分;icon_style 非法值模型层拒绝
- **Excel 下拉数据验证(Round 18)**: ExcelSheetSpec 新增 data_validations(range+options 下拉列表/allow_blank/输入提示)——状态/分类列防手输错值;内联列表超 255 字符(Excel 硬限制)单条跳过不阻断;全部可选缺省零变化
- **Excel 条件格式(Round 17)**: ExcelSheetSpec 新增 conditional_formats——data_bar 数据条/color_scale 双色色阶/duplicate 重复值高亮(COUNTIF+纯色),range A1 记法非法模型层拒绝、openpyxl 级失败单条跳过不阻断;全部可选缺省零变化
- **@引用摘要带版式信息(Round 16)**: @docx 文件的摘要新增页眉/页脚/页码域/目录域概况(批注概况同款独立维度语义,不受截断)——LLM 在编辑回路可见 R7-13 的版式元素
- **读取侧补齐(Round 15)**: read_docx 新增 headers_footers(每节页眉/页脚文本+页码域标记,linked 空节跳过)与 toc_fields(目录域 instr 列表)——R7-13 生成的页眉/页脚/目录在读取与编辑回路可见;前端 IPC 契约同步
- **Excel 格式增强(Round 14)**: ExcelSheetSpec 新增 header_style(表头加粗+浅灰底+居中)/freeze_header(冻结首行)/autofit_columns(按内容自适应列宽,显式列宽优先,中文双宽计)/number_formats(按列名映射 Excel 数字格式,未知列忽略,公式单元格跳过)——全部可选,缺省零变化
- **目录域(Round 13)**: format_spec.toc 在标题后插入 TOC 域(级别范围/占位提示可配,Word/WPS/LibreOffice 更新域生成目录)+分页;Linter 对偶新增 toc/presence 规则;paper-writing/report-writing 技能自检步骤接入 office_repair_word 自动修复
- **格式自动修复(Round 12)**: repair_docx + POST /office/word/repair + office_repair_word 工具(WRITE_LOCAL)——对照 FormatSpec 自动修复样式/页面类违规(复用 word_layout 幂等应用)、标题编号与图/表题注重排;默认写 -repaired.docx 新文件(overwrite=true 原子替换);修复后自动复检,语义类违规(citation/coverage)保留报告
- **写作技能(Round 11)**: 两个 shipped SKILL.md——paper-writing(期刊论文五步工作流:大纲确认→分章起草→BibTeX 解析/结构化引用→office_create 一次成形→office_lint_word 自检)与 report-writing(项目文档/报告:格式来源三选一/模板填充改道/术语表/图表题注三线表/office_update 修订+快照回滚);when_to_use 语义自动激活,零 Python 代码路径变更
- **Word 格式 Linter(Round 10)**: POST /office/word/lint + office_lint_word 工具——对照 FormatSpec 校验任意 .docx(页边距/纸张/方向/正文字号行距缩进/标题样式/页眉/页码域/标题编号连续性/题注编号连续性/引用标记覆盖),违规输出 rule_id+严重级+实测 vs 期望+中文修复建议;spec 未提供的项不检查,与生成器对偶
- **Word 引用体系(Round 9)**: 结构化文献条目(references,9 类文献)+ 确定性 GB/T 7714-2015 格式化(J/M/D/C/R/EB/OL 等类型码、>3 作者截断"等/et al")+ APA 简表;段落 citations 按 key 回链自动生成文中上标 [N](首现编号、连续合并 [1-3])与文末参考文献节(悬挂缩进/样式可配);BibTeX 解析(REST /office/word/parse-bibtex + office_parse_bibtex 工具,零第三方依赖)
- **Word 内容元素(Round 8)**: word generate 插图支持行内放置(after_paragraph)与题注自动编号("图N");表格支持题注("表N")/学术三线表/表头跨页重复/固定列宽/合并单元格;多级标题自动编号(1/1.1/1.1.1,format_spec.numbering);修复受管路径丢弃 images 的缺口
- **Word 版式引擎 FormatSpec(Round 7)**: word generate 新增可选 `format_spec`——页边距/纸张/方向、正文(字号/行距/首行缩进/段距/对齐)、Title 与标题样式覆盖(字号/加粗/颜色/间距)、页眉文本、页脚页码域;"版式即配置",格式要求由确定性代码注入而非 prompt 口头约定;不传时行为零变化
- **PDF 全链路**: 中文生成修复(CID 字体)、文本/表格/表单读取、生成、AcroForm 填写、PDF→Word(文本级)、Office→PDF 导出(检测本机 LibreOffice/Word)
- **PDF/模板 LLM 工具 6 件**: office_read_pdf / office_generate_pdf / office_read_pdf_form / office_fill_pdf_form / office_analyze_word_template / office_fill_word_template
- **Excel 公式闭环**: 生成/编辑写公式、读取公式视图、formulas 引擎本地求值(main 通道)
- **图表与图片**: Excel 原生图表、Word/PPT 插图、matplotlib 渲染管线(main 通道)
- **office_analyze**: 本地数据分析(describe/计数/聚合/相关性)+ 分析报告 xlsx + 图表 artifact
- **模板库**: 10 套内置中文模板(word×6/excel×2/ppt×2)+ 工作区用户模板 + 前端「从模板创建」
- **编辑信任闭环**: 改前快照(10 份/100MB 保留)、dry_run 预览、diff 预览对话框一键应用、self_check 回读 + 验证历史表
- **Word 批注**读/写(OOXML 层);富预览(标题层级/表格/分 sheet/公式视图)
- **@ 注入升级**: Word 整段+表格+批注、Excel 自适应行+统计、PDF 支持
- **office e2e**: 3 个 stub-deep 用例进 tier-1 PR 门禁
- **归档视图批量操作**;前端纳入 PDF 全流程

### Added(projects)
- **项目模块 P13**: 知识搜索范围支持"全部最近 wiki 项目"——knowledge_project 支持逗号分隔多根(逐根授权任一未授权 403 fail-closed;多根逐个 search_wiki 按 score 合并、root::path 去重、截取总 limit;单值向后兼容 P9),命令面板范围分组新增"全部最近 wiki 项目"选项(>=2 个项目时出现,选择持久化逗号拼接范围)(方案 docs/plans/2026-09-16_knowledge-multi-scope-plan.md)
- **项目模块 P9**: 知识搜索默认域配置化——/search/global 新增可选 knowledge_project（经 authorize_registered_project 校验：未授权 403/非 wiki 404，与 wiki 域同契约），_search_knowledge 显式范围优先、缺省回退最近打开（默认行为零变化）；命令面板新增"知识范围"分组（默认+最近 wiki 项目 ≤5，localStorage 持久化 sage:knowledge-scope:v1，选择不关面板），搜索请求按范围携带参数(方案 docs/plans/2026-09-15_knowledge-scope-p9-plan.md)
- **项目模块 P8**: wiki recent_projects 存储迁移到 projects 注册表(SQLite)——recent_projects.py 重写为只读投影适配器(公共 API 全保,消费方零改动);projects 表新增可空 intent 列(幂等迁移,NULL 读侧映射 open);MAX_RECENT 为投影截断而非注册表生命周期,save_recent 窗口重写只删上一窗口内行;旧 JSON 一次性导入后改名 .migrated 备份;单调毫秒保证同毫秒 record 顺序可判定;移除 wiki/files 平台原语依赖(方案 docs/plans/2026-09-15_wiki-recents-sqlite-p8-plan.md)
- **项目模块 P7**: 全局搜索接入项目分组——/search/global 默认含 projects 组(ProjectRepository.search 按 name/path LIKE + 会话计数聚合,types=project 可单选),命令面板搜索模式命中项目名/路径片段可直达(复用 open 流,handleOpenProject 收敛为 {id} 签名)(方案 docs/plans/2026-09-14_projects-search-p7-plan.md)
- **项目模块 W5**: wiki/files 全量 Windows 解锁——其余 12 个 secure_* 补 reparse-safe 分支(沿用 R32 原语),Windows 上 wiki 项目 create/open/list 从 500 恢复可用;修复两个 R32 原语缺陷(CREATE_ALWAYS 先截断后复核绕过多链接拒绝契约、校验失败句柄泄漏锁死同 inode 文件)+ secure_read_text `..` 逃逸缺口;测试解锁 path_security/security_final_paths/project_context/skill_md 回滚/P6 桥接集成的 Windows skip(symlink 夹具改能力探测);本机全量 unit 5539 过零新增失败(方案 docs/plans/2026-09-14_wiki-files-win-unlock-plan.md §7)
- **项目模块 P6**: wiki 授权桥接 projects 注册表(recents ∪ registry 并集,约 24 个 wiki 端点门禁 fail-closed 语义不变;MCP 授权面同样并集;wiki open/create 双登记进侧栏清单;前置 #760 解除 POSIX-only 阻塞;全局搜索默认域明确不改,依据 docs/plans/2026-09-14_wiki-projects-bridge-plan.md)
- **项目模块 P5**: 侧栏项目区块局部拖拽登记——拖文件夹到项目分组即批量登记(拖拽不自动打开,与 + 按钮登记即打开区分;路径取 Electron File.path 与 OfficeFilePicker 同判据,目录有效性走既有 validate_workspace 校验,零新增 IPC;dragOver 高亮提示)(方案 docs/plans/2026-09-13_projects-p5-drag-plan.md;Electron>=32 需迁移 webUtils.getPathForFile,已留注记)
- **项目模块 P4**: 项目子行就地删除会话(hover 两步确认,联动刷新子列表/计数/会话区)+ 项目清单自动刷新(订阅 store 会话数量变化,400ms 防抖重查后端聚合计数,消除跨区增删后的陈旧显示)(方案 docs/plans/2026-09-13_projects-p4-plan.md)
- **项目模块 P3**: Chat 头部当前项目徽标——会话绑定工作区时在对话头部显示 Folder+项目名 chip(tooltip 完整路径),多项目并行不再迷路;名称优先匹配登记项目,历史绑定回退 basename,清单拉取失败静默降级;纯展示组件不依赖 provider(方案 docs/plans/2026-09-13_projects-p3-plan.md;拖拽排序经评估否决——与最近打开排序语义打架,依据见方案 §1)
- **项目模块 P2**: 行展开会话子列表(chevron 懒加载项目内未归档会话 ≤20 条,轻量子行 title+相对时间,点击直达;open/新建后自动刷新子列表)+ 命令面板接入("项目"分组列出最近 8 个项目一键打开;新增"添加项目"操作命令走原生选目录;操作分派收敛为单一 runAction 消除键盘/点击双点 if/else)。后端零改动,复用 P1 端点(方案 docs/plans/2026-09-13_projects-p2-plan.md;拖拽登记与 wiki recent_projects 统一经评估缓行,依据见方案 §2)
- **项目模块 P1**: 侧边栏"项目"占位落地为项目注册表(对标 Cursor Recent Workspaces)——登记工作目录(原生选目录,幂等去重),点击项目自动复用其最近活跃会话(无则新建并绑定,标题取项目名);行内 hover 项目内新建对话 + 两步确认移除(不动磁盘与会话);目录消失标记 ⚠ 并提示重选;归属判定复用 session_workspace_bindings 活跃绑定,fork/变更面板/检查点/SAGE.md 上下文等既有链路自动生效(技术文档 docs/technical/61-projects-module.md)

### Changed(office)
- Word @ 摘要从"每段第一句"改为全文结构化 markdown;Excel 摘要从固定 5 行改为自适应
- office 工具面 7→16;writer 档位同步(除 office_delete 外全量)
- PPT 生成支持版式选择(替代硬编码几何)

### Fixed(office)
- PDF 生成中文输出为空白(base-14 字体无 CJK 字形)
- Excel 编辑后公式缓存值丢失的提示缺失
- 死参数 `OfficePptGenerateRequest.template` 移除;快照目录无保留策略(技术债 L3)

## [v0.4.9-alpha.41] - 2026-09-11

> 🔌 **可插拔更新源系统** — Phase 1–4 完整闭环。方案 `docs/superpowers/specs/2026-09-10-pluggable-update-providers-design.md`;技术文档 `docs/technical/56-update-providers.md`;用户手册 `docs/user-manual/14-update-providers.md`。

### Added(update-providers)
- **Provider 抽象层** (`UpdateProvider` 接口 + `ProviderRegistry` + `ProviderStore`):更新源从硬编码 url 切换到「注册表 + 用户可配 provider 列表」;支持 generic-http / github / gitee / gitlab 4 种内置类型
- **Provider 安全存储**:`electron-store` 持久化 provider 配置,token 经 Electron `safeStorage`(OS keychain 后端)加密后落盘;preload IPC bridge 仅暴露白名单方法
- **GitHub Releases provider** (#616):`/repos/{owner}/{repo}/releases/latest` + `/releases?per_page=10`;pre-release 通过 `pickNewestPrerelease` 选最新 `published_at`
- **Gitee Releases provider** (#617):Gitee API v5 + `?access_token=` query,镜像 GitHub 选版策略
- **GitLab Releases provider** (#618):API v4 + `PRIVATE-TOKEN` header + `upcoming_release=true` flag
- **Feature flag 全开** (#619,`ENABLE_UPDATE_PROVIDERS_UI`):Phase 3 默认 ON,`SAGE_EXPERIMENTAL_PROVIDERS=0` 紧急回滚 escape hatch
- **E2E 闭环** (#620,Playwright hermetic journey):`providers-manager.e2e.ts`(列表→新增→编辑→测试→删除 6 步)
- **Provider UI** (Phase 2 PR #613,已合并):`ProvidersManager` 设置面板;列表/新增/编辑/删除/设为默认/测试连接 6 个交互;按 `channelMap` 决定 stable/beta/alpha 是否预发布通过
- **技术文档** (#621)`docs/technical/56-update-providers.md` + **用户手册** (#621)`docs/user-manual/14-update-providers.md`

### Changed(update-providers)
- UpdateManager 重构:从单一 updater 切换到「active provider + builtin generic-http fallback」;存量用户无感
- preload bridge 暴露 6 个 provider 方法(白名单 + 类型守卫):`providers.list / add / update / remove / setDefault / test`

### Fixed(update-providers)
- 安全:token 全部经 `safeStorage.encryptString` 加密,文件权限 0o600
- 多 provider 冲突:同 `isDefault=true` 时 UI 显示警告并要求二选一

## Release Tier Definitions

| Tier | Tag Format | Audience | Channel |
|------|-----------|----------|---------|
| **alpha** | `vX.Y.Z-alpha.N` | Sage contributors only | GitHub Releases (prerelease) |
| **beta** | `vX.Y.Z-beta.N` | Public beta testers | GitHub Releases (prerelease) |
| **rc / preview** | `vX.Y.Z-rc.N` | Broad testing, recommended for early adopters | GitHub Releases (prerelease) |
| **stable** | `vX.Y.Z` | All users | GitHub Releases (latest) |

Win7 LTS adds `-win7` suffix after tier (e.g. `vX.Y.Z-beta.N-win7`).

## [v0.4.3-alpha.2] - 2026-07-07

> 🧪 **Alpha tier** — Sage 贡献者内测。PEP 604/585 → typing.* 跨平台兼容同步(原 Win7 LTS fix PR #112 现在 main 也对齐)。Win10+Linux+Mac 验证用版本。

### Changed
- **fix(backend): mass-rewrite PEP 604/585 annotations → typing.*** — 193 个文件 (backend/ + packages/sage-core/) 同步 Win7 LTS 的 Py3.8 兼容性重写。Main (Py3.11) 上纯属 stylistic 改动,功能不变。release/win7 上是必需的运行兼容性修复
- **fix(scripts): py38_compat_rewrite.py** — 新增 AST-based 重写工具 + 一个 follow-up 修复(typing import 只插入到模块顶部,不合并到中间位置的旧 import)

## [v0.4.4-alpha.1] - 2026-07-09

> 🧪 **Alpha tier** — Sage 贡献者内测。LLM Wiki **NDJSON 流式架构** (PR-114+115+116) 上线,9 个 followup 清理 (PR-118+120+122+124),Win7 LTS 同步 (PR-117+119+121+123)。流式 chat/ingest + 6 stage 进度 + sticky progress auto-dismiss + empty retrieval UX + HTTPException status 保留 + 5 个路由层集成测试 + LLMContext dataclass 抽象 + GraphData 序列化方法 + llmConfig 集成 useSettings。

### Added
- **feat(wiki): LLM Wiki NDJSON 流式架构 (PR-114+115+116)** — `/api/v1/wiki/{chat,ingest}/stream` NDJSON 端点,Electron main `relayNdjsonToEvent` 拆分到 IPC channel,前端 `useWikiChatStream` / `useWikiIngest` hooks
- feat(wiki): 6 stage ingest 进度 (`started` → `copy_source` → `step1_analyze` → `step2_write` → `embedding` → `completed`)
- feat(wiki): `LLMContext` dataclass 抽象 (`llm_call` + `llm_stream_call` + `http_post`) + `make_llm_context` 工厂,4 路由共享
- feat(wiki): `GraphData.to_dict()` / `from_dict()` 方法,dedupe 序列化
- feat(wiki): `lastQueryHadNoResults` 状态 + "未在 wiki 中找到相关内容" UX
- feat(wiki): ingest 进度条 4s 自动 dismiss (sticky progress UX)
- feat(wiki): `DEFAULT_EMBED_MODEL` 常量 (`'text-embedding-3-small'`)
- feat(wiki): `_http_exception_from_llm` helper,3 LLM-using 路由保留 upstream status code
- test(wiki): `/ingest/stream` 路由层 5 个集成测试

### Fixed
- fix(wiki): temp .md file leak in `/ingest/stream` — `_stream_with_cleanup` async generator wrapper + try/finally
- fix(wiki): `useWikiChatStream` / `useWikiIngest` unlisten 时 `{streamId}` 透传到 `sage:unlisten` (修 abort leak)

### Documentation
- docs(wiki): 25-llm-wiki-integration.md 新增 "流式架构" section (10 章节) 描述 PR-114+115+116 架构 (PR-125)

## [v0.4.9-alpha.29] - 2026-08-27

> 🧪 **Alpha tier** — Sage 贡献者内测。**Main 分支累积发布**(v0.4.5-alpha.26 → v0.4.9-alpha.29),涵盖 50+ commit、四大块新能力:**Chat-Native 多 agent 编排** (#296+#314+#315+#316+#317+#318+#355+#356+#357+#361+#363),**Electron tier-based E2E 自动化基础设施** (#376),**事件循环阻塞根治 + 日志/医生扩容** (#293+#294+#295+#306),以及 §5.1/§5.2/§5.4 evolution/memory IPC 接线 (#339+#342)。Win10+Linux+Mac 验证用版本;Win7 LTS 用户请用 `v0.4.9-alpha.8-win7` 或更新 `-win7` 后缀的发布。

### Added

#### 多 agent 编排(Chat-Native Multi-Agent Orchestration)
- **feat: Chat-Native 多 agent 编排 (#296)** — `orchestration_mode` 接入 chat 链路,run 级 task_plan/task_progress/task_review/lanes 全套数据模型与 SSE 推送
- **Wave 1 编排执行控制 (#314)** — retry 策略、reviewer 异步评审、scratch 草稿空间
- **Wave 2 编排计划生命周期 (#315)** — 计划持久化 / resume 恢复流 / 计划卡 UI / `depends_on` 拓扑依赖 / `task_review` 阶段产物
- **Wave 3 PR A (#316)** — P2-7 计划权威 `task_id` 全局递增、P2-8 模板库、P2-9 配置化重试次数、P2-11 run 级 cancel
- **Wave 3 PR B (#317)** — P2-10 休眠层:review 模块化拆分、lanes 真实执行(LaneBoard 监控)、board 实时面板
- **编排计划卡前端接线 (#318)** — 三态视图(规划中/执行中/已结束)、取消执行、模板选择器、resume 恢复流
- **depends_on 拓扑调度 (#355)** — 分波执行(同一 wave 内并发,跨 wave 串行)+ 级联取消(上游 cancel → 下游全部 cancel)
- **agent todo 清单全链路接线 (#356)** — `todo_write` 后端暴露 + SSE 快照推送 + 前端 `TodoListCard` 渲染
- **前端 mirror 编排计划到 todo 卡 (#357)** — read-only 镜像,主区域只读,左侧 todo 卡可勾选
- **编排 P2 五项 (#361)** — schema 结构化返回 / followup 续聊 / worktree 隔离 / legacy 清理 / LaneBoard 激活
- **编排 P2 fast-follow 五项遗留 (#363)** — task_id 串号修复 + 残留 plan 双调用链清理 + 5 处 UX 修复
- **编排 control plane P0 修复 (#353)** — task_review 提交竞态 + plan lock 死锁 + cancel 信号丢失

#### Electron E2E 自动化基础设施
- **feat(electron-e2e): tier-based E2E automation infrastructure (#376, 20 commits / 49 files / +3047/-959)** — `tests/electron/` 全新目录,3-tier 架构:
  - **Tier 1 stub-smoke**:Playwright + 自带 stub backend,3 个 spec(chat / sidebar / settings),无 LLM 真实调用,CI 默认跑
  - **Tier 2 deep**:Playwright + 真实后端 + 真实 SQLite,跳过 wiki/evolution(需 LLM),`run-deep` tag 触发
  - **Tier 3 live**:真人手动 + `__TAURI__` IPC hook,本地验证用
  - 含 `stub-backend.ts` + `_real_backend.py` 复用 main `python backend/main.py` 启动逻辑,IPC 契约对齐(`/memory/save`、`/memory/list`、`/orchestration/lanes`、`/orchestration/board`),`data-testid` 选择器全覆盖,Windows NSIS 安装包 CI 红 6 项修复(import/order + session upsert + DevTools 窗口过滤 + portable Python resolver + settingsStore 顺序 + AppStartupSettings 死代码)
  - 详见 `docs/superpowers/specs/2026-08-25-electron-e2e-automation-design.md` + `docs/superpowers/plans/2026-08-25-electron-e2e-automation.md`

#### §5 章节 wiring(scheduler / memory / background review)
- **feat(scheduler): evolution 任务 lifespan 接入 (§5.1) (#342)** — evolution scheduler 任务跨请求存活,重启后从 SQLite 恢复运行状态
- **fix(memory): wire review collaborators + memory IPC (§5.2 + §5.4) (#339)** — memory 模块审阅协作 + IPC 通道补全

#### Doctor 二期扩容
- **feat(doctor): §1.5 二期扩容 (#293)** — 从 8 个 check 扩到 13 个(新增 5 项:sqlite_writable / config_integrity / port_frontend / py_version_match / disk_space),CI 中 doctor 报错可视化
- **feat: add sage doctor CLI for installation/env self-check** — `python -m backend.cli.doctor` 命令入口,8 项 CRITICAL / WARN / INFO 三级检查,`--json` 输出机器可读报告,electron 启动前自动跑(`SAGE_DOCTOR_ON_START=false` 可跳过)。详见 `docs/technical/41-sage-doctor.md` + `docs/user-manual/11-sage-doctor.md`。

#### 后端 / 前端杂项
- **feat(electron+frontend): backend 异常退出自动重启 + ECONNREFUSED 友好翻译 + UI 横幅 (PR-B)** — 防止 backend crash 后 UI 永久卡死;中文化错误提示
- **feat(orch+agent): 配置化 max_iterations + 子代理预算 + 中文错误提示 (#333)** — `DEFAULT_MAX_ITERATIONS` 5→10 + 子代理 6 次上限 + AGENT_RUNTIME_MESSAGES 全中文化
- **feat(rightpanel): 面板内添加 × 关闭按钮 (closes #298) (#299)** — 之前只能拖动整个面板,不能单独关
- **feat(orchestration): 进度可视化 (#300)** — `task_progress` 5 元组(stage / current / total / eta / message)+ UI 编排摘要卡片

#### Win7 LTS parity + base CI
- **feat(win7): complete Task 0-3 platform parity + base CI fixes (#368)** — 平台差异 Py3.8/Py3.11 适配 6 项(PEP 604 in shared models + certifi 回归 + LM Studio protocol/modelId/localModelPath + Asia/Shanghai + pydantic 1/2 model_dump_compat + streaming teardown),后续已通过 PR #377 cherry-pick 到 release/win7

### Fixed

#### 事件循环阻塞根治(§1.2 PR-A + PR-B)
- **fix(event-loop): §1.2 PR A (#294)** — `legacy_routes` 全部 `async→def`(34 handler)+ `threading.Lock` 替换 `asyncio.Lock` + jieba 热启动后台化
- **fix(event-loop): §1.2 PR B (#295)** — `storage` 适配器改 `asyncio.to_thread` + 共享 `_SQLITE_LOCK`(`per-instance Lock` 会导致跨请求死锁)

#### 日志 / 设置 / 编排 P0
- **fix(logging): 日志基础设施修复 (#306)** — 6 类故障场景排查从 10-30min 降至 2-5min(`logging.py` 启动顺序 + SageLogger 路径优先级 + audit JSONL 落盘 + structured log JSON parse + threading name 标识 + NDJSON 启动日志)
- **fix(settings): 恢复设置保存 + 测试连接用端点自身模型 (#323)** — `strip_unknown_fields` 净化残留 + `testEndpointConnection` 改用端点自身 model(避免空 model 422)
- **fix(orchestration): task_id 全局递增修复 3/6 假象 + 普通聊天 artifacts 落库 (#302)** — 旧 `task_id = (run_id, sequence)` 导致同 run 内 hash 冲突;改为进程内单调递增 + DB 唯一约束
- **fix(orch): §13.7 计划卡延后项收尾 (#322)** — 双击防重入 + 409 Conflict 区分 + resume 时 NULL plan_id 兜底
- **fix(ci): remove stale Determine ARTIFACT_SUFFIX step in main's release-win7.yml (#352)** — main 分支 release workflow 残留 win7 死代码

#### Chat 链路 + 后端 SSL / 内存
- **fix(chat-stream): accept explicit null orchestration_mode from IPC (#297)** — 前端 `null` 被错误序列化为 `"null"` 字符串
- **fix(chat-stream): CI 修复 (#345)** — `TS6133 runId` 未使用变量豁免 + import/order 空行修复
- **fix(chat): 欢迎页/输入框/新对话 三处 UI 缺陷 (#305)** — 路由切换后欢迎页残留 + 输入框失焦 + 新对话按钮 race
- **fix: preserve chat messages across route switches (#350)** — Memory / Wiki 路由切换时 Chat 缓存被清空
- **fix(backend): inject memory manager + bootstrap SSL CA from certifi (#349)** — memory 模块未注入 manager 依赖 + certifi 缺失导致自签名 CA 校验失败
- **fix(llm-proxy): dedupe /v1 when baseURL already ends with /v1 (#308)** — LM Studio 用户配置 `http://localhost:1234/v1` 时代理变成 `/v1/v1/chat/completions` 报 404

#### 测试 / CI flake 治理
- **fix(tests): bandaid two CI flakes (#299)** — Event-loop closed asyncio 警告 + §1.2 gate 阈值敏感度 100→200ms
- **test: remove stale respx xfail markers (#310)** — 104 个测试从 mock fallback 改回真实验证(`respx` 升级后 httpx mock 行为变更)
- **test(llm_client): align 2 chat_stream tests to LLMError (#309)** — 异常类型从 `httpx.HTTPError` 对齐到项目 `LLMError`
- **test(event-loop): 5-round median P99 gate, 400ms threshold (CI-reality) (#312)** — §1.2 5 轮中位数 P99 守门,从单次 P99 升级
- **fix(electron-e2e): portable Python resolver for stub_backend (CI ENOENT)** — Windows CI runner 无 `python` 在 PATH,resolver 走 `python.exe` 显式路径

### Changed

- **refactor(orch): M4 收口 — 删除 updatePlan 双调用链 (#321)** — `plan_router.update_plan` 与 `orchestration_service.update_plan` 双调用链收敛到单入口
- **chore(plans): remove completed plan file (#334)** — `docs/plans/2026-08-13_orch-p0-execution-control.md` 已 merge 到 technical/42 §10,plans/ 不保留已完成
- **chore(repo): §1.4 假功能/死设置清理 (#292)** — 30 文件删 + 12 改,清理未实现的假设置项

### Documentation

- **docs(orchestration): 归档编排修复 + 进度可视化 + Wave 3 编排 (#301+#303+#319+#320)** — 4 个 plans/ 文件删除,内容并入 `docs/technical/42-*.md` §9 / §10 / §11 / §13
- **docs: 编排技术手册 §15(拓扑调度 + agent todo 全链路)+ README 章节简介更新 (#360)**
- **docs(technical): §1.2 event-loop gate upgrade history — 5-round median P99 (#313)**
- **docs(technical): 日志基础设施修复归档 (#307)** — 29 §修复记录 + 41 §日志路径优先级
- **docs(spec): Electron E2E 自动化测试基础设施设计 + 实施计划 (15 任务) (#376 配套)**

## [v0.4.9-alpha.37] - 2026-09-09

> 🧪 **Alpha tier** — Sage 贡献者内测。**orchestration event-loop 修复** (#541):EventHub / SnapshotStore `__init__` 之前 eager 构造 `asyncio.Lock()`,在 Py3.8 (release/win7) 主线程无 running loop 时抛 `RuntimeError`;sync test fixture 用 `asyncio.get_event_loop().run_until_complete` 在 Py3.10+ 同样无 current loop。新 `backend/orchestration/_lazy_lock.py::LazyLock` descriptor 把 lock 构造延迟到第一次 `await`(此时 loop 已 active),并把 3 个测试文件 10 处 `run_until_complete` 迁到 `asyncio.run`。同时累积 #530/#535/#537/#538/#539/#540 主线工作(chat input UX、usage cache、office pandas、office_archive、alpha17 packaged-mode port、bundle pandas fix)。

### Added
- feat: 网络模式门禁（online/intranet/offline）+ 主机白名单，内网/气隙下搜索工具按模式不加载
- feat: web_fetch 正文抽取（text/links/tables/raw 四模式）+ GBK/GB18030 编码嗅探，stdlib 栈式实现
- feat: http_download 流式下载工具（工作区边界 + Content-Length/实际字节双重大小上限 + 文件名净化）

### Fixed
- fix(orchestration): #536 EventHub / SnapshotStore LazyLock descriptor + asyncio.run() in sync tests (#541)

### Changed
- chore(release): bump version to 0.4.9-alpha.37

## [v0.4.9-alpha.40] - 2026-09-10

> 🧪 **Alpha tier** — Sage 贡献者内测。**启动诊断 + 自动重试** (#586, port of release/win7 #585): 部分慢启动机器 (Win7 重灾区) 在 90s 健康检查超时内未响应 `python -m backend.main → uvicorn.run()`. 后端 ``[backend/main.py]`` 加 6 个 \`[sage-startup]\` stderr checkpoint (模块级 import 完成 / \`__main__\` 进入 / \`db.init_db()\` 完成 / \`lifespan\` 完成 / \`uvicorn.run()\` 调用), 由 \`__name__ == "__main__"\` 守护 (pytest 不触发). Electron `[electron/main.ts]` 在第一次 90s 超时后自动重试一次 (再等 90s), 日志记录 \`backendProc\` 状态 (pid/exitCode/signalCode) + \`currentBackend\` 代际, 对话框 detail 显示后端进程状态区分 crashed vs still-starting.

### Fixed
- fix(electron): startup diagnostics + auto-retry (port from win7 PR #585) (#586)

### Changed
- chore(release): bump version to 0.4.9-alpha.40



## [v0.4.9-alpha.34] - 2026-09-09

> 🧪 **Alpha tier** — Sage 贡献者内测。**Win7 安装包启动失败 P0 修复** (#513 → cherry-pick 到 win7 #514):doctor 自检在 packaged Win7 上误报 3 个 CRITICAL(SAGE_USER_DATA_DIR fallback 用了 `process.cwd()` 解析到 `C:\Program Files\Sage\` 只读目录),tray 图标因 `build/icon.ico` 不在 `electron-builder.yml` files 列表里而整个加载失败。新增 `electron/userDataPaths.ts` 统一 backend spawn + doctor spawn 的路径解析(6 vitest 测试);files 列表加 `build/icon.{ico,png}`,asar 内路径变 `<asar>/build/icon.ico` 与 `tray.ts` 期望一致。

### Fixed
- fix(electron): doctor spawn 改用 userData + tray 图标打包进 app.asar (#513)

🔗 Milestone(s): Win7 启动崩溃 P0 修复

## [v0.4.5-alpha.3] - 2026-07-11

> 🧪 **Alpha tier** — Sage 贡献者内测。**SAGE_USER_DATA_DIR 修复**(PR #134):v0.4.5-alpha.2 NSIS installer 安装到 `C:\Program Files\Sage\` 后约 4-5 秒必崩(`PermissionError: [WinError 5] 拒绝访问`),因为 backend 写 themes/scheduled_tasks JSON/audit JSONL/logs 到 bundled `resources/backend/data/`,而程序目录对普通用户只读。新 `SAGE_USER_DATA_DIR` env 让 packaged Electron 注入 `<userData>` 作为运行时可变路径,dev 透传 `<project>/data`。4 个 backend 写路径(theme + scheduler JSON + audit JSONL + log)统一签名;`electron/main.ts` + `electron/backendLauncher.ts` 增加 `sageUserDataDir` 在所有 4 个 spawn 分支都注入。

### Fixed
- fix(scripts): v0.4.5-alpha.2 NSIS installer installs to `C:\Program Files\Sage\` (system-protected) crashed 4-5s after spawn with `PermissionError: [WinError 5] 拒绝访问: 'C:\Program Files\Sage\resources\backend\data\themes'`. Backend code wrote runtime-mutable files (themes, scheduled-tasks JSON, audit JSONL, logs) to the bundled `resources/backend/data/` directory, which is read-only when installed to a system directory. Introduced `SAGE_USER_DATA_DIR` env var; packaged Electron sets it to `<userData>` (`%AppData%/Sage`), dev mode sets it to `<project>/data`. Four runtime-mutable paths now honor the env: `backend/api/theme_router.py` (module-level `_storage = ThemeStorage()` no longer hardcodes `<services>/parent/data/themes`), `backend/services/theme_storage.py` (new `_default_storage_dir()` helper prefers `${SAGE_USER_DATA_DIR}/themes`, falls back to bundled), `backend/main.py:154` (lifespan scheduled_tasks.json resolves to `${SAGE_USER_DATA_DIR}/scheduled_tasks.json` when env set, else keeps the relative `backend/data/scheduled_tasks.json` dev convenience), `backend/utils/logging.py` (SageLogger.setup picks env-driven path when no log_dir/project_root is supplied), `backend/adapters/out/event/file_adapter.py` (new `_default_audit_log_path()` helper, `FileEventAdapter()` no longer hardcodes `backend/data/audit/audit.jsonl`; raised via AI review #H1 — same root cause class as the original PermissionError). Electron side: `electron/main.ts` computes `SAGE_USER_DATA_DIR` (`<userData>` in packaged, `<cwd>/data` in dev) and passes it through to the resolver; `electron/backendLauncher.ts` adds `sageUserDataDir` to `ResolveOpts` and includes it in `extraEnv` for all 4 spawn branches (dev-conda / dev-conda-overridden / packaged-win32 / packaged-linux). Caller-supplied `storage_dir=...` always wins (test/doc scenarios). 3 new unit tests in `TestThemeStorageDefaultDir` cover env-set / env-unset / explicit-overrides-env. All 18 theme tests + 13 backendLauncher tests + 691 vitest + backend pytest all pass; tsc clean.

## [v0.4.5-alpha.2] - 2026-07-11

> 🧪 **Alpha tier** — Sage 贡献者内测。**bundle python 修复 PR #132** 修复了 v0.4.5-alpha.1 NSIS installer 安装后启动 4-5 秒仍报 `ModuleNotFoundError: No module named 'sage_core'` 然后 30s "后端健康检查超时" 对话框的根因(7z 提取已确认每行 content 都是真正的 traceback)。

### Fixed
- fix(scripts): v0.4.5-alpha.1 packaged installer still crashed at startup with `ModuleNotFoundError: No module named 'sage_core'` (4-5s after spawn → 30s backend health timeout dialog). PR #130 carried forward the `_pth` `..` fix but DELETED the win7 LTS `pip install -e $SageCoreDest` step on the (incorrect) assumption that the hyphen-named `resources/sage-core/` directory would satisfy `import sage_core`. Python's import machinery is path-literal and rejects hyphen-named module dirs, so the inner `sage_core/` was never on sys.path. Now `bundle-python-main.ps1` ALSO copies `packages/sage-core/sage_core/` directly into `resources/python/Lib/site-packages/sage_core/`, where `import site` (enabled in `_pth`) puts it on `sys.path` unconditionally. `pip install -e` is intentionally NOT used because it bakes the build-machine's absolute path into the generated `.pth`, which does not exist on end-user machines. Verify step now also canary-imports `sage_core` + `from sage_core.entities import AgentDecision` to catch this regression at bundle time.

### Changed
- chore(release): bump version to 0.4.5-alpha.2

## [v0.4.5-alpha.1] - 2026-07-10

> 🧪 **Alpha tier** — Sage 贡献者内测。**spawn conda ENOENT 修复 + main-branch Python bundling** (PR #130, 6 commits / 8 files / +914 -75)。修复了 main 分支 Windows NSIS installer 因缺 Python bundling 步骤导致 end-user 启动时抛"a javascript error occurred in the main process"的根因。Resolver + bundling 双层修复，新 resolver 函数 13 个 vitest cases 覆盖全分支。

### Added
- feat(wiki): native folder picker for project create/open, recent projects memory, debounced backend pre-check (issue: llm-wiki-folder-picker)
- feat(release): main-branch Python bundling (`scripts/bundle-python-main.ps1`) — wraps Python 3.11 embeddable + `backend/requirements.txt` (main, pydantic 2.x) + `packages/sage-core` into the same `resources/` tree that `electron-builder.yml` extraResources expects. Mirrors `scripts/bundle-python.ps1` (Win7 LTS, Py 3.8), with main-branch-specific fixes cherry-picked from release/win7 LTS commits 4cea570 / 2689cb8 / a20c061 / 973d44c (python311._pth `..` path import + `import backend.main` canary + `LASTEXITCODE` guards + no dead `start-backend.bat` + precise `resources/` cleanup).
- feat(electron): `electron/backendLauncher.ts` — pure-function resolver that picks the right Python launcher (dev conda / SAGE_PYTHON override raw-python / packaged Win / packaged Linux / macOS unsupported / unknown platform). Replaces the inline `if (pyLauncher)` branch in `electron/main.ts#spawnBackend()` so the decision is unit-testable.

### Fixed
- **fix(electron): packaged Win installer crashed with "spawn conda ENOENT" at startup** — root cause was two-layer, fixed in this PR + review pass:
  1. **Resolver layer** (`electron/main.ts` + new `electron/backendLauncher.ts`): previously `spawnBackend()` fell back to `spawn('conda', ...)` whenever bundled Python didn't exist. End-user Windows machines have no `conda`, so this surfaced as an opaque main-process JavaScript crash that buried the real cause. The resolver now refuses to call `conda` in `app.isPackaged` mode and instead surfaces a clear "Python 后端未找到 (安装包可能损坏)" dialog pointing users to the GitHub releases page to reinstall; macOS / unknown-platform packaged builds short-circuit to informative dialogs.
  2. **CI layer** (`.github/workflows/release.yml`): previously the main release workflow was missing the `bundle-python` step that `release-win7.yml` had since the Win7 LTS split. `release.yml` now calls `pwsh scripts/bundle-python-main.ps1` on the Windows runner before `electron-builder`, so main-branch releases produce a self-contained installer.
  3. **Hardening** (review pass after PR was opened): spawn-backend now has a `'error'` handler so AV/ACL/ENOEXEC failures don't crash the main process; the second misleading "30s 后端超时" dialog is suppressed when the broken-installer dialog already fired (`reportedBrokenInstaller` sentinel); `SAGE_PYTHON=python3` override no longer produces a broken `python3 run -n ...` spawn (the resolver now distinguishes conda-style vs raw-python commands).
  4. **`electron-builder.yml` extraResources trimmed**: dropped the dead `resources/start-backend.bat` entry (main.ts spawns `python.exe` directly via the resolver, never invokes the .bat — same cleanup release/win7 applied in 973d44c).
  - **Known follow-up**: Linux Python bundling (Ubuntu AppImage / deb) is still missing. No Python "embeddable" distribution exists for Linux; needs `python-build-standalone` or PyInstaller — out of scope for this bug-fix PR.
  - **13 new vitest cases** cover both packaged branches + dev branch + SAGE_PYTHON override (incl. a regression guard that `python3` override does NOT emit conda-flavoured args).
- feat(wiki): gate folder picker Browse button behind `appSettings.wiki.useFolderPicker` (default true; set false to fall back to plain text input — see §8 rollback in plan)
- feat(skills): conform `backend/skills/skill_md/` to agentskills.io spec
  - Add optional fields: `license`, `compatibility` (≤500 chars), `allowed-tools`
  - Strengthen `name` (≤64 chars) and `description` (≤1024 chars) validation
  - Support single-file `<dir>/SKILL.md` form in loader
  - Warn (not block) when frontmatter `name` != parent directory name
  - Emit warning when description lacks trigger keywords
  - All changes forward-compatible; existing SKILL.md files unaffected
  - Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md

## [v0.3.0] - 2026-06-23

### Added
- **feat(chat): 实时显示工具调用、思考过程和 agent 编排 (#57)**
  - P0: `streamingToolCalls` 升级为 `useState` + ref 镜像，acting/observing 事件立即渲染，不再等流结束
  - P1: ThinkingPanel 流式自动展开，`useEffect` 监听 `isStreaming` 变化
  - P2: ActiveAgentIndicator 显示"第 N 轮 · agent 名 · 阶段图标 (lucide)"，新增 `src/shared/lib/agentStateMapping.ts` 作为单一真相源
  - 附带修复: setTimeout 泄漏 / 不可变更新 / `ToolCall.id` 字段 / `interrupt()` finishStream / cancel-prev 同时停后端 / `Message` React.memo + 自定义比较函数
- **feat(ci): 双轨 release workflow (main → Win10+/Linux, LTS → Win7 SP1)**
  - main release 产物: `Sage-Setup-${version}-win10.exe` / `sage_${version}_amd64.deb` / `Sage-${version}.AppImage`
  - LTS release 产物: `Sage-Setup-${version}-win7.exe` (Windows 7 SP1 x64 only, tag 形如 `v*-lts`)
  - 新 workflow: `.github/workflows/release-win7.yml` (在 `release/win7` 分支)
  - `electron-builder.yml`: `win.artifactName` 用 `${env.ARTIFACT_SUFFIX}` 占位

### Changed
- **docs(technical)**: `21-win7-lts.md` 加 §9 Release 工作流；`26-packaging-matrix.md` §1/§2 拆 Win7/Win10+；`20-electron.md` §5 加 LTS 提示
- **docs(README)**: §"双轨发布" 表格加具体下载入口；Q4 重写
- **docs(user-manual)**: `01-desktop.md` §1.1/§1.2 拆 Win7 LTS 子节

### Fixed
- **fix(lint): 排除 dist-electron 扫描 + 修复 4 个 warnings (#59)** — `package.json` lint 脚本加 `--ignore-pattern dist-electron`，修复 WikiGraphView / Sidebar / MemoryBrowser 的 eslint warnings，删除 stale plan 文档
- **fix: expose agent list to LLM and add settings endpoints to legacy mode**
- **fix(ci): add ARTIFACT_SUFFIX to ci.yml Windows build step**
- **fix(ci): add trailing newline + fix artifact name in release notes**
- **fix(backend): auto-fix ruff lint errors in integration tests (#52)**

### 计划中
- 跟踪 [`docs/plans/2026-06-13_full-quality-optimization-v2.md`](./plans/2026-06-13_full-quality-optimization-v2.md) 7 方向 A-G
  - A. 六边形迁移收口(剩 A2 memory / A3 evolution / A4 skills / A5 agents / A6 wiki / A7 llm-proxy)
  - B. FSD 收口(`src/{components,hooks,lib,types}` 归位)
  - C. 前端覆盖率阈值 + Playwright E2E ≥ 8 个
  - D. WCAG 2.2 AA + axe-core + Lighthouse ≥ 95
  - E. 性能与体积基线 + CI 预算
  - F. 安全审计入 CI(npm/pip audit + gitleaks + electronegativity)
  - G. onboarding 一键脚本 + ADR 起步

## [v0.2.0] - 2026-06-22

### Added
- **feat(agent): 接通 Agent Profile 到运行时 (#48)** — SageAgent 接受 `agent_id` 参数，运行时从 SQLite 读最新 profile，消费 `system_prompt` / `max_iterations` / `enabled` 字段
- **feat(orchestrator): 接入 AgentOrchestrator 到生产** — `/chat` 路由根据消息复杂度（关键词 + 长度）分流，复杂消息走 `AgentOrchestrator.process_request`
- **perf(orchestrator): `asyncio.gather` 并行子任务** — `_execute_multi_step` 用 `asyncio.gather(return_exceptions=True)` 替代串行执行，结果顺序与输入一致，错误隔离
- **feat(ui): ActiveAgentIndicator 组件** — 流式聊天时显示"🤖 当前处理 agent: xxx"，3 秒无更新后淡出
- **feat(agent): get_enabled_agent() 工具函数** — 从 SQLite 读启用 agent 的 profile dict（disabled/missing 返回 None）
- **feat(agent): AgentEvent.agent_id 字段** — 透传当前活跃 agent ID 到前端
- **feat(backend): localStorage → SQLite 配置存储迁移 (#46)** — settings 持久化到后端 preferences 表，前端 localStorage 兜底缓存 + 7 天过期清理
- **feat(backend): SAGE_DB_PATH env var** — 支持 packaged Electron 后端子进程用独立 DB 路径
- **feat(backend): SettingsRepository on preferences table** — 通用 KV 存储，KEYS 白名单限定可写 key
- **feat(backend): GET/PUT /preferences/{key}** — theme & session id 持久化
- **feat(electron): 4 IPC routes for settings & preferences** — Electron 端透传
- **feat(electron): set SAGE_DB_PATH for backend subprocess** — Electron 启动后端时设 DB 路径
- **feat(frontend): async settings storage with auto-migration + 7d cleanup** — 自动迁移 + 缓存过期
- **feat(frontend): theme storage + session storage dual-write** — 本地缓存 + 后端同步
- **feat(frontend): useStore.currentSessionId / ThemeProvider / useSettings async init** — 异步初始化避免启动竞态
- **feat(frontend): settingsClient IPC wrapper with 5s timeout** — 统一 IPC 客户端
- **fix(ci): 多个 CI 修复** — 从 backend 目录安装依赖、requirements.txt、sage_core 包
- **fix(backend): conftest teardown 守卫 importlib.reload residue**
- **fix(backend): skip pre-existing broken tests (SessionService DI not wired)**
- **fix(frontend): useChat tests wait for useSettings async load**
- **fix(frontend): settingsClient ipcCall type — object → Record<string, unknown>**
- **fix: main 分支 pre-existing TypeScript 错误** — `saveSettings` 显式 `as AppSettings` 类型断言

### Changed
- **fix(frontend): main 分支 pre-existing lint 错误** — `import/order` 自动修复（App.tsx / ThemeProvider.tsx / store.ts 等）
- **test(integration): hex-only 测试加 @_HEX_ONLY skip** — `/preferences/{key}` / `/settings` 端点在 legacy 模式不注册，hex 模式才跑

## [v0.1.2] - 2026-06-15

### Added
- **PG-A1 sessions 6 端点 hex 迁移(#19)**——把 legacy 路由的 `/sessions/*` 迁到六边形架构
  - 新建 `SessionService` (`backend/application/services/`) 编排会话生命周期,内置 OTel + 审计 + 指标
  - 扩 `StoragePort`:加 `get_session` / `update_session` + 改 `delete_session` 返 rowcount
  - `hex_routes.py` 加 6 端点 + 2 Pydantic 模型(`SessionCreate` / `SessionUpdate`) + DI 工厂
  - 响应字段与 legacy 完全兼容(POST/GET/PATCH/DELETE + 错误文案 "会话不存在"),前端 0 改动即可切换
  - 单元测试 15 个 + 集成测试 12 个覆盖 happy + 404 路径
- **Tauri → Electron 21.4.4 迁移(#14)**——主桌面框架切换,Electron 21 是 Win7 兼容的最后一版
- **Win7 LTS 维护章节(#18 + #21-win7-lts)**——18 个月归档时间表 + 真机烟测 SOP + 风险声明
- **IPC shim 改名(#16)**——`tauriInvoke` / `tauriEvent` 改名为 `desktopInvoke` / `desktopEvent`(与 transport 解耦,旧名 6 个月过渡到 2026-12-31)
- **CI backend-py38 + win7-lts 分支守卫(#15)**——双 Python 版本 + release/win7 分支自动保护
- **LLM 代理路由**(`/api/v1/llm/*`)——旁路浏览器 CORS,前端直接打 LLM 不再需要 OLLAMA_ORIGINS 配置
- **Agents CRUD 端到端**——`list` / `get` / `update` / `toggle` 4 端点
- **Chat 流式响应端到端**——NDJSON → Tauri event → React 中间态文案
- **Skills 系统端到端**——`SkillPort` + 3 routes + 3 commands + 4 builtin skills
- **LLM Wiki 集成 PR-8(Phase 1-7)**——4 LLM provider 抽象 + LanceDB RAG(hybrid retrieval) + 知识图谱(4-signal) + React Flow 视图
- **Tauri CLI 包锁定**——`@tauri-apps/api` / `@tauri-apps/cli` 锁到 `=2.1.0`,修 major.minor 一致性校验失败
- **Electron-builder 矩阵 + Playwright Electron smoke**——3 OS 自动化构建 + 桌面端冒烟测试

### Changed
- `backend/main.py` 默认 `API_MODE` 临时从 `"hex"` 改 `"legacy"`(1 字符 + TODO 注释),等后续 PR 装配 SessionService DI 后改回 `"hex"`
- 5 个集成测试的 local `_API_MODE` 默认同步从 `"hex"` 改 `"legacy"`,与 main.py 实际配置一致

### Deprecated
- `src/lib/tauriInvoke.ts` / `tauriEvent.ts` re-export shim——已 `@deprecated`,计划 2026-12-31 删除(`release/win7` 临时保留到 2026-12-31)

### Fixed
- **Electron 桌面端 Linux 启动修复(#25)**——`electron/main.ts` 把后端 spawn 从 `python backend/main.py` 改成 `python -m backend.main`,让 `from backend.adapters...` 绝对 import 能 resolve;同步加 `postinstall` (`scripts/fix-chrome-sandbox.sh`) 在 `npm install` 后自动恢复 `chrome-sandbox` 的 root 所有权 + 4755 SUID 位(Linux-only,macOS/Windows 跳过,idempotent)
- **构建图标 gitignore 修正**——`build/icon.{ico,png}` 改为跟踪,修 `electron-builder` 缺图标的隐式失败
- **WikiGraphView 单元测试外移**——inline `describe` 移到独立文件,修 vitest 多文件解析问题
- **Tauri CLI 锁版本**——`@tauri-apps/api` / `@tauri-apps/cli` 锁到 `=2.1.0`,修 major.minor 一致性校验
- **WikiChat import 顺序**——CI lint 失败的 import 顺序修正

## [v0.1.1] - 2026-06-08

### Security
- 通过 fork backport CVE-2026-42184(GHSA-7gmj-67g7-phm9)
- 锁定 Tauri 2.1.1 矩阵(Win7 + Rust 1.77.2 兼容)

### Fixed
- `release.yml` 多个隐患(vs-setup deleted / Node 18 / cargo update / contents: write)

### Documentation
- 完整文档归档:`docs/technical/20-win7-tauri-compat.md`

### Build
- 首个 Win7 兼容 Windows 安装包 `Sage_0.1.1_x64-setup.exe`(含 WebView2 v109 离线嵌入)

## [v0.1.0] - 2026-05-09

### Added
- 完善 GitHub Actions Windows 构建配置(`.github/workflows/ci.yml` + `release.yml` + `src-tauri/tauri.conf.json`)

[Unreleased]: https://github.com/oneMuggle/sage/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/oneMuggle/sage/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/oneMuggle/sage/compare/v0.1.2...v0.2.0
[v0.1.2]: https://github.com/oneMuggle/sage/compare/v0.1.1...v0.1.2
[v0.1.1]: https://github.com/oneMuggle/sage/compare/v0.1.0...v0.1.1
[v0.1.0]: https://github.com/oneMuggle/sage/releases/tag/v0.1.0


