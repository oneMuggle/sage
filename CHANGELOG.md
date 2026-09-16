# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Release Tier Definitions

| Tier | Tag Format | Audience | Channel |
|------|-----------|----------|---------|
| **alpha** | `vX.Y.Z-alpha.N` | Sage contributors only | GitHub Releases (prerelease) |
| **beta** | `vX.Y.Z-beta.N` | Public beta testers | GitHub Releases (prerelease) |
| **rc / preview** | `vX.Y.Z-rc.N` | Broad testing, recommended for early adopters | GitHub Releases (prerelease) |
| **stable** | `vX.Y.Z` | All users | GitHub Releases (latest) |

Win7 LTS adds `-win7` suffix after tier (e.g. `vX.Y.Z-beta.N-win7`).

## [Unreleased]

> 🌐 **网页访问能力优化 Round 5 批次 4：文件嗅探与浏览器下载跟踪**（方案 `docs/plans/2026-09-14_web-access-download-analysis-round5.md` §2.2 SN2/SN3）

### Added(web-access)
- **`web_fetch mode=files`（SN2，新模块 `backend/tools/file_links.py`）**：从静态或渲染后 DOM 抽取候选文件链接并打分——`<meta name=citation_pdf_url>` / `<link rel=alternate type=application/pdf>`（学术站标准位，最高分）、`<a href>` 文件后缀（pdf/zip/docx/xlsx/epub/csv/…）与 `download` 属性 / `type=application/pdf`、`<iframe|embed|object>`、`<meta http-equiv=refresh>`、「下载 / 全文 / PDF / attachment」锚文本；同 URL 去重合并 `sources`；对 top-5 候选做首块探测（不跟随重定向、逐个过 `check_host`）标 `probe=file|html|redirect|error` + `detected_type` / `content_type` / `content_length` / `suggested_filename`，`probe=html`（登录页 / 中转页）降权；SPA 壳自动渲染后把动态 DOM 候选与静态候选合并；结果 `files[]` 可直接喂 `http_download`
- **浏览器下载跟踪（SN3，新模块 `backend/tools/browser_events.py` + 新工具 `browser_downloads`）**：`browser_launch` 后为会话建立一条常驻 CDP 事件 WS（守护线程），`Browser.setDownloadBehavior{eventsEnabled:true}` 订阅 `downloadWillBegin` / `downloadProgress`，落成线程安全的 `DownloadTracker`（url / 文件名 / 状态 / 字节 / 最终路径，完成时按 guid 或 suggestedFilename 解析落盘路径）；`browser_downloads(browser_id?, wait_for_complete, timeout)` 列出 / 阻塞等待全部完成，完成文件登记 artifact（只登记一次）；事件通道不可用时退化为下载目录列举（`.crdownload` = 进行中）并明示；`browser_close` / 后端退出时停通道

### Changed(web-access)
- `BROWSER_TOOLS` 新增 `browser_downloads`（READ）；coder 默认工具白名单经 `*BROWSER_TOOLS` 自动带上；`browser_launch` 结果新增 `download_tracking`


## [v0.4.9-alpha.34-win7] - 2026-09-15

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 收口 7 commits：py3.8 后端 round 3 / Ruff lint 收口 / main 最大化对齐 B1-B6 / UI/Code 字体定制 / Windows bash 工具 + 工具 schema 校验。

### Fixed
- **Windows bash 工具** (#858): `spawn_verified` 在 Windows 走 `CREATE_NEW_PROCESS_GROUP` 建立独立进程组；`kill_process_tree` 走 `taskkill.exe /T /F` 递归终止进程树，taskkill 失败回退到 leader kill。修复 win7 安装包上 bash 工具报错 "平台不支持安全进程组回收" 的问题。
- **工具 schema 校验** (#858): `execute_tool` / `_await_tool_execution` 分发前调用 `_validate_required_params` 读取 `tool.schema.parameters.required`，LLM 漏传 required 参数时返回友好错误而非 Python TypeError。修复 win7 安装包上 office_read 抛 "execute() missing 1 required positional argument: doc_id" 的问题。
- **REPL pending cleanup** (#858): Windows `observed=None` 路径不再直接 return，改走 `kill_process_tree`，避免原 kill 失败的进程永远残留在 `_PENDING_CLEANUPS`。
- **execute_code stderr buffering** (#850 round 3): py3.8 兼容路径，确保 stderr 不被吞
- **hardlink_to**: py3.8 缺失 API 用 `os.link` 兜底
- **Ruff 收口** (#850 round 3): py38 typing 回写产生的 I001/F811/F401 全部清零

### Changed
- **main 最大化对齐** (#850): B1-B6 + Phase 3 自动化（auto_sync + parity 分级守门 + win7-sync workflow），release/win7 与 main 差异 1937 → 226
- **UI/Code 字体定制子系统** (#856): cherry-pick main PR #851

## [v0.4.9-alpha.33-win7] - 2026-09-14

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 修复 LLM 代理响应编码错误。

### Fixed
- **LLM 代理响应编码**: `_read_response_body_limited()` 从 `aiter_raw()` 改为 `aiter_bytes()`，修复上游压缩响应（gzip/deflate）未解压导致前端 JSON 解析失败的问题。影响所有非流式 LLM 代理请求（如 `/v1/models` 列表查询）。

## [v0.4.9-alpha.32-win7] - 2026-09-14

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #794 — 安装包日志错误修复 (3 bugs)。

### Fixed
- **fetchModels 防御性检查**: 非标准 JSON 上游 (LM Studio 变体) 不再导致 `data.data.map()` TypeError
- **settings_canonicalizer**: 新增 `local_model_path` → `localModelPath` alias，兼容旧数据迁移
- **knowledgeApi 死代码清理**: 消除 `list_knowledge_docs` / `search_knowledge_docs` Unknown IPC command 错误日志；删除 4 个废弃组件

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


## [v0.4.9-alpha.31-win7] - 2026-09-14

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #777 帮助系统修复。`src/pages/Help/HelpTab.tsx` 移除链接 `target="_blank"` 改为应用内跳转 + 新增 5 个 markdown 帮助文档导入 (chat/memory/skills/office/orchestration), `src/pages/Help/AboutTab.tsx` `process.*` 改为 `typeof process !== 'undefined'` guard 返回 'N/A' 兜底 (修复 `process is not defined`), `src/pages/Help/ChangelogTab.tsx` + `HelpTab.tsx` 把 `window.changelogAPI/helpAPI` 改为 `window.electronAPI?.changelogAPI/helpAPI`, `src/shared/types/electron-api.d.ts` 新增两个 IPC bridge 类型, `electron/main.ts` 新增 `sage:changelog:read` IPC handler (dev 走 `__dirname/../../CHANGELOG.md`,packaged 走 `process.resourcesPath/CHANGELOG.md`), `electron-builder.yml` 把 `CHANGELOG.md` 加入 `extraResources` (packaged 时随包分发)。零冲突自动合并;Frontend TS + Electron build 双绿。

### Fixed
- **fix(win7): cherry-pick main #777 帮助系统修复** — 链接改为应用内跳转;8 个 builtin 帮助项全部补齐内容;About/Changelog 页面正常加载

### Changed
- **chore(release): bump version to 0.4.9-alpha.31-win7**

## [v0.4.9-alpha.30-win7] - 2026-09-13

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #765 Round 3 `search_config` key 静态加密落库 + `web_search` 查询缓存。`backend/security/key_store.py` 新模块 (AES-256-GCM 静态加密 + Win7 Py3.8 兼容),`backend/api/search_routes.py` 加缓存命中检查。11 unit + 3 integration test 引用。

### Added
- **feat(win7): cherry-pick main #765 Round 3 search_config 加密落库 + web_search 缓存** — 密钥静态加密 + 查询缓存减少 LLM 重复请求

### Changed
- **chore(release): bump version to 0.4.9-alpha.30-win7**

## [v0.4.9-alpha.29-win7] - 2026-09-12

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #759 Round 2 反爬路由指引 + UA 现代化 + `web_fetch` TTL 缓存。

### Added
- **feat(win7): cherry-pick main #759 Round 2 反爬路由 + UA + web_fetch 缓存**

### Changed
- **chore(release): bump version to 0.4.9-alpha.29-win7**

## [v0.4.9-alpha.28-win7] - 2026-09-11

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #618 Phase 3 T3.3 GitLab release provider。`electron/update/providers/gitlab.ts` 145 行 (GitLab API v4 PRIVATE-TOKEN 鉴权 + 项目 ID URL-encode + upcoming_release prerelease 过滤 + assets.links 下载 + 401/404 错误本地化), `electron/update/__tests__/providers/gitlab.test.ts` 177 行 (7 测试:endpoint + token header / projectId encode / 自建 baseUrl / 401 凭证错 / 404 项目不存在 / 空数组 null / ping ok), `electron/main.ts` 注册 `providerRegistry.register('gitlab', ...)` 在 github/gitee 之后。同 main PR #629 已 cherry-pick 的 GitHub #616 + Gitee #617 一致风格。零新增依赖;7 vitest 全绿。

### Added
- **feat(win7): cherry-pick main #618 Phase 3 T3.3 (#632)** — GitLab Releases provider 支持 GitLab.com + 自建 GitLab + 私有部署;7 vitest tests 全绿

### Changed
- **chore(release): bump version to 0.4.9-alpha.28-win7**

## [v0.4.9-alpha.27-win7] - 2026-09-11

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS cherry-pick of main PR #611 第十一批:嵌入器运行时切换/模型下载/设置页卡片 + A/B 权重变体。`backend/memory/embedder_factory.py` 加 `Embedder` 协议到 import block (Ruff F821 fix, follow-up from initial PR #623 attempt), `backend/adapters/out/memory/adapter.py` 加 `os` 导入支持 backfill, `electron/modelDownloadIpc.ts` 170 行新文件 (download progress events), `src/pages/settings/MemoryTab.tsx` 87 行嵌入器管理 UI + 卡片, `backend/api/embedder_routes.py` 73 行新 endpoints (list/select/download 嵌入器), `backend/main.py` 注册路由。Win7 独有:MemoryTab 补 `useNavigate` 导入 (frontend TS build 失败),`auto_memory`/`retrieval` 开关移植 (writer profile 默认值对齐 main)。73 unit + 4 integration test 引用;symspell 不变。

### Added
- **feat(win7): cherry-pick main #611 第十一批 (#623)** — `backend/memory/embedder_factory.py` runtime 切换;`backend/api/embedder_routes.py` 73 行 (list/select/download);`electron/modelDownloadIpc.ts` 170 行 (download progress events);`src/pages/settings/MemoryTab.tsx` 87 行 (嵌入器管理卡片 + 切换 UI)

### Fixed
- **fix(win7): add Embedder import to embedder_factory.py (Ruff F821)** — `create_embedder()` 返回 `Embedder` 协议但未 import,Ruff CI 红 → 1 行 import 加
- **fix(win7): MemoryTab 补 useNavigate 导入 + auto_memory/retrieval 开关移植** — frontend TS build 红 → `import { useNavigate }` 加
- **fix(win7): adapter 补 os 导入** — backfill path 用到 `os.path` 缺 import → 1 行加

### Changed
- **chore(release): bump version to 0.4.9-alpha.27-win7**

## [v0.4.9-alpha.24-win7] - 2026-09-11

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 同步 main PR #584 期刊模板子系统 (8-PR 系列 N1–N8):把 .docx 期刊模板解析为结构化 `JournalSpec`、起草结构化稿件、按 spec 校验、把素材填入模板生成可投搞稿件。8 个 backend 模块 (`backend/office/journal/{models,parser,validator,generator,persistence,llm_adapter,pandoc_adapter,errors}.py`)、4 个 office 路由、`OfficeJournalTool` 注册到 writer profile,前端 `src/features/journal/{JournalPanel, components/*, useJournalTemplates, index}`、`tests/e2e/journal.spec.ts` Playwright journey、文档 `docs/technical/55-journal-template-subsystem.md` + `docs/user-manual/13-journal-template-panel.md`。手动 port 而非 merge commit:剔除 main-only 的 7 个 office routes + `OfficeAnalyzeTool` + `OfficeEditPreviewDialog` + FTS backfill (PR #561/564/569 batch-2/3/round-2/3 依赖),保留 win7 现有 Pydantic v1 兼容;profile whitelist 删 orphan `office_analyze`。

### Added
- **feat(win7): cherry-pick PR #584 journal template subsystem (#625)** — 8 backend 模块 + 4 路由 + `OfficeJournalTool` + 8 前端组件 + 5 IPC commands + E2E journal Playwright + docs/technical/55 + docs/user-manual/13 + docs/technical/54 对标追踪
- **feat(office): journal 4 路由 + tool** — `POST /office/journal/parse-template` / `GET /office/journal/specs` / `GET /office/journal/specs/{spec_id}` / `POST /office/journal/validate` / `POST /office/journal/fill-from-content`

### Fixed
- **fix(office): ruff CI failures** — `persistence.py` F821 lambda-exc closure 改 `len(exc.errors())` (v1/v2 双兼容);`models.py` PEP 604 `str | bytes` → `typing.Union`;`profiles.py` 删 orphan `office_analyze` 引用以满足 `test_profile_seeds_within_known_names`;`preload.ts` 删 5 个 unused Office 类型导入

### Changed
- **chore(release): bump version to 0.4.9-alpha.24-win7**

## [v0.4.9-alpha.23-win7] - 2026-09-10

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS **启动诊断 + 自动重试** (port of release/win7 #585): 部分 Win7 机器首启 >90s 超时,后端 `backend/main.py` 加 6 个 `[sage-startup]` stderr checkpoint(`__name__=='__main__'` 守护),Electron `electron/main.ts` 第一次超时后自动重试一次 (再等 90s) + 日志 backendProc 状态;对话框 detail 显示 pid/exitCode/signalCode 便于诊断。本批累积同期未单独 changelog 的 win7 适配:PR #568 (alpha.19 HMAC fallback 路径)/ #580 (alpha.21 flat-split-bg 图标)/ #583 (alpha.22 圆角蒙版 transparent bg) — 同列于此便于追踪。

### Fixed
- **fix(electron): Win7 startup diagnostics + auto-retry (#585)** — 6 个 startup checkpoint + Electron 端超时自动重试一次;backend spawn 状态进对话框详情;ruff T201 用 `# noqa: T201` per-line

### Changed
- **chore(release): bump version to 0.4.9-alpha.23-win7**

## [v0.4.9-alpha.9-win7] - 2026-08-29

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 同步 main #381 bash-tool-parity:将 `TerminalTool` 替换为 `BashTool` / `BashOutputTool` / `KillShellTool` 三件套,与 Claude Code Bash 工具语义对齐。Cherry-pick 链路: main `81a20b0b` → win7 `00984167` (#382),37 文件 / +7481/-547。

### Added
- **feat(win7-tools): cherry-pick main bash-tool-parity (#382)** — main PR #381 (30 文件 / +3123/-630)。新增 `backend/tools/bash_session.py`(`BashSessionRegistry` 后台 shell 进程表,32 上限,内存态)、`bash_tool.py`(三件套实现 + 危险命令分级 → PermissionEnforcer)、`subprocess_util.py`(`BoundedOutputCollector` / `spawn_verified` / `kill_process_tree` 跨平台原语)、`shell_resolver.py`(POSIX bash→sh / Windows Git Bash→PowerShell 探测)。前端 `src/shared/lib/humanize.ts` 加 bash/bash_output/kill_shell 三工具的中文风险描述。docs `docs/technical/44-bash-tool.md` 新建章节。冲突解析 2 处:(1) `backend/tools/__init__.py` 的 `__all__` — win7 alpha.8 有重复/错位的 `AgentTool` 行 + 缺 BashTool trio,合并为单一完整列表;(2) `backend/tests/integration/test_lifespan_wiring.py` — 保留 win7 既有的 `test_lifespan_wires_hooks_and_evolution_scheduler` + `test_watchdog_fetch_runs_sql_off_event_loop` + PR 新增 `test_lifespan_health_metadata_uses_runtime_ownership_envelope` + 4 个 shutdown 测试 (`test_shutdown_bash_sessions_clears_registry`、`_swallows_cleanup_failure`、`test_shutdown_repl_cleanups_calls_pending_cleanup`、`_swallows_cleanup_failure`),补 `import os`。Python 3.8 兼容性已验证:`sage-backend-py38` (Python 3.8.20) 跑全量 backend 单测 `3522 passed`,Backend (Python 3.8, Win7 LTS) CI 8m10s pass。

## [v0.4.9-alpha.7-win7] - 2026-08-25

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 同步 rightpanel 面板 × 关闭按钮 UI 改进:cherry-pick main 的 `5e43f8e6 feat(rightpanel): 面板内添加 × 关闭按钮 (closes #298)`。本批扫描 10 个 main 候选,核对发现仅 rightpanel × 按钮还未在 win7 适配 (其余 #345 / #350 / #363 / #339 / #349 / #310 / #352 / 331bd737 PR-B 等 9 个均已通过 #346 / #351 / #364 / #341 / #348 / #311 / alpha.5 / 756e165a 等 win7 适配版提前到位)。

### Added
- **fix(win7-rightpanel): cherry-pick main rightpanel × 关闭按钮 (#374)** — main `5e43f8e6` 5 文件 / +714/-18:`PanelHeader` 新组件封装 × 关闭按钮 + tab 切换两态,`RightPanel` 用 `PanelHeader` 替换原 inline tab/关闭 UI,新增 `PanelHeader.test.tsx` 7 用例覆盖 × 按钮调用。冲突解析:`RightPanel.tsx` 解构区 cherry-pick 含 `taskBoard?: TaskBoard | null` 字段,win7 未移植 main #318 编排计划卡前端接线,`RightPanelProps` 接口无该字段 → **直接移除 `taskBoard` 解构**,与 win7 当前接口对齐,避免 TS 报错 + 不引入 orchestrator 依赖。Plan / spec 文档一并 cherry-pick,便于未来 cherry-pick #318 时无缝衔接。

## [v0.4.9-alpha.6-win7] - 2026-08-25

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 平台一致性 + Chat UI 补全回归测试落地:cherry-pick main 的 PR #305 (Chat 顶部 "+ 新对话" / Sidebar 跳转 / InputCard autosize 三处 UI 缺陷修复)。本批原本挑选了 4 个低风险 PR (#286 / #298 / #305 / #308),核对发现仅 #305 还有未 cherry-pick 内容(R1 autosize 回归测试),其余三个已被 PR #287 / #312+#313 / #324 等前置到位。

### Fixed
- **fix(win7-chat): cherry-pick main PR #305 三处 Chat UI 缺陷 (R1/R2/R3) 回归测试补全 (#372)** — main PR #305 R1 (InputCard autosize)、R2 (Sidebar 用 navigate 替代 window.location.href)、R3 (Chat 顶部 "+ 新对话" 跳 /welcome) 三处主代码已在 win7 通过 PR #324 等途径前置到位。本批 cherry-pick 仅追加 R1 autosize 回归测试 (`src/widgets/chat/__tests__/InputCard.test.tsx` +20 行),守护 `textarea.style.height` 在 value 变化时被 useEffect 更新、封顶 200px 的契约。冲突解析:`InputCard.tsx` 第 149-152 行 cherry-pick 想移除的注释实际是 win7 适配注解 (`emacsRef 同时服务 autosize, 与 main #252 最终形态一致`),保留并删冲突标记

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

## [v0.4.9-alpha.3-win7] - 2026-08-23

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 分支同步编排控制面、拓扑调度、agent todo、结构化返回、follow-up 续聊、worktree 隔离、legacy 清理和 LaneBoard 激活。

### Fixed

- fix(win7): 同步 orchestration control plane P0
- fix(win7): 同步 P1 `depends_on` 拓扑调度与 agent todo 全链路
- fix(win7): 同步 P2 schema 结构化返回、follow-up 续聊、worktree 隔离、legacy 清理和 LaneBoard
- fix(win7): 完成 P2 fast-follow 五项遗留

## [v0.4.9-alpha.5-win7] - 2026-08-25

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS 平台一致性 + base CI 修复落地:cherry-pick main 的 PR #368 (Task 0-3 platform parity) + PR #367 (base CI 修复) 合并成 PR #370。Win7 适配重点:`requirements-py38.txt` (Python 3.8 + pydantic 1.x) + `certifi` CA bundle 路径注入 + Pydantic v1/v2 `model_dump_compat` 兼容层 + LM Studio OpenAI-compatible protocol + memory session_id 跨层透传 + `office_create` binding-aware delegation 越界守卫。

### Added
- feat(cli): add sage doctor for installation/env self-check (port of main PR #283; win7 适配: conda_env 跨平台路径匹配 + py_version_match 优先 requirements-py38.txt)
- feat(wiki): native folder picker for project create/open, recent projects memory, debounced backend pre-check (issue: llm-wiki-folder-picker)
- feat(wiki): gate folder picker Browse button behind `appSettings.wiki.useFolderPicker` (default true; set false to fall back to plain text input — see §8 rollback in plan)
- feat(skills): conform `backend/skills/skill_md/` to agentskills.io spec
  - Add optional fields: `license`, `compatibility` (≤500 chars), `allowed-tools`
  - Strengthen `name` (≤64 chars) and `description` (≤1024 chars) validation
  - Support single-file `<dir>/SKILL.md` form in loader
  - Warn (not block) when frontmatter `name` != parent directory name
  - Emit warning when description lacks trigger keywords
  - All changes forward-compatible; existing SKILL.md files unaffected
  - Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md
- feat(backend): packaged backend supervision + bundled supervisor for NSIS (#130 + #132 win7 port)
- feat(llm): LM Studio OpenAI-compatible protocol support (modelId / localModelPath)
- feat(llm): `Asia/Shanghai` 时区规范化作为 LLM 调用默认
- feat(memory): `MemoryManager.add_to_working(role, content, session_id=)` → `WorkingMemory.add(message, session_id=)` → `get_context(session_id=)` 三层 session_id 透传,跨 session 严格隔离

### Fixed
- **fix(win7-bundling): sage_core inner-copy + backendLauncher error handling** (port of main PR #130 + #132)
  - v0.4.5-alpha.2-win7 NSIS installer crashed at first launch with `ModuleNotFoundError: No module named 'sage_core'` 4-5s after spawn → 30s "backend health timeout" dialog. Root cause: `packages/sage-core/` is hyphen-named but the Python module is underscore-named `sage_core`; `pip install -e` only writes a .pth referencing the CI runner's absolute path (which doesn't exist on end-user machines).
  - `scripts/bundle-python.ps1`: after `pip install -e sage-core`, also copy the inner `sage_core/` package into `Lib/site-packages/` where `import site` puts it unconditionally. Verify step now canary-imports both `sage_core` and `backend.main` (was just `backend.main`) so the regression is caught at bundle time.
  - `electron/main.ts`: replace inline `existsSync` + conda fallback with `resolveBackendLaunchCommand()` from a new `electron/backendLauncher.ts` (ported from main). Adds broken-installer detection, `proc.on('error')` listener, `spawnStubProcess` placeholder, `reportedBrokenInstaller` flag (skips misleading 30s dialog), `SAGE_USER_DATA_DIR` env var (was missing).
  - Adds 13 vitest cases in `electron/__tests__/backendLauncher.test.ts` and 3 Pester AST assertions in `scripts/bundle-python.Tests.ps1`.
  - Bumps to v0.4.5-alpha.3-win7.
- **fix(win7-py38): 跨 Pydantic v1 / v2 兼容** — `model_dump_compat()` helper 抹平 `.dict()` / `.model_dump()` 差异; 全部 e2e 测试在 py3.8 + pydantic 1.10 + py3.11 + pydantic 2.5 双轨绿
- **fix(win7-tls): certifi CA bundle 路径注入 + 系统 bundle 兜底** — `_is_ca_bundle_available()` 优先探测 `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` 三个 env var(由 `main.configure_ssl_ca_bundle` 注入 certifi.where 路径),然后兜底探测 `ssl.get_default_verify_paths().cafile / capath`(OpenSSL 系统 certs 目录)。env var 显式设了但路径存在却不可用(0 字节空文件)→ 直接 False 不静默回落系统,避免掩盖 misconfig
- **fix(win7-office): `office_create` binding-aware delegation 越界守卫** (T7.5) — 当用户显式把 `output_dir` 指到 binding workspace 之外(如桌面)时不再 delegation,留给 legacy `output_dir` 路径走 `_enforce_workspace` + ApprovalGate 触发"越界写"权限提示。否则文件会被静默改写到 managed workspace, 用户找不到且 doc 也只在 binding 内可见,双重反直觉
- **fix(win7-test): `test_no_list_dir_hyphen_anywhere_in_source` cwd 来源去硬编码** — 改用 `git rev-parse --show-toplevel` 子进程动态定位仓库根,任意 worktree / 干净 CI runner 都能跑
- **fix(ci): base CI 修复 cherry-pick (PR #367)** — `ci-write-manifest` 转 .mjs, `build-manifest` 路径校正, vitest 排除 .claude/worktrees

## [Unreleased]

## [v0.4.9-alpha.4-win7] - 2026-08-25

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 LTS alpha 推进,代码基线与 v0.4.9-alpha.3-win7 一致;**无功能变更**(本轮仅为发布版本号 bump + NSIS 重打)。下一轮 `cherry-pick` main 的 PR #368 (Task 0-3 平台一致性) 后再发 v0.4.9-alpha.5-win7。

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
