# R93 批次计划 —— API Client 测试覆盖收口（第三批）

日期：2026-09-20 ｜ worktree：`.worktrees/feat-r93-api-tests-3`（基于 origin/main f8244c27）

## 背景

r90 已收口 promptApi / mcpClient / agentsApi / runtimeApi / messageApi。再扫描
`src/shared/api/` 无专属测试的 client，挑出 4 个有行为面的：

| 文件 | 行数 | 面积 |
| --- | --- | --- |
| `worktreeApi.ts` | 213 | #1308 新增（会话级 worktree 模式）。wire snake_case→camelCase 映射、status/kind 回退、merge 信封解包、条件载荷 |
| `journalApi.ts` | 69 | office journal 模板 5 端点的通道与字段映射 |
| `learnApi.ts` | 37 | 显式复盘触发；withRetry 包装 |
| `attachmentRagClient.ts` | 76 | r59 向量 RAG client；index/search/delete 条件载荷（target_chunk_size/media_ids/limit），无错误包装（原样抛出） |

demo*/desktopEvent/orchEvents/orchEventStream 留待后续（属事件流/demo 面板，
价值密度低于本批）。

## 批次内容

新增 4 个测试文件（`src/shared/api/__tests__/`）：

1. `worktreeApi.test.ts`（12 用例）——三态 status 直通与未知回退 active、
   kind 未知回退 local、branches 默认 includeRemote=true、create 默认
   baseRef='HEAD' 且 worktree=null 透传、merge 解包 result 信封、remove
   默认 deleteBranch=false、handleApiError 包装。
2. `journalApi.test.ts`（6 用例）——parse/list/get/validate/fill 通道与
   snake_case 字段映射、错误包装。
3. `learnApi.test.ts`（3 用例）——trigger 载荷（prompt 缺省空串）、
   withRetry 错误包装（fake timers，4 次调用）。
4. `attachmentRagClient.test.ts`（6 用例）——index 条件 target_chunk_size、
   search 条件 media_ids/limit、delete 幂等返回、IPC 失败原样抛出
   （rejects.toBe 原错误对象，锁定"无 handleApiError 包装"契约）。

## 验证矩阵

- vitest run 4 文件：27/27 通过（本机，node_modules junction + 即摘协议）。
- CI Frontend (TypeScript) 为准（本机 junction 缺 docx-preview，tsc 有假阳性；
  r90 同批次 CI Frontend 绿已证明该模式可靠）。

## 不做

- 不改任何源码（纯测试批次）。
- 不动 win7 分支（测试增强不回移）。
