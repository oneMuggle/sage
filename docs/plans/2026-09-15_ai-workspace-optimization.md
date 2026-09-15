# Sage AI 工作区优化：三阶段实施方案

## Context
用户确认实施全部三项优化：来源与引用、产物迭代、项目上下文聚合。目标是打通“资料→回答→成果→复用”，而非新增重复入口。只针对 main，不同步或合并 release/win7。

已创建工作树 `/home/fz/project/sage/.claude/worktrees/sage-ai-workspace-optimization`，分支 `worktree-sage-ai-workspace-optimization`。实施前核实分支基线、工作区状态和独立服务端口；不覆盖其他会话的文件或服务。

## 设计约束
- 复用现有项目注册表、session workspace binding、Wiki NDJSON 流、产物预览、路径授权及数据库迁移模式。
- Wiki 授权基于 `authorize_registered_project`；产物操作校验 artifact/session 归属及实际文件权限。
- 不新增第二套向量库，不重造 Office 编辑器，不改全站消息协议来实现局部 Wiki 功能。
- 保持 HTML 沙盒；所有路径和来源标识在服务端校验，拒绝越界、符号链接逃逸和失效授权。
- 本次不包含团队协作、云同步、自动共享、后台自动执行或 Win7 回移。

## 阶段一：来源选择与可核实引用
关键文件：`src/widgets/wiki/WikiChat.tsx`、`src/features/wiki/useWikiChatStream.ts`、`src/shared/api-client/wiki.ts`、`src/entities/wiki/store.ts`、`backend/api/wiki_routes.py`、`backend/wiki/chat.py`、`backend/wiki/vector_store.py` 及相关测试。

1. 在现有 Wiki 文件列表基础上提供本次问答来源勾选。未指定表示全部可用来源；显式空选择禁用提问，后端不得回退为全库检索。过滤在检索排名前执行，随后读取也再次限制范围。
2. 定义结构化引用：稳定 ID、项目内相对路径、标题、原文摘录、内容 hash、行/段落位置及 chunk index。第一版定位已索引 Wiki 文本的行/段落；没有可靠页码映射的 PDF/Office 只打开文件并说明不能精确定位，不编造页码。
3. 服务端从实际送入模型的检索片段构建引用目录；模型仅引用目录内 ID。修正当前 `backend/wiki/chat.py` 仅返回路径且可能把未进入 prompt 的页面加入 citations 的问题。
4. NDJSON、Electron 转发、hook 与消息渲染同步更新。完成的回答及引用入当前聊天消息列表，下一轮不覆盖上一轮；切换项目不残留旧来源、旧流或旧回答。
5. 点击或键盘聚焦引用可查看摘录；hash 不一致显示来源已变化，不悄悄高亮错误位置。

验收：选两个文件只使用这两个；空结果明确提示；每轮引用独立保留；定位成功及来源变更均有清晰反馈；越界路径拒绝。

## 阶段二：产物选段修改与版本恢复
关键文件：`src/widgets/chat/artifacts/ArtifactViewer.tsx`、现有 artifact store/API、`backend/api/artifact_routes.py`、`backend/data/artifact_repo.py`、`backend/data/artifact_reader.py`、现有数据库迁移目录。复用适合纯文本的 diff 机制；`workspace_revert.py` 的 Git 撤销不作为产物版本恢复实现。

1. 仅对 UTF-8 Markdown、代码、HTML 开启文本编辑面板。HTML 的选段在源码文本视图进行，预览继续使用沙盒。Office/PDF 不开放该编辑入口。
2. 提交 artifact ID、base hash、选中原文与位置、修改要求。服务端验证原文与位置，覆盖 emoji/中文/CRLF。
3. 使用现有模型配置与调用服务生成候选替换，不写原文件。候选只替换指定范围，返回完整候选差异与服务端 proposal ID。
4. 用户整体接受或拒绝候选；应用前再次验证 base hash，冲突拒绝覆盖。
5. 持久化初始版本、应用版本及恢复版本。恢复先预览差异，再创建新的当前版本，历史不删除；版本不依赖 Git 仓库。
6. 同一产物写操作串行化，原子替换；文本上限 1 MiB，单产物最多 100 版本，达到限制拒绝并提示。

验收：生成候选不改文件；拒绝无副作用；接受后结果与 diff 一致；外部修改返回冲突；重启后可查看并恢复版本；其他 session 无法编辑。

## 阶段三：项目概览与上下文沉淀
关键文件：`backend/data/project_repo.py`、`backend/api/project_routes.py`、现有数据库迁移、`src/shared/api/projectApi.ts`、`src/widgets/sidebar/sections/ProjectSection.tsx`、现有会话消息菜单及主聊天上下文装配入口。

1. 扩展项目元数据：说明、项目指令、明确选中的资料；会话归属仍复用活跃 workspace binding，不另建归属关系。
2. 项目增加概览入口，聚合说明、资料、会话、成果；保留快速打开最近会话。列表分页，大文件按需加载。
3. 资料由用户显式添加，不自动读取整个目录。支持删除关联、打开原文和查看可用/失效状态。
4. 已绑定项目的新会话与后续请求加载项目指令及选定资料，优先级为应用安全规则＞项目指令＞全局风格偏好；资料作为不可信内容，不能覆盖指令。
5. 项目上下文按 project ID 和 binding 隔离，默认不自动引入其他项目聊天。沿用已有预算裁剪机制，显示被排除/截断资料。
6. 保存回答通过服务端 message ID 验证归属；Wiki 临时回答允许提交可见文本作为用户显式资料，不保存思考、工具日志、凭据。保留来源元数据与会话回链。
7. 保存为项目 Markdown 资料，按项目+来源消息/内容 hash 去重，复用已有资料解析/检索机制；索引失败显示待重试。

验收：新会话能复用显式资料与指令；项目隔离；保存回答可打开并再次作为来源使用；重复保存不重复创建；移除资料后后续请求不再引用。

## 实施与验证顺序
- [x] M0：核实基线、独立端口与环境，写入仓库计划，定位调用链与测试夹具。
- [x] M1：来源协议、检索范围、引用定位与流式 UI 闭环。
  - 92 测试通过（48 backend + 44 frontend/electron），tsc 0 错误，lint 0 错误
  - Abort 归属验证：wikiStreamOwners {token, sender} 三重匹配 cancel，StrictMode 两次 mount 使用不同 token 隔离
  - 关键修复：检索前过滤 allowed_paths（HNSW label filter + JSON filter）、
    引用仅在 budget truncation 后从实际 prompt 内容生成、Promise.all 先订阅后启动、
    500 上限前端默认选择 + 提示、locate 端点 line_start > len(lines) 返回 422
- [x] M2 后端：版本历史与 apply-edit 闭环。
  - `artifact_versions` 表（DDL in `backend/data/database.py`），复合 PK `(artifact_id, version_num)`
  - `backend/data/artifact_version_repo.py`：create_version / list_versions / get_version / get_latest_version / apply_edit
  - `backend/api/artifact_routes.py`：4 新端点 GET versions、GET version/{n}、POST restore、PUT 更新
  - 每产物 asyncio.Lock 串行化写；base_hash 冲突 → 409；1 MiB 文本上限；100 版本上限；原子替换（tmp + rename）
  - 58 artifact 测试通过（42 已有 + 16 新增，含 7 API / 4 repo / 2 schema）
  - LLM-based 编辑候选生成（propose endpoint）待实现，不影响版本恢复主路径
- [x] M2 前端：编辑面板、版本选择器、API client 函数
  - `artifactApi.ts` 新增 4 个版本 API + 3 个接口（list/get/restore/update）
  - `useArtifactContent.ts` 新增 `refresh` callback（版本恢复后刷新内容）
  - `VersionHistory.tsx` 可折叠版本列表面板，展开加载 + 恢复按钮 + loading/error/empty 状态
  - `ArtifactViewer.tsx` 编辑模式（EDITABLE_KINDS: markdown/code/json/text/csv）+ SHA-256 base_hash + 保存/取消 + VersionHistory 集成
  - 22 artifact 前端测试全绿，tsc 0 错误
- [x] M3：项目概览、资料管理、上下文注入与回答沉淀闭环。
  - `project_materials` 表（DDL in `backend/data/database.py`）+ 复合 UNIQUE INDEX `(project_id, content_hash)`
  - `backend/data/project_material_repo.py`：add / get / list_by_project / list_active_for_injection / remove
  - `backend/data/project_repo.py`：PATCH 端点支持 description/instructions（model_fields_set 语义只改传入字段）
  - `backend/api/project_routes.py`：5 新端点 PATCH /materials/{id}、POST /materials、DELETE /materials/{material_id}、GET /materials、POST /materials/save-answer
  - `backend/chat/project_context.py`：ProjectMetadata + active materials 注入 chat context，优先级 安全 > 项目指令 > 全局偏好；资料作为不可信内容，标注 `[untrusted]`
  - `backend/api/legacy_routes.py`：`save_answer_to_project` 路径处理 403 message_project_mismatch
  - 50 M3 后端测试全绿（repo + routes + metadata context + 集成测试）
  - `electron/commands.ts` 新增 5 IPC 通道（projects_update / list_materials / add_material / remove_material / save_answer）
  - `src/shared/api/projectApi.ts` 新增 5 TypeScript 方法 + ProjectMaterial / ProjectUpdatePatch 类型 + mapProject / mapMaterial mapper
  - `src/widgets/sidebar/sections/ProjectSection.tsx`：项目概览面板（description/instructions textarea + 局部 dirty 检测 + 保存）+ 资料管理面板（status badge + add via textarea + remove + 1 MiB 上限前端拦截）+ 保存回答按钮（从当前会话最近 assistant 消息取 messageId）
  - i18n：zh.ts + en.ts lockstep 新增 30 keys（materials_*, overview_*, save_answer_*）
  - ProjectSection.test.tsx：29 测试全绿（17 旧 P1-P5 + 12 新 M3 用例）
  - tsc 0 错误、eslint 0 错误、build 成功（39.42s）、pre-existing 不相关失败（TemplateFillDialog JSON、WikiChat.sources 超时）已确认与 M3 无关
- [ ] M4：跨功能回归、桌面验证、安全及代码审查、更新技术/用户手册。

每阶段先写失败测试，再实现；Python 使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不向共享环境安装依赖。前端运行 Vitest、类型检查、lint、构建；后端运行针对性 pytest、真实临时数据库集成测试、路径与权限测试。新增关键服务覆盖率目标至少80%。

按项目 run-desktop 流程启动独立 Vite 与 Electron，使用隔离测试数据和匹配认证 token。实测选择来源—生成回答—点击定位—保存回答—再次引用，以及失败、取消、重试、项目切换、来源变化、版本冲突、HTML 沙盒和原有预览/授权回归。每阶段进行代码与安全审查。未获明确授权不提交、不推送、不创建 PR、不改 CI。
